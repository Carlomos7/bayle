//! The engine child process: spawn, handshake, readiness. Rust owns the process (decision 0012), no shell plugin.

use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// First launch may let `uv` build the environment, so the line can take a while.
pub const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(90);
pub const READY_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Deserialize)]
struct Handshake {
    port: u16,
    version: String,
    contract: String,
}

/// What the webview gets from `get_backend`.
#[derive(Clone, Serialize)]
pub struct Backend {
    pub base_url: String,
    pub token: String,
    pub app_version: String,
    pub contract_version: String,
}

pub fn new_token() -> Result<String, String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|e| format!("no OS randomness: {e}"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

fn parse_handshake(line: &str, token: &str) -> Result<Backend, String> {
    let h: Handshake =
        serde_json::from_str(line.trim()).map_err(|e| format!("bad handshake {line:?}: {e}"))?;
    Ok(Backend {
        base_url: format!("http://127.0.0.1:{}", h.port),
        token: token.to_owned(),
        app_version: h.version,
        contract_version: h.contract,
    })
}

/// Packaged: the onedir engine next to the exe. Dev: `uv run bayle --backend` from the repository root.
/// shortcut: the packaged engine path is a guess until the packaging work package fixes it.
fn engine_command(exe_dir: &Path) -> Result<Command, String> {
    let name = if cfg!(windows) { "bayle.exe" } else { "bayle" };
    let packaged: PathBuf = exe_dir.join("engine").join(name);
    if packaged.is_file() {
        let mut cmd = Command::new(packaged);
        cmd.arg("--backend");
        return Ok(cmd);
    }
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../..");
    if !repo.join("pyproject.toml").is_file() {
        return Err(format!(
            "no engine found at {}",
            exe_dir.join("engine").display()
        ));
    }
    let mut cmd = Command::new("uv");
    cmd.args(["run", "bayle", "--backend"]).current_dir(repo);
    Ok(cmd)
}

/// Start the engine and wait for its handshake line. The returned `Child` owns the open stdin pipe: dropping it
/// (or the shell dying) is the engine's end-of-file signal, so keep it alive for the whole session.
pub fn start(exe_dir: &Path, token: &str) -> Result<(Child, Backend), String> {
    let mut cmd = engine_command(exe_dir)?;
    cmd.env("BAYLE_API_TOKEN", token)
        .stdin(Stdio::piped()) // the parent end is not inheritable, so engine grandchildren never hold it
        .stdout(Stdio::piped());
    if cfg!(debug_assertions) {
        cmd.env("BAYLE_API_DEV", "1"); // lets the Vite dev origin through the engine's CORS list
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(crate::job::CREATE_SUSPENDED | crate::job::CREATE_NO_WINDOW);
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("cannot start the engine: {e}"))?;
    #[cfg(windows)]
    if let Err(e) = crate::job::confine_and_resume(&child) {
        let _ = child.kill();
        return Err(e);
    }
    let out = child.stdout.take().ok_or("engine has no stdout")?;
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let _ = tx.send(BufReader::new(out).read_line(&mut line).map(|_| line));
    });
    let backend = match rx.recv_timeout(HANDSHAKE_TIMEOUT) {
        Ok(Ok(line)) if !line.trim().is_empty() => parse_handshake(&line, token),
        Ok(_) => Err("the engine exited before it announced a port".into()),
        Err(_) => Err("the engine did not announce a port in time".into()),
    };
    match backend {
        Ok(b) => Ok((child, b)),
        Err(e) => {
            let _ = child.kill();
            Err(e)
        }
    }
}

fn health_ok(port: u16, token: &str) -> bool {
    let addr = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
    let Ok(mut s) = TcpStream::connect_timeout(&addr, Duration::from_secs(1)) else {
        return false;
    };
    let _ = s.set_read_timeout(Some(Duration::from_secs(2)));
    let req = format!(
        "GET /v1/health HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {token}\r\nConnection: close\r\n\r\n"
    );
    let mut body = String::new();
    s.write_all(req.as_bytes()).is_ok()
        && s.read_to_string(&mut body).is_ok()
        && response_is_ready(&body)
}

fn response_is_ready(response: &str) -> bool {
    response.starts_with("HTTP/1.1 200") && response.contains("\"ready\":true")
}

/// Poll `/v1/health` until it says ready.
pub fn wait_ready(backend: &Backend) -> Result<(), String> {
    let port: u16 = backend
        .base_url
        .rsplit(':')
        .next()
        .and_then(|p| p.parse().ok())
        .ok_or("bad base url")?;
    let deadline = Instant::now() + READY_TIMEOUT;
    while Instant::now() < deadline {
        if health_ok(port, &backend.token) {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Err("the engine never reported ready".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn handshake_line_becomes_backend() {
        let b = parse_handshake(
            "{\"port\":4242,\"version\":\"4.6.0\",\"contract\":\"1\"}\n",
            "tok",
        )
        .unwrap();
        assert_eq!(b.base_url, "http://127.0.0.1:4242");
        assert_eq!(
            (
                b.token.as_str(),
                b.app_version.as_str(),
                b.contract_version.as_str()
            ),
            ("tok", "4.6.0", "1")
        );
    }

    #[test]
    fn bad_handshake_is_an_error() {
        assert!(parse_handshake("Traceback...", "t").is_err());
    }

    #[test]
    fn tokens_are_long_and_unique() {
        let (a, b) = (new_token().unwrap(), new_token().unwrap());
        assert_eq!(a.len(), 64);
        assert_ne!(a, b);
    }

    #[test]
    fn only_a_200_with_ready_counts() {
        assert!(response_is_ready("HTTP/1.1 200 OK\r\n\r\n{\"ready\":true}"));
        assert!(!response_is_ready("HTTP/1.1 401 Unauthorized\r\n\r\n{}"));
        assert!(!response_is_ready(
            "HTTP/1.1 200 OK\r\n\r\n{\"ready\":false}"
        ));
    }
}
