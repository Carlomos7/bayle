//! Bayle's Tauri shell: the gateway (ADR 0015), the updater and the recovery screen (ADR 0016). The web view reaches the
//! engine only through these commands; updates are the shell's and work with the engine down.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod files;
mod ui;

use std::{
    collections::HashMap,
    path::PathBuf,
    sync::{Arc, Mutex},
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
/// Where the channel manifests live (`<base>/<channel>.json`). shortcut: a local server for the installer spike;
/// release builds set BAYLE_UPDATE_BASE to the published manifests' address at build time.
const UPDATE_BASE: &str = match option_env!("BAYLE_UPDATE_BASE") {
    Some(base) => base,
    None => "http://127.0.0.1:8765",
};

/// Where this run keeps its state, its update channel, and the update found by the last check.
struct Shell {
    state_dir: PathBuf,
    channel: String,
    pending: Mutex<Option<Update>>,
    redact: Arc<Redact>,
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
    let url = format!("{UPDATE_BASE}/{}.json", shell.channel);
    let updater = app
        .updater_builder()
        .endpoints(vec![url.parse().map_err(UiError::gateway)?])
        .map_err(UiError::gateway)?
        .build()
        .map_err(UiError::gateway)?;
    let update = updater.check().await.map_err(UiError::gateway)?;
    let info = update.as_ref().map(|u| UpdateInfo {
        version: u.version.clone(),
        current: u.current_version.clone(),
        notes: u.body.clone(),
    });
    *shell.pending.lock().unwrap() = update;
    Ok(info)
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
        .map_err(UiError::gateway)?;
    gateway.shutdown(Duration::from_secs(10)).await;
    if let Err(e) = update.install(bytes) {
        gateway.restart(); // nothing was installed: bring the engine back
        return Err(UiError::gateway(e));
    }
    app.restart();
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
        app.path()
            .app_local_data_dir()
            .expect("the app's local data folder")
    };
    let _ = std::fs::create_dir_all(&state);
    let mut env = vec![(
        "BAYLE_DATA".to_owned(),
        state.to_string_lossy().into_owned(),
    )];
    if dev || cfg!(debug_assertions) {
        // a development identity sees none of the user's folders: no real saves, game data or Qt data
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
            let channel =
                std::env::var("BAYLE_UPDATE_CHANNEL").unwrap_or_else(|_| "beta".to_owned());
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
                channel,
                pending: Mutex::new(None),
                redact: Arc::new(redact),
            });
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
            app_save_support_logs,
            app_update_check,
            app_update_install
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
