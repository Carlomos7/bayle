//! Bayle's Tauri shell: the gateway (ADR 0015), the updater and the recovery screen (ADR 0016). The web view reaches the
//! engine only through these commands; updates are the shell's and work with the engine down.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{path::PathBuf, sync::Mutex, time::Duration};

use bayle_gateway::{EngineCommand, Gateway, GatewayError, GatewayEvent, Status};
use serde::Serialize;
use serde_json::{Map, Value};
use tauri::{AppHandle, Manager, RunEvent, State, ipc::Channel};
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_updater::{Update, UpdaterExt};
use tokio::sync::broadcast::error::RecvError;

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
}

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
    path: Option<Map<String, Value>>,
    query: Option<Map<String, Value>>,
    body: Option<Value>,
) -> Result<Value, GatewayError> {
    gateway
        .call(
            &operation,
            path.unwrap_or_default(),
            query.unwrap_or_default(),
            body,
        )
        .await
}

#[tauri::command]
fn engine_status(gateway: State<'_, Gateway>) -> Status {
    gateway.status()
}

/// Every gateway event from now on, in order, on the page's channel.
#[tauri::command]
fn engine_events(gateway: State<'_, Gateway>, channel: Channel<GatewayEvent>) {
    let mut events = gateway.subscribe();
    tauri::async_runtime::spawn(async move {
        loop {
            let event = match events.recv().await {
                Ok(event) => event,
                Err(RecvError::Lagged(missed)) => GatewayEvent::Lagged { missed },
                Err(RecvError::Closed) => break,
            };
            if channel.send(event).is_err() {
                break; // the page went away
            }
        }
    });
}

/// The recovery screen's Retry.
#[tauri::command]
async fn engine_restart(gateway: State<'_, Gateway>) -> Result<(), ()> {
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
fn open_logs(app: AppHandle, shell: State<'_, Shell>) -> Result<(), String> {
    let logs = shell.state_dir.join("logs");
    let target = if logs.is_dir() {
        logs
    } else {
        shell.state_dir.clone()
    };
    app.opener()
        .open_path(target.to_string_lossy(), None::<&str>)
        .map_err(|e| e.to_string())
}

/// The recovery screen's Report issue.
#[tauri::command]
fn report_issue(app: AppHandle) -> Result<(), String> {
    app.opener()
        .open_url(ISSUES_URL, None::<&str>)
        .map_err(|e| e.to_string())
}

/// Checks this channel's signed manifest. Only a higher version is offered (no downgrades).
#[tauri::command]
async fn update_check(
    app: AppHandle,
    shell: State<'_, Shell>,
) -> Result<Option<UpdateInfo>, String> {
    let url = format!("{UPDATE_BASE}/{}.json", shell.channel);
    let updater = app
        .updater_builder()
        .endpoints(vec![url.parse().map_err(|e| format!("{e}"))?])
        .map_err(|e| e.to_string())?
        .build()
        .map_err(|e| e.to_string())?;
    let update = updater.check().await.map_err(|e| e.to_string())?;
    let info = update.as_ref().map(|u| UpdateInfo {
        version: u.version.clone(),
        current: u.current_version.clone(),
        notes: u.body.clone(),
    });
    *shell.pending.lock().unwrap() = update;
    Ok(info)
}

/// Installs the update found by update_check: the engine is stopped first, then the signed installer runs (the
/// signature is verified before anything is installed) and the app restarts on the new version.
#[tauri::command]
async fn update_install(
    app: AppHandle,
    gateway: State<'_, Gateway>,
    shell: State<'_, Shell>,
) -> Result<(), String> {
    let update = shell
        .pending
        .lock()
        .unwrap()
        .take()
        .ok_or("Check for updates first.")?;
    // download and verify first: a refused update never takes the engine down
    let bytes = update
        .download(|_, _| {}, || {})
        .await
        .map_err(|e| e.to_string())?;
    gateway.shutdown(Duration::from_secs(10)).await;
    if let Err(e) = update.install(bytes) {
        gateway.restart(); // nothing was installed: bring the engine back
        return Err(e.to_string());
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
    let bundled = app
        .path()
        .resource_dir()
        .ok()
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
    // one TLS provider for every HTTP client in the app: the updater plugin's reqwest is built without one, and Cargo
    // unifies that onto the gateway's client, which then panics on creation
    let _ = rustls::crypto::ring::default_provider().install_default();
    // a broken engine must fail quietly into the recovery screen, never as Windows' own error boxes: the engine
    // inherits this error mode, so a damaged DLL or a crash no longer opens a modal dialog per restart
    #[cfg(windows)]
    unsafe {
        use windows_sys::Win32::System::Diagnostics::Debug::{SEM_FAILCRITICALERRORS, SEM_NOGPFAULTERRORBOX, SetErrorMode};
        SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX);
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let (command, state_dir) = engine_setup(app.handle());
            let gateway = tauri::async_runtime::block_on(async { Gateway::start(command) });
            app.manage(gateway);
            let channel =
                std::env::var("BAYLE_UPDATE_CHANNEL").unwrap_or_else(|_| "beta".to_owned());
            app.manage(Shell {
                state_dir,
                channel,
                pending: Mutex::new(None),
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_call,
            engine_status,
            engine_events,
            engine_restart,
            dev_kill_engine,
            open_logs,
            report_issue,
            update_check,
            update_install
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
