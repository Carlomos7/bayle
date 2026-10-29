//! Bayle's Tauri shell: the gateway (ADR 0015), the updater and the recovery screen (ADR 0016). The web view reaches the
//! engine only through these commands; updates are the shell's and work with the engine down.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod files;
mod ui;

use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};

use bayle_gateway::{EngineCommand, Gateway};
use files::{Shown, WindowAction};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use tauri::{AppHandle, Manager, RunEvent, State, ipc::Channel};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_updater::{Update, UpdaterExt};
use tokio::sync::broadcast::error::RecvError;
use ui::{EngineStatus, Redact, UiError, UiMessage};

const ISSUES_URL: &str = "https://github.com/Carlomos7/bayle/issues/new";
/// Where a release's channel manifests live (`<base>/<channel>.json`, ADR 0016). Fixed, so no build setting can point a
/// release elsewhere; the updater also refuses plain http unless the config allows it, which only the dev config does.
const RELEASE_UPDATE_BASE: &str = "https://carlomos7.github.io/bayle/updates";
/// A development identity's manifests: BAYLE_UPDATE_BASE, else the local server of the installer tests.
const DEV_UPDATE_BASE: &str = "http://127.0.0.1:8765";
const CHANNELS: [&str; 2] = ["stable", "beta"];
/// The channel this install follows, in the state folder so it survives updates.
const CHANNEL_FILE: &str = "update-channel";

/// Where this run keeps its state, its update channel, and the update found by the last check.
struct Shell {
    state_dir: PathBuf,
    channel: Mutex<String>,
    update_base: String,
    pending: Mutex<Option<Update>>,
    redact: Arc<Redact>,
    /// React drew the window (app_ui_ready); until then watch_ui may show the shell's own fallback.
    ui_ready: AtomicBool,
}

/// The forwarding task of each open event channel, by channel id, so `engine_unsubscribe` can end it.
#[derive(Default, Clone)]
struct Subscriptions(Arc<Mutex<HashMap<u32, tauri::async_runtime::JoinHandle<()>>>>);

#[derive(Serialize)]
struct UpdateInfo {
    version: String,
    current: String,
    notes: Option<String>,
}

/// What About shows: this build, its update channel and the folder that holds Bayle's data.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct AppInfo {
    version: String,
    channel: String,
    data_folder: String,
    platform: &'static str,
}

#[tauri::command]
fn app_info(app: AppHandle, shell: State<'_, Shell>) -> AppInfo {
    AppInfo {
        version: app.package_info().version.to_string(),
        channel: shell.channel.lock().unwrap().clone(),
        data_folder: shell.state_dir.to_string_lossy().into_owned(),
        platform: std::env::consts::OS,
    }
}

#[tauri::command]
async fn engine_call(
    gateway: State<'_, Gateway>,
    operation: String,
    params: Option<Map<String, Value>>,
    epoch: Option<u64>,
) -> Result<Value, UiError> {
    if epoch.is_some_and(|e| e != gateway.status().generation) {
        return Err(UiError::new(
            "stale_epoch",
            "That was for an engine that has since restarted.",
        ));
    }
    Ok(gateway
        .call_params(&operation, params.unwrap_or_default())
        .await?)
}

#[tauri::command]
fn engine_status(gateway: State<'_, Gateway>, shell: State<'_, Shell>) -> EngineStatus {
    ui::engine_status(&gateway.status(), &shell.redact)
}

/// The current status, then every gateway event from now on, in order, on the page's channel.
#[tauri::command]
fn engine_subscribe(
    gateway: State<'_, Gateway>,
    shell: State<'_, Shell>,
    subs: State<'_, Subscriptions>,
    channel: Channel<UiMessage>,
) {
    let mut events = gateway.subscribe(); // before the status, so no change falls between them
    let gateway = gateway.inner().clone();
    let id = channel.id();
    let map = subs.inner().clone();
    let redact = shell.redact.clone();
    let handle = tauri::async_runtime::spawn(async move {
        let current = |gateway: &Gateway| UiMessage::Status {
            status: ui::engine_status(&gateway.status(), &redact),
        };
        if channel.send(current(&gateway)).is_ok() {
            loop {
                let message = match events.recv().await {
                    Ok(event) => ui::message(event, &redact),
                    Err(RecvError::Lagged(_)) => Some(current(&gateway)),
                    Err(RecvError::Closed) => break,
                };
                if message.is_some_and(|m| channel.send(m).is_err()) {
                    break; // the page went away
                }
            }
        }
        map.0.lock().unwrap().remove(&id);
    });
    subs.0.lock().unwrap().insert(id, handle);
}

#[tauri::command]
fn engine_unsubscribe(subs: State<'_, Subscriptions>, channel_id: u32) {
    if let Some(handle) = subs.0.lock().unwrap().remove(&channel_id) {
        handle.abort();
    }
}

/// The recovery screen's Retry.
#[tauri::command]
async fn engine_restart(gateway: State<'_, Gateway>) -> Result<(), UiError> {
    gateway.restart();
    Ok(())
}

/// Development builds only: end the engine as a crash would. Does nothing in a release build.
#[tauri::command]
fn dev_kill_engine(gateway: State<'_, Gateway>) {
    #[cfg(debug_assertions)]
    gateway.kill_engine();
    #[cfg(not(debug_assertions))]
    let _ = gateway;
}

/// React calls this once it has drawn the window.
#[tauri::command]
fn app_ui_ready(shell: State<'_, Shell>) {
    shell.ui_ready.store(true, Ordering::SeqCst);
}

/// How long the UI gets to draw itself before the shell offers its own way out (ADR 0016, criterion 7).
const UI_GRACE: Duration = Duration::from_secs(20);
const FALLBACK_UPDATE: &str = "Install the latest update";
const FALLBACK_REPORT: &str = "Open logs and report";

/// A UI that never draws (a broken release) leaves a blank, frameless window: give it a frame and offer, natively,
/// the recovery screen's actions that need no UI.
fn watch_ui(app: AppHandle) {
    std::thread::spawn(move || {
        std::thread::sleep(UI_GRACE);
        if app.state::<Shell>().ui_ready.load(Ordering::SeqCst) {
            return;
        }
        if let Some(w) = app.get_webview_window("main") {
            let _ = w.set_decorations(true);
        }
        ui_fallback(app, "");
    });
}

fn ui_fallback(app: AppHandle, said: &str) {
    use tauri_plugin_dialog::{MessageDialogButtons, MessageDialogKind, MessageDialogResult};
    let text = format!(
        "{said}Bayle's window didn't load. Your profiles, mods and saves are not affected.\n\nInstall the latest \
         update to fix it, or open the logs and report it. Reinstalling Bayle from its installer also fixes it."
    );
    let handle = app.clone();
    app.dialog()
        .message(text)
        .title("Bayle")
        .kind(MessageDialogKind::Error)
        .buttons(MessageDialogButtons::YesNoCancelCustom(
            FALLBACK_UPDATE.into(),
            FALLBACK_REPORT.into(),
            "Close Bayle".into(),
        ))
        .show_with_result(move |r| match r {
            MessageDialogResult::Yes => fallback_update(handle),
            MessageDialogResult::Custom(l) if l == FALLBACK_UPDATE => fallback_update(handle),
            MessageDialogResult::No => fallback_report(handle),
            MessageDialogResult::Custom(l) if l == FALLBACK_REPORT => fallback_report(handle),
            _ => handle.exit(0),
        });
}

fn fallback_report(app: AppHandle) {
    let _ = app_open_logs(app.clone(), app.state::<Shell>());
    let _ = app_report_issue(app.clone());
    ui_fallback(app, "");
}

fn fallback_update(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        // the same signed path as Settings: an install restarts the app; anything else comes back here
        let said = match app_update_check(app.clone(), app.state::<Shell>()).await {
            Ok(Some(_)) => {
                match app_update_install(app.clone(), app.state::<Gateway>(), app.state::<Shell>())
                    .await
                {
                    Ok(()) => return,
                    Err(e) => format!("The update didn't install: {}\n\n", e.message),
                }
            }
            Ok(None) => "There is no newer version yet.\n\n".to_owned(),
            Err(e) => format!("Bayle couldn't check for updates: {}\n\n", e.message),
        };
        ui_fallback(app, &said);
    });
}

/// The recovery screen's Open logs: the engine writes its logs in the state folder.
#[tauri::command]
fn app_open_logs(app: AppHandle, shell: State<'_, Shell>) -> Result<(), UiError> {
    let logs = shell.state_dir.join("logs");
    let target = if logs.is_dir() {
        logs
    } else {
        shell.state_dir.clone()
    };
    app.opener()
        .open_path(target.to_string_lossy(), None::<&str>)
        .map_err(UiError::gateway)
}

/// The recovery screen's Report issue.
#[tauri::command]
fn app_report_issue(app: AppHandle) -> Result<(), UiError> {
    app.opener()
        .open_url(ISSUES_URL, None::<&str>)
        .map_err(UiError::gateway)
}

/// Opens a link in the browser: https only.
#[tauri::command]
fn app_open_url(app: AppHandle, url: String) -> Result<(), UiError> {
    let ok = tauri::Url::parse(&url).is_ok_and(|u| u.scheme() == "https" && u.host().is_some());
    if !ok {
        return Err(UiError::new(
            "bad_parameter",
            "Parameter url: only https links open.",
        ));
    }
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(UiError::gateway)
}

/// One row of a file picker's type list: `{name: "Mods", extensions: ["zip", "7z"]}`.
#[derive(Deserialize)]
struct PickFilter {
    name: String,
    extensions: Vec<String>,
}

/// A path chosen in a dialog, as text; None when the dialog was closed without choosing.
fn chosen(path: Option<tauri_plugin_dialog::FilePath>) -> Result<Option<String>, UiError> {
    path.map(|p| {
        p.into_path()
            .map(|p| p.to_string_lossy().into_owned())
            .map_err(UiError::gateway)
    })
    .transpose()
}

/// Asks for one file. The chosen path, or null when the dialog was cancelled.
#[tauri::command]
async fn app_pick_file(
    app: AppHandle,
    title: Option<String>,
    filters: Option<Vec<PickFilter>>,
) -> Result<Option<String>, UiError> {
    let mut dialog = app.dialog().file();
    if let Some(title) = title {
        dialog = dialog.set_title(title);
    }
    for f in filters.unwrap_or_default() {
        let extensions: Vec<&str> = f.extensions.iter().map(String::as_str).collect();
        dialog = dialog.add_filter(f.name, &extensions);
    }
    chosen(dialog.blocking_pick_file())
}

/// Asks for one folder. The chosen path, or null when the dialog was cancelled.
#[tauri::command]
async fn app_pick_folder(app: AppHandle, title: Option<String>) -> Result<Option<String>, UiError> {
    let mut dialog = app.dialog().file();
    if let Some(title) = title {
        dialog = dialog.set_title(title);
    }
    chosen(dialog.blocking_pick_folder())
}

/// Shows a path in the file manager: a folder is opened, a file is only selected in its folder. Never opens a file
/// (so the web view cannot run a program), whatever it asks for.
#[tauri::command]
fn app_open_path(app: AppHandle, path: String) -> Result<(), UiError> {
    let shown = files::classify(&path).map_err(|why| UiError::new("bad_parameter", why))?;
    match shown {
        Shown::Folder(folder) => app
            .opener()
            .open_path(folder.to_string_lossy(), None::<&str>),
        Shown::File(file) => app.opener().reveal_item_in_dir(file),
    }
    .map_err(UiError::gateway)
}

/// Whether the main window is maximized, so the title bar shows Restore instead of Maximize.
#[tauri::command]
fn app_window_maximized(app: AppHandle) -> Result<bool, UiError> {
    app.get_webview_window("main")
        .ok_or_else(|| UiError::gateway("There is no main window."))?
        .is_maximized()
        .map_err(UiError::gateway)
}

/// The window buttons of the main window: `minimize`, `toggle_maximize` or `close`.
#[tauri::command]
fn app_window(app: AppHandle, action: String) -> Result<(), UiError> {
    let action = files::window_action(&action).ok_or_else(|| {
        UiError::new(
            "bad_parameter",
            "Parameter action: minimize, toggle_maximize or close.",
        )
    })?;
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| UiError::gateway("There is no main window."))?;
    match action {
        WindowAction::Minimize => window.minimize(),
        WindowAction::ToggleMaximize if window.is_maximized().map_err(UiError::gateway)? => {
            window.unmaximize()
        }
        WindowAction::ToggleMaximize => window.maximize(),
        WindowAction::Close => window.close(),
    }
    .map_err(UiError::gateway)
}

/// Zips the state folder's logs (only them: never the saves or the settings) where the user picks. The chosen path,
/// or null when the dialog was cancelled.
#[tauri::command]
async fn app_save_support_logs(
    app: AppHandle,
    shell: State<'_, Shell>,
) -> Result<Option<String>, UiError> {
    let logs = shell.state_dir.join("logs");
    if !logs.is_dir() {
        return Err(UiError::new("not_found", "There are no logs yet."));
    }
    let picked = app
        .dialog()
        .file()
        .set_title("Save the support logs")
        .set_file_name("bayle-support-logs.zip")
        .add_filter("Zip archive", &["zip"])
        .blocking_save_file();
    let Some(dest) = chosen(picked)? else {
        return Ok(None);
    };
    let to = PathBuf::from(&dest);
    tauri::async_runtime::spawn_blocking(move || files::zip_logs(&logs, &to))
        .await
        .map_err(UiError::gateway)?
        .map_err(UiError::gateway)?;
    Ok(Some(dest))
}

/// Checks this channel's signed manifest. Only a higher version is offered (no downgrades).
#[tauri::command]
async fn app_update_check(
    app: AppHandle,
    shell: State<'_, Shell>,
) -> Result<Option<UpdateInfo>, UiError> {
    let url = format!(
        "{}/{}.json",
        shell.update_base,
        shell.channel.lock().unwrap()
    );
    let updater = app
        .updater_builder()
        .endpoints(vec![url.parse().map_err(UiError::gateway)?])
        .map_err(UiError::gateway)?
        .build()
        .map_err(UiError::gateway)?;
    let update = updater.check().await.map_err(update_error)?;
    let info = update.as_ref().map(|u| UpdateInfo {
        version: u.version.clone(),
        current: u.current_version.clone(),
        notes: u.body.clone(),
    });
    *shell.pending.lock().unwrap() = update;
    Ok(info)
}

/// Switches the update channel and saves it; the next check uses it.
#[tauri::command]
fn app_set_channel(shell: State<'_, Shell>, channel: String) -> Result<(), UiError> {
    if !CHANNELS.contains(&channel.as_str()) {
        return Err(UiError::gateway(format!("There is no {channel} channel.")));
    }
    std::fs::write(shell.state_dir.join(CHANNEL_FILE), &channel).map_err(UiError::gateway)?;
    *shell.channel.lock().unwrap() = channel;
    *shell.pending.lock().unwrap() = None; // an update found on the other channel is not offered
    Ok(())
}

/// The state folder: the one Windows names, else LOCALAPPDATA when it is an existing absolute folder (Windows can fail
/// to name it for an odd user profile). Never a guess such as the temp folder: data kept there would look lost on the
/// next start, when Windows names the real folder again.
fn state_folder(
    known: Option<PathBuf>,
    local: Option<PathBuf>,
    identifier: &str,
) -> Option<PathBuf> {
    known.or_else(|| {
        local
            .filter(|l| l.is_absolute() && l.is_dir())
            .map(|l| l.join(identifier))
    })
}

/// Stops at startup when there is no state folder, saying why, rather than keeping the user's data somewhere else.
fn no_state_folder() -> ! {
    let text = "Bayle can't find this account's local app data folder (LOCALAPPDATA), so it can't open your \
                profiles, backups and settings. Nothing was changed. Check that LOCALAPPDATA names an existing \
                folder, or sign out and in again, then start Bayle again.";
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::UI::WindowsAndMessaging::{MB_ICONERROR, MB_OK, MessageBoxW};
        let wide = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
        MessageBoxW(
            std::ptr::null_mut(),
            wide(text).as_ptr(),
            wide("Bayle can't start").as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
    eprintln!("{text}");
    std::process::exit(1)
}

/// The saved channel; else Beta for a pre-release version and Stable for a release.
fn saved_channel(state: &std::path::Path, version: &str) -> String {
    std::fs::read_to_string(state.join(CHANNEL_FILE))
        .ok()
        .map(|s| s.trim().to_owned())
        .filter(|c| CHANNELS.contains(&c.as_str()))
        .unwrap_or_else(|| {
            if version.contains('-') {
                "beta"
            } else {
                "stable"
            }
            .to_owned()
        })
}

/// Installs the update found by app_update_check: the engine is stopped first, then the signed installer runs (the
/// signature is verified before anything is installed) and the app restarts on the new version.
#[tauri::command]
async fn app_update_install(
    app: AppHandle,
    gateway: State<'_, Gateway>,
    shell: State<'_, Shell>,
) -> Result<(), UiError> {
    let update = shell
        .pending
        .lock()
        .unwrap()
        .take()
        .ok_or_else(|| UiError::gateway("Check for updates first."))?;
    // download and verify first: a refused update never takes the engine down
    let bytes = update
        .download(|_, _| {}, || {})
        .await
        .map_err(update_error)?;
    gateway.shutdown(Duration::from_secs(10)).await;
    if let Err(e) = update.install(bytes) {
        gateway.restart(); // nothing was installed: bring the engine back
        return Err(update_error(e));
    }
    app.restart();
}

/// An updater failure in words a player can act on; the updater's own text stays in details.reason.
fn update_error(e: tauri_plugin_updater::Error) -> UiError {
    use tauri_plugin_updater::Error as E;
    let (code, message) = match &e {
        E::Reqwest(_) | E::Network(_) => (
            "update_offline",
            "Bayle couldn't reach the update server. Check your internet connection and try again.",
        ),
        E::ReleaseNotFound
        | E::Serialization(_)
        | E::Semver(_)
        | E::TargetNotFound(_)
        | E::TargetsNotFound(_) => (
            "update_unreadable",
            "The update information couldn't be read right now. Try again later.",
        ),
        E::Minisign(_) => (
            "update_untrusted",
            "An update was found, but its signature didn't match Bayle's, so it was not installed.",
        ),
        _ => (
            "update_failed",
            "The update didn't work. Bayle is unchanged; try again later.",
        ),
    };
    let mut err = UiError::new(code, message);
    err.details = serde_json::json!({ "reason": e.to_string() });
    err
}

/// The engine command and the state folder for this build.
fn engine_setup(app: &AppHandle) -> (EngineCommand, PathBuf) {
    let dev = app.config().identifier.ends_with(".dev");
    let state = if cfg!(debug_assertions) {
        std::env::var_os("BAYLE_GATEWAY_DATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| std::env::temp_dir().join("bayle-gateway-dev"))
    } else {
        // ADR 0016: the one state folder; never app_data_dir(), which roams on Windows
        let known = app.path().app_local_data_dir().ok();
        let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
        state_folder(known, local, &app.config().identifier).unwrap_or_else(|| no_state_folder())
    };
    let _ = std::fs::create_dir_all(&state);
    let mut env = vec![(
        "BAYLE_DATA".to_owned(),
        state.to_string_lossy().into_owned(),
    )];
    if dev || cfg!(debug_assertions) {
        // a development identity sees none of the user's folders: no real saves, game data or Qt data. Paths written
        // down earlier (copied settings, undo records) can still name them, so the engine refuses those folders too.
        let protect: Vec<PathBuf> = ["LOCALAPPDATA", "APPDATA"]
            .iter()
            .filter_map(|v| std::env::var_os(v).map(PathBuf::from))
            .collect();
        if let Ok(joined) = std::env::join_paths(&protect) {
            env.push((
                "BAYLE_PROTECT".to_owned(),
                joined.to_string_lossy().into_owned(),
            ));
        }
        for (var, sub) in [
            ("LOCALAPPDATA", "local"),
            ("APPDATA", "roaming"),
            ("USERPROFILE", "home"),
            ("HOME", "home"),
        ] {
            let folder = state.join("sandbox").join(sub);
            let _ = std::fs::create_dir_all(&folder);
            env.push((var.to_owned(), folder.to_string_lossy().into_owned()));
        }
    }
    let exe = if cfg!(windows) {
        "bayle-engine.exe"
    } else {
        "bayle-engine"
    };
    // a debug build runs the source engine: target/debug/engine is a leftover of an earlier bundle and lags the code
    let bundled = app
        .path()
        .resource_dir()
        .ok()
        .filter(|_| !cfg!(debug_assertions))
        .map(|r| r.join("engine").join(exe));
    let command = match bundled.filter(|p| p.is_file()) {
        Some(program) => EngineCommand {
            cwd: program.parent().map(PathBuf::from),
            program,
            args: vec!["--backend".to_owned()],
            env,
            handshake_timeout: Duration::from_secs(60),
        },
        None => {
            // running from the source tree: the engine's own uv project
            let engine = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../engine");
            EngineCommand {
                program: "uv".into(),
                args: [
                    "run",
                    "--quiet",
                    "--project",
                    &engine.to_string_lossy(),
                    "--extra",
                    "api",
                    "bayle-engine",
                    "--backend",
                ]
                .map(String::from)
                .to_vec(),
                cwd: Some(engine),
                env,
                handshake_timeout: Duration::from_secs(120),
            }
        }
    };
    (command, state)
}

fn main() {
    // a broken engine must fail quietly into the recovery screen, never as Windows' own error boxes: the engine
    // inherits this error mode, so a damaged DLL or a crash no longer opens a modal dialog per restart
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::System::Diagnostics::Debug::{
            SEM_FAILCRITICALERRORS, SEM_NOGPFAULTERRORBOX, SetErrorMode,
        };
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let (command, state_dir) = engine_setup(app.handle());
            let gateway = tauri::async_runtime::block_on(async { Gateway::start(command) });
            app.manage(gateway);
            let channel = saved_channel(&state_dir, &app.package_info().version.to_string());
            let update_base = if app.config().identifier.ends_with(".dev") {
                std::env::var("BAYLE_UPDATE_BASE").unwrap_or_else(|_| DEV_UPDATE_BASE.to_owned())
            } else {
                RELEASE_UPDATE_BASE.to_owned()
            };
            let home = std::env::var("USERPROFILE")
                .or_else(|_| std::env::var("HOME"))
                .unwrap_or_default();
            let install = app
                .path()
                .resource_dir()
                .map(|p| p.to_string_lossy().into_owned())
                .unwrap_or_default();
            // most specific first: the install and data folders may sit under the home folder
            let redact = Redact(vec![
                (install, "the install folder"),
                (state_dir.to_string_lossy().into_owned(), "the data folder"),
                (home, "~"),
            ]);
            app.manage(Subscriptions::default());
            app.manage(Shell {
                state_dir,
                channel: Mutex::new(channel),
                update_base,
                pending: Mutex::new(None),
                redact: Arc::new(redact),
                ui_ready: AtomicBool::new(false),
            });
            watch_ui(app.handle().clone());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_call,
            engine_status,
            engine_subscribe,
            engine_unsubscribe,
            engine_restart,
            dev_kill_engine,
            app_open_logs,
            app_report_issue,
            app_open_url,
            app_pick_file,
            app_pick_folder,
            app_open_path,
            app_window,
            app_window_maximized,
            app_save_support_logs,
            app_info,
            app_update_check,
            app_set_channel,
            app_update_install,
            app_ui_ready
        ])
        .build(tauri::generate_context!())
        .expect("the Tauri app");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            let gateway = handle.state::<Gateway>().inner().clone();
            tauri::async_runtime::block_on(gateway.shutdown(Duration::from_secs(5)));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_update_failure_is_said_in_plain_words_with_the_reason_kept() {
        use tauri_plugin_updater::Error as E;
        let e = update_error(E::Network(
            "error sending request for url (https://x/beta.json)".into(),
        ));
        assert_eq!(e.code, "update_offline");
        assert!(e.message.contains("internet connection") && !e.message.contains("url"));
        assert!(e.details["reason"].as_str().unwrap().contains("beta.json"));
        assert_eq!(update_error(E::ReleaseNotFound).code, "update_unreadable");
        assert_eq!(update_error(E::EmptyEndpoints).code, "update_failed");
    }

    #[test]
    fn the_state_folder_is_never_a_guess() {
        let dir = tempfile::tempdir().unwrap();
        let id = "io.github.carlomos7.bayle";
        let known = dir.path().join("known").join(id);
        // Windows names it: that one, whatever LOCALAPPDATA says
        assert_eq!(
            state_folder(Some(known.clone()), Some(dir.path().into()), id),
            Some(known)
        );
        // Windows can't: LOCALAPPDATA, only when it is an existing absolute folder
        assert_eq!(
            state_folder(None, Some(dir.path().into()), id),
            Some(dir.path().join(id))
        );
        assert_eq!(state_folder(None, Some(dir.path().join("gone")), id), None);
        assert_eq!(state_folder(None, Some("relative".into()), id), None);
        assert_eq!(state_folder(None, None, id), None);
    }

    #[test]
    fn the_channel_is_the_saved_one_else_follows_the_version() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(saved_channel(dir.path(), "6.0.0-beta.1"), "beta");
        assert_eq!(saved_channel(dir.path(), "6.0.0"), "stable");
        std::fs::write(dir.path().join(CHANNEL_FILE), "stable\n").unwrap();
        assert_eq!(saved_channel(dir.path(), "6.0.0-beta.1"), "stable");
        std::fs::write(dir.path().join(CHANNEL_FILE), "nightly").unwrap();
        assert_eq!(saved_channel(dir.path(), "6.0.0"), "stable");
    }
}
