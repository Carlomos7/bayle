fn main() {
    // tauri.conf.json bundles the frozen engine from here. A debug build runs the engine from source instead, so an
    // empty folder is enough for it; a release build must have the real one.
    let engine = std::path::Path::new("../target/engine-dist/bayle-engine");
    if !engine.join("bayle-engine.exe").exists() && !engine.join("bayle-engine").exists() {
        if std::env::var("PROFILE").as_deref() == Ok("release") {
            panic!(
                "the frozen engine is missing: run `uv run --project apps/engine python apps/desktop/scripts/build_engine.py` from the repo root first"
            );
        }
        std::fs::create_dir_all(engine).expect("create the engine resource folder");
    }
    tauri_build::build()
}
