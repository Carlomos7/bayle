# 0012 The backend process dies with the app: onedir, stdin watchdog, Job Object, startup sweep

**Status:** Proposed. To be confirmed by a spike (100 start/stop cycles, parent crash) before it is Accepted.

## Context

When the backend runs as a child of the desktop shell, a closed or crashed shell must not leave a Python process behind.
A stale backend would hold the data folder, and two writers are a corruption risk. The backend also starts CPU worker
subprocesses. Tauri's sidecar documentation does not promise that a sidecar is stopped on exit, and a PyInstaller
one-file build starts a bootloader parent and a Python child, so killing the parent orphans the child.

## Decision

Four layers, none of which is enough alone:

1. **Frozen as a onedir folder**, not one file. No bootloader grandchild, no temp folder that survives a kill, and
   Velopack already needs a folder (see [0004](0004-velopack.md)). Run as a single process: never with more than one
   server worker, never with reload.
2. **stdin-EOF watchdog (graceful).** The shell keeps the backend's stdin pipe open. A daemon thread in the backend reads
   it; end of file means the parent is gone, so the server is asked to exit and the CPU workers are terminated. Works on
   Windows and Linux without extra APIs.
3. **Windows Job Object with kill-on-close (hard).** The shell puts the backend in a job; when the last handle closes,
   Windows kills everything in it, workers included, even if the shell crashed. On Linux the shell uses the parent-death
   signal or a process-group kill.
4. **Startup sweep.** A lockfile in the data folder records the backend's process id and port. At start, a leftover
   backend from a dead shell is stopped, and a second live backend on the same data folder is refused.

The backend entry point (`--backend`) is dispatched before any Qt or window import, like `--worker` today. Shutdown
order: stop taking jobs, cancel the running job with a deadline, flush the jobs index, close event streams, stop CPU
workers, close the app context.

## Why

Each layer covers a case the others miss: the watchdog handles a clean or crashed parent but needs the backend to be
healthy; the Job Object handles a hung backend but only on Windows; the sweep handles whatever slipped past both. The
lock lives in the data folder because the same data must be safe from both the old and the new app.

## Consequences

- The backend needs a small amount of platform code on both systems, tested with real subprocesses.
- Tests must reset the process-global state that the app context wires (data folder, stores, log sink); the backend owns
  exactly one session per process.
- The Velopack startup hooks and the ready report belong to the shell, not the backend, so the backend must not run them.

## Alternatives considered

- **Poll the parent's process id:** works but races on id reuse; the pipe is simpler and cannot be reused.
- **Trust the shell's own sidecar kill:** reported to fail for PyInstaller one-file builds.
- **One-file freeze:** smaller to ship, but orphans and temp-folder leaks.
- **No sweep:** a crash would leave a backend holding the data folder until reboot.

## Evidence

https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects (kill-on-close; children inherit the job),
https://pyinstaller.org/en/stable/operating-mode.html (onedir versus onefile), https://v2.tauri.app/develop/sidecar/ ,
and the Tauri discussion about PyInstaller sidecars surviving exit (tauri-apps/tauri discussion 3273). Not yet
measured: survival counts over repeated cycles, and the Linux details.

## Reopen if

The spike finds a surviving process on either system, or the shell is replaced by something that spawns the backend
differently.
