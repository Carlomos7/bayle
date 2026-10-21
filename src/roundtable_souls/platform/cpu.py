"""CPU-bound work in a process of its own, so it cannot hold the window's GIL.

A task is a top-level function named "package.module:function" that takes keyword arguments (JSON values; pass file
paths, not bytes) and returns a JSON value. run_cpu(task, args) returns a Future. Without a backend (tests, the
command line) the task runs at once on the calling thread; the window installs one (ui/cpu_pool.py) that sends the
task to a worker process: this program started again with --worker, speaking one JSON object per line on standard
input and output (serve below). Calling .result() from a job's thread is the intended use; a task run from the
window's own thread would deadlock a waiting caller, so the backend runs those inline.

A worker never imports Qt: tasks live in modules below the window.
"""

from __future__ import annotations

import builtins
import importlib
import json
import os
import sys
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any, BinaryIO

PREFIX = "roundtable_souls."
Backend = Callable[[str, dict], "Future[Any]"]
_backend: Backend | None = None
_broadcast: Backend | None = None
_ui_thread: int | None = None  # the window's thread, once known: CPU work must never be asked for on it
_warned: set[tuple[str, int]] = set()


class UiThreadError(RuntimeError):
    """CPU work was asked for on the window's own thread (strict mode: tests and debugging)."""


def install(backend: Backend | None, broadcast: Backend | None = None, ui_thread: int | None = None) -> None:
    """The window's way of running tasks in worker processes (None: back to running them inline). broadcast sends
    a task to every live worker; ui_thread is the window's thread (threading.get_ident())."""
    global _backend, _broadcast, _ui_thread
    _backend, _broadcast, _ui_thread = backend, broadcast, ui_thread


def strict() -> bool:
    """Tests and debugging (ROUNDTABLE_SOULS_STRICT_CPU=1): CPU work on the window's thread raises."""
    return bool(os.environ.get("ROUNDTABLE_SOULS_STRICT_CPU") or os.environ.get("PYTEST_CURRENT_TEST"))


def _on_ui_thread(task: str) -> None:
    """Called on the window's thread: raise in strict mode; otherwise warn once per calling line, with the stack,
    and let the caller run the task inline (a worker could not be waited for here without freezing the window)."""
    if strict():
        raise UiThreadError(f"{task} was asked for on the UI thread; run it from a job or background thread")
    frames = [f for f in traceback.extract_stack()[:-2] if f.filename != __file__]
    site = (frames[-1].filename, frames[-1].lineno or 0) if frames else ("?", 0)
    if site not in _warned:
        _warned.add(site)
        from roundtable_souls.platform import logging as run_logging

        run_logging.get_logger("cpu").warning(
            "%s ran on the UI thread (it freezes the window); called from:\n%s",
            task,
            "".join(traceback.format_list(frames[-8:])),
        )


def call(task: str, args: dict) -> Any:
    """Run a task here, now (what a worker does for each request, and what run_cpu does without a backend)."""
    module, _, name = task.partition(":")
    if not module.startswith(PREFIX) or not name or name.startswith("_"):
        raise ValueError(f"not a task: {task!r}")
    return getattr(importlib.import_module(module), name)(**args)


class TaskError(RuntimeError):
    """A task failed in a worker with an exception that is not a built-in one; the message names it."""


_KEPT = (OSError, ValueError, KeyError, IndexError, EOFError, MemoryError)


def remote_error(reply: dict) -> Exception:
    """The exception for a failed reply: a built-in OSError or ValueError family one comes back as itself (callers
    catch those), anything else as a TaskError."""
    kind, text = str(reply.get("kind")), str(reply.get("error"))
    t = getattr(builtins, kind, None)
    if isinstance(t, type) and issubclass(t, _KEPT):
        return t(text)
    return TaskError(f"{kind}: {text}")


def run_inline(task: str, args: dict) -> Future:
    fut: Future = Future()
    try:
        fut.set_result(json.loads(json.dumps(call(task, args))))  # the same shape a worker sends back
    except Exception as e:
        fut.set_exception(e)
    return fut


def run_cpu(task: str, args: dict) -> Future:
    if _ui_thread is not None and threading.get_ident() == _ui_thread:
        _on_ui_thread(task)
        return run_inline(task, args)
    return (_backend or run_inline)(task, args)


def invalidate(kind: str = "all") -> None:
    """A cache in the live workers is out of date (kind: saves/caches.py's names): they clear it before any task
    sent after this call. Callers clear their own process's cache themselves."""
    if _broadcast is not None:
        _broadcast("roundtable_souls.saves.caches:forget", {"kind": kind})


def worker_command() -> list[str]:
    """The program and arguments that start a worker: the frozen exe itself, or this interpreter on the package."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    return [sys.executable, "-m", "roundtable_souls", "--worker"]


def serve(stdin: BinaryIO, stdout: BinaryIO) -> int:
    """Worker loop: for each line {"id", "task", "args"} write {"id", "ok", "result" | "error"}; ends at end of input."""
    for line in stdin:
        if not line.strip():
            continue
        req: dict = {}
        try:
            req = json.loads(line)
            reply = {"id": req["id"], "ok": True, "result": call(req["task"], req.get("args") or {})}
            text = json.dumps(reply)
        except Exception as e:
            text = json.dumps({"id": req.get("id"), "ok": False, "kind": type(e).__name__, "error": str(e)})
        stdout.write(text.encode("utf-8") + b"\n")
        stdout.flush()
    return 0


def worker_main() -> int:
    """--worker: standard output carries only replies, so anything a task prints goes to standard error."""
    out = os.fdopen(os.dup(1), "wb")  # file descriptors, not sys.stdout: a windowed build may have none of those
    os.dup2(2, 1)
    return serve(os.fdopen(0, "rb"), out)


# ----------------------------------------------------------------------------- tasks of its own
def probe(value: int = 0) -> dict:
    """A tiny task for the self-test and the tests: echoes, and says whether Qt was loaded (it must not be)."""
    qt = any(m.split(".")[0] in ("PySide6", "shiboken6") for m in sys.modules)
    return {"value": value + 1, "pid": os.getpid(), "qt": qt}
