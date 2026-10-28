//! What the desktop commands do with the user's files, apart from Tauri: which paths the web view may have shown and
//! how the support bundle is zipped. Pure std + zip, so it is unit-tested here.

use std::{
    fs::File,
    io::{self, Write},
    path::{Path, PathBuf},
};

use zip::{CompressionMethod, ZipWriter, write::SimpleFileOptions};

/// What `app_open_path` may do with a path. Nothing here runs a file: a folder is opened in the file manager, a file
/// is only shown (selected) in it.
#[derive(Debug, PartialEq)]
pub enum Shown {
    Folder(PathBuf),
    File(PathBuf),
}

/// The path the web view asked for, as something the shell may show; the refusal is a sentence for `bad_parameter`.
/// Only absolute local paths of things that exist: no relative path (it would mean the shell's own folder), no network
/// path, no URL.
pub fn classify(path: &str) -> Result<Shown, &'static str> {
    let p = Path::new(path);
    if path.is_empty() || path.contains("://") || !p.is_absolute() {
        return Err("Parameter path: an absolute path of this PC is needed.");
    }
    if path.starts_with(r"\\") || path.starts_with("//") {
        return Err("Parameter path: network paths are not opened.");
    }
    if p.is_dir() {
        Ok(Shown::Folder(p.to_path_buf()))
    } else if p.is_file() {
        Ok(Shown::File(p.to_path_buf()))
    } else {
        Err("Parameter path: there is nothing at that path.")
    }
}

/// What the window buttons do.
#[derive(Debug, PartialEq)]
pub enum WindowAction {
    Minimize,
    ToggleMaximize,
    Close,
}

pub fn window_action(name: &str) -> Option<WindowAction> {
    match name {
        "minimize" => Some(WindowAction::Minimize),
        "toggle_maximize" => Some(WindowAction::ToggleMaximize),
        "close" => Some(WindowAction::Close),
        _ => None,
    }
}

/// Zips every regular file under `logs` (and nothing else) into `dest`; the number of files. A link is skipped, so
/// the bundle cannot reach outside the folder.
pub fn zip_logs(logs: &Path, dest: &Path) -> io::Result<usize> {
    let mut files = Vec::new();
    collect(logs, &mut files)?;
    let mut zip = ZipWriter::new(File::create(dest)?);
    let options = SimpleFileOptions::default().compression_method(CompressionMethod::Deflated);
    for file in &files {
        let name = file.strip_prefix(logs).unwrap_or(file);
        let name: Vec<_> = name.iter().map(|c| c.to_string_lossy()).collect();
        zip.start_file(name.join("/"), options)?;
        zip.write_all(&std::fs::read(file)?)?;
    }
    zip.finish()?;
    Ok(files.len())
}

fn collect(folder: &Path, files: &mut Vec<PathBuf>) -> io::Result<()> {
    for entry in std::fs::read_dir(folder)? {
        let entry = entry?;
        let kind = entry.file_type()?; // does not follow a link
        if kind.is_dir() {
            collect(&entry.path(), files)?;
        } else if kind.is_file() {
            files.push(entry.path());
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Read;

    use super::*;

    #[test]
    fn a_folder_is_opened_and_a_file_only_shown() {
        let dir = tempfile::tempdir().unwrap();
        let file = dir.path().join("run.exe");
        std::fs::write(&file, b"x").unwrap();
        let text = |p: &Path| p.to_string_lossy().into_owned();
        assert_eq!(
            classify(&text(dir.path())),
            Ok(Shown::Folder(dir.path().to_path_buf()))
        );
        assert_eq!(classify(&text(&file)), Ok(Shown::File(file)));
    }

    #[test]
    fn everything_else_is_refused() {
        let dir = tempfile::tempdir().unwrap();
        let gone = dir.path().join("gone");
        for bad in [
            "",
            "notepad.exe",
            r"..\..",
            "https://example.com",
            "steam://rungameid/1245620",
            "file:///C:/Windows",
            r"\\server\share",
            "//server/share",
            &gone.to_string_lossy(),
        ] {
            assert!(classify(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn only_the_three_window_buttons_exist() {
        assert_eq!(window_action("minimize"), Some(WindowAction::Minimize));
        assert_eq!(
            window_action("toggle_maximize"),
            Some(WindowAction::ToggleMaximize)
        );
        assert_eq!(window_action("close"), Some(WindowAction::Close));
        assert_eq!(window_action("fullscreen"), None);
    }

    #[test]
    fn the_bundle_holds_the_logs_and_nothing_beside_them() {
        let state = tempfile::tempdir().unwrap();
        let logs = state.path().join("logs");
        std::fs::create_dir_all(logs.join("jobs")).unwrap();
        std::fs::write(logs.join("engine.log"), b"started").unwrap();
        std::fs::write(logs.join("jobs").join("j1.log"), b"done").unwrap();
        std::fs::write(state.path().join("settings.json"), b"secret").unwrap();
        let out = state.path().join("support.zip");
        assert_eq!(zip_logs(&logs, &out).unwrap(), 2);
        let mut zip = zip::ZipArchive::new(File::open(&out).unwrap()).unwrap();
        let mut names: Vec<_> = zip.file_names().map(|n| n.unwrap().into_owned()).collect();
        names.sort();
        assert_eq!(names, ["engine.log", "jobs/j1.log"]);
        let mut text = String::new();
        zip.by_name("jobs/j1.log")
            .unwrap()
            .read_to_string(&mut text)
            .unwrap();
        assert_eq!(text, "done");
        assert!(zip_logs(&state.path().join("none"), &out).is_err());
    }
}
