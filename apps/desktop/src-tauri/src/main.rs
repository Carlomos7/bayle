// No console window in release builds on Windows.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // TODO(velopack): `velopack::VelopackApp::build().set_auto_apply_on_startup(false).run()` must be the first call
    // here, on Windows only (cfg(windows)); see tools spikes/velopack-tauri/RESULTS.md. Crate not added yet.
    bayle_desktop_lib::run()
}
