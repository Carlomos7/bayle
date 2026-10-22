mod engine;
#[cfg(windows)]
mod job;

use engine::Backend;
use std::path::PathBuf;
use std::process::Child;
use std::sync::{Arc, Condvar, Mutex};

use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// The Qt launcher's default and minimum window size (Main.qml), in logical pixels.
const WINDOW_SIZE: (f64, f64) = (1100.0, 760.0);
const WINDOW_MIN: (f64, f64) = (740.0, 540.0);

/// Set once, by the startup thread: the engine's connection details or why there is none.
type Slot = Arc<(Mutex<Option<Result<Backend, String>>>, Condvar)>;
struct Engine(Mutex<Option<Child>>);

#[tauri::command]
async fn get_backend(slot: tauri::State<'_, Slot>) -> Result<Backend, String> {
    let slot = slot.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        let (lock, cv) = &*slot;
        let mut g = lock.lock().unwrap();
        while g.is_none() {
            g = cv.wait(g).unwrap();
        }
        g.clone().unwrap()
    })
    .await
    .map_err(|e| e.to_string())?
}

/// The webview data folder lives with the engine's data, never in the install root (Velopack replaces that on update).
fn webview_dir(app: &AppHandle) -> Result<PathBuf, String> {
    let base = match std::env::var_os("ROUNDTABLE_SOULS_DATA").filter(|v| !v.is_empty()) {
        Some(dir) => PathBuf::from(dir),
        None => app.path().app_local_data_dir().map_err(|e| e.to_string())?,
    };
    Ok(base.join("webview2"))
}

fn start_engine(app: &AppHandle) -> Result<Backend, String> {
    let exe_dir = std::env::current_exe()
        .map_err(|e| e.to_string())?
        .parent()
        .ok_or("no exe dir")?
        .to_path_buf();
    let (child, backend) = engine::start(&exe_dir, &engine::new_token()?)?;
    *app.state::<Engine>().0.lock().unwrap() = Some(child);
    engine::wait_ready(&backend)?;
    Ok(backend)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let slot: Slot = Arc::new((Mutex::new(None), Condvar::new()));
    let app = tauri::Builder::default()
        // registered first, as the plugin requires
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .manage(slot.clone())
        .manage(Engine(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![get_backend])
        .setup(move |app| {
            let dir = webview_dir(app.handle())?;
            std::fs::create_dir_all(&dir)?;
            let main = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Bayle")
                .inner_size(WINDOW_SIZE.0, WINDOW_SIZE.1)
                .min_inner_size(WINDOW_MIN.0, WINDOW_MIN.1)
                .data_directory(dir.clone())
                .visible(false)
                .build()?;
            let splash =
                WebviewWindowBuilder::new(app, "splash", WebviewUrl::App("splash.html".into()))
                    .title("Bayle")
                    .inner_size(400.0, 200.0)
                    .decorations(false)
                    .center()
                    .data_directory(dir)
                    .build()?;
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let result = start_engine(&handle);
                let (lock, cv) = &*slot;
                *lock.lock().unwrap() = Some(result);
                cv.notify_all();
                // the main page shows an engine error itself, so it is shown either way
                let _ = handle.run_on_main_thread(move || {
                    let _ = splash.close();
                    let _ = main.set_size(tauri::LogicalSize::new(WINDOW_SIZE.0, WINDOW_SIZE.1));
                    let _ = main.center();
                    let _ = main.show();
                });
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("cannot build the Bayle shell");
    app.run(|handle, event| {
        if let RunEvent::Exit = event
            && let Some(mut child) = handle.state::<Engine>().0.lock().unwrap().take()
        {
            let _ = child.kill(); // the job object / stdin EOF reap the rest of the tree
        }
    });
}
