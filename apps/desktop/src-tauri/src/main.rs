//! Bayle's Tauri shell, Phase 0: the gateway (ADR 0015) behind a development page. The web view reaches the engine
//! only through these commands; it never sees the engine's port or token.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{path::PathBuf, time::Duration};

use bayle_gateway::{EngineCommand, Gateway, GatewayError, GatewayEvent, Status};
use serde_json::{Map, Value};
use tauri::{Manager, RunEvent, State, ipc::Channel};
use tokio::sync::broadcast::error::RecvError;

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

/// Development builds only: end the engine as a crash would, to try the restart path. Does nothing in a release build.
#[tauri::command]
fn dev_kill_engine(gateway: State<'_, Gateway>) {
    #[cfg(debug_assertions)]
    gateway.kill_engine();
    #[cfg(not(debug_assertions))]
    let _ = gateway;
}

/// shortcut: always `uv run` on the source engine with a scratch data folder; the frozen engine and the real data
/// folder come with packaging (step D5) and the installer decision (D6).
fn engine_command() -> EngineCommand {
    let engine = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../engine");
    let scratch = std::env::var_os("BAYLE_GATEWAY_DATA")
        .map(PathBuf::from)
        .unwrap_or_else(|| std::env::temp_dir().join("bayle-gateway-dev"));
    let dir = |name: &str| {
        let p = scratch.join(name);
        let _ = std::fs::create_dir_all(&p);
        p.to_string_lossy().into_owned()
    };
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
        // never the real data folder in Phase 0: the engine moves and migrates files in it at start
        env: vec![
            ("BAYLE_DATA".into(), dir("data")),
            ("LOCALAPPDATA".into(), dir("local")),
            ("APPDATA".into(), dir("roaming")),
            ("USERPROFILE".into(), dir("home")),
            ("HOME".into(), dir("home")),
        ],
        handshake_timeout: Duration::from_secs(120),
    }
}

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let gateway =
                tauri::async_runtime::block_on(async { Gateway::start(engine_command()) });
            app.manage(gateway);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            engine_call,
            engine_status,
            engine_events,
            dev_kill_engine
        ])
        .build(tauri::generate_context!())
        .expect("the Tauri app");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            handle.state::<Gateway>().shutdown();
        }
    });
}
