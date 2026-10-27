//! Starting one engine process: a fresh token, the handshake line, the contract check, and a process tree the gateway
//! can stop as a whole (a Windows Job Object that also kills it when the gateway dies; a process group on Unix).

use std::{
    collections::VecDeque,
    path::PathBuf,
    process::Stdio,
    sync::{Arc, Mutex},
    time::Duration,
};

use serde::Deserialize;
use serde_json::json;
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::{Child, ChildStdin, Command},
};

use crate::{contract::CONTRACT_MAJOR, error::GatewayError};

/// How to start the engine: the program and arguments (`uv run ... bayle-engine --backend` in development, the frozen
/// engine in a build) and the environment it gets besides the token.
#[derive(Debug, Clone)]
pub struct EngineCommand {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub cwd: Option<PathBuf>,
    pub env: Vec<(String, String)>,
    pub handshake_timeout: Duration,
}

/// The engine's first stdout line (apps/engine/src/bayle/api/server.py).
#[derive(Debug, Clone, Deserialize)]
pub struct Handshake {
    pub port: u16,
    pub version: String,
    pub contract: String,
}

pub(crate) struct Running {
    pub handshake: Handshake,
    pub token: String,
    pub child: Child,
    pub tree: Arc<Tree>,
    stdin: Option<ChildStdin>, // held open: its end of file is the engine's signal to stop (ADR 0012)
}

impl Running {
    /// Asks the engine to stop the way a closing parent does (ADR 0012's stdin watchdog).
    pub fn close_stdin(&mut self) {
        self.stdin = None;
    }
}

/// Exit codes the engine uses before its handshake for problems a restart cannot fix (server.py).
pub(crate) fn fatal_exit(code: Option<i32>) -> bool {
    matches!(code, Some(2) | Some(3))
}

pub(crate) async fn start(cmd: &EngineCommand) -> Result<Running, GatewayError> {
    let mut raw = [0u8; 32];
    getrandom::fill(&mut raw)
        .map_err(|e| GatewayError::engine_unavailable(format!("no random token: {e}")))?;
    let token: String = raw.iter().map(|b| format!("{b:02x}")).collect();

    let mut command = Command::new(&cmd.program);
    command
        .args(&cmd.args)
        .envs(cmd.env.iter().map(|(k, v)| (k, v)))
        .env("BAYLE_API_TOKEN", &token)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    if let Some(cwd) = &cmd.cwd {
        command.current_dir(cwd);
    }
    #[cfg(windows)]
    command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    #[cfg(unix)]
    {
        command.process_group(0);
        #[cfg(target_os = "linux")]
        unsafe {
            command.pre_exec(|| {
                libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL);
                Ok(())
            });
        }
    }
    let mut child = command.spawn().map_err(|e| {
        GatewayError::engine_unavailable(format!("could not start the engine: {e}"))
    })?;
    let tree = Arc::new(Tree::contain(&child));

    let tail = Arc::new(Mutex::new(VecDeque::new()));
    let stderr = child.stderr.take().expect("stderr is piped");
    let stderr_tail = tail.clone();
    tokio::spawn(async move {
        let mut lines = BufReader::new(stderr).lines();
        while let Ok(Some(line)) = lines.next_line().await {
            let mut t = stderr_tail.lock().unwrap();
            t.push_back(line);
            if t.len() > 20 {
                t.pop_front();
            }
        }
    });
    let stdin = child.stdin.take().expect("stdin is piped");
    let mut stdout = BufReader::new(child.stdout.take().expect("stdout is piped")).lines();

    let first = tokio::time::timeout(cmd.handshake_timeout, stdout.next_line()).await;
    let line = match first {
        Ok(Ok(Some(line))) => line,
        Ok(_) => {
            let code = child.wait().await.ok().and_then(|s| s.code());
            tokio::time::sleep(Duration::from_millis(100)).await; // let the stderr reader catch the last lines
            let said = tail
                .lock()
                .unwrap()
                .iter()
                .cloned()
                .collect::<Vec<_>>()
                .join("\n");
            return Err(GatewayError::gateway(
                503,
                if fatal_exit(code) {
                    "engine_refused"
                } else {
                    "engine_unavailable"
                },
                if said.is_empty() {
                    format!("The engine stopped before it was ready (exit {code:?}).")
                } else {
                    said
                },
                json!({ "exit_code": code }),
            ));
        }
        Err(_) => {
            tree.kill();
            return Err(GatewayError::gateway(
                504,
                "timeout",
                "The engine did not start in time.",
                json!(null),
            ));
        }
    };
    tokio::spawn(async move { while let Ok(Some(_)) = stdout.next_line().await {} }); // keep the pipe drained
    let handshake: Handshake = serde_json::from_str(&line).map_err(|_| {
        tree.kill();
        GatewayError::gateway(
            502,
            "contract_mismatch",
            "The engine's first line is not a handshake.",
            json!({ "line": line }),
        )
    })?;
    if handshake.contract.split('.').next() != Some(CONTRACT_MAJOR) {
        tree.kill();
        return Err(GatewayError::gateway(
            502,
            "contract_mismatch",
            format!(
                "The engine speaks contract {}, this app {}.",
                handshake.contract, CONTRACT_MAJOR
            ),
            json!({ "engine": handshake.contract, "app": CONTRACT_MAJOR }),
        ));
    }
    Ok(Running {
        handshake,
        token,
        child,
        tree,
        stdin: Some(stdin),
    })
}

/// The engine's whole process tree (uv, Python, its CPU workers).
pub(crate) struct Tree {
    #[cfg(windows)]
    job: windows_sys::Win32::Foundation::HANDLE,
    #[cfg(unix)]
    pgid: i32,
}

unsafe impl Send for Tree {}
unsafe impl Sync for Tree {}

#[cfg(windows)]
impl Tree {
    /// A Job Object with kill-on-close: stopping it, or the gateway's process ending, ends every process in it.
    /// shortcut: the child runs for a moment before it joins the job, so a grandchild started in that moment escapes;
    /// start the engine suspended when it is the frozen engine rather than `uv run`.
    fn contain(child: &Child) -> Self {
        use windows_sys::Win32::System::JobObjects::*;
        unsafe {
            let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if !job.is_null() {
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                SetInformationJobObject(
                    job,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if let Some(handle) = child.raw_handle() {
                    AssignProcessToJobObject(job, handle as _);
                }
            }
            Tree { job }
        }
    }

    pub fn kill(&self) {
        if !self.job.is_null() {
            unsafe { windows_sys::Win32::System::JobObjects::TerminateJobObject(self.job, 1) };
        }
    }
}

#[cfg(windows)]
impl Drop for Tree {
    fn drop(&mut self) {
        if !self.job.is_null() {
            unsafe { windows_sys::Win32::Foundation::CloseHandle(self.job) };
        }
    }
}

#[cfg(unix)]
impl Tree {
    fn contain(child: &Child) -> Self {
        Tree {
            pgid: child.id().map(|p| p as i32).unwrap_or(0),
        }
    }

    pub fn kill(&self) {
        if self.pgid > 0 {
            unsafe { libc::kill(-self.pgid, libc::SIGKILL) };
        }
    }
}
