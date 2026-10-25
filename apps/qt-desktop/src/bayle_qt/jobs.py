"""The window's side of work/runner.py: events the worker threads post arrive here, on the UI thread, and go to the
callbacks given with each piece of work."""

from __future__ import annotations

import itertools
import sys
import threading
from collections.abc import Callable
from typing import Any

from bayle.adapters.system import logging as run_logging
from bayle.work import runner as jobs
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

# The one pool for background work in the window (reads, jobs, the game watch). A bigger pool than the core count: the
# watch and a running job each hold a thread for a long time.
POOL = QThreadPool()
POOL.setMaxThreadCount(16)


class _Task(QRunnable):
    def __init__(self, call: Callable[[], None]):
        super().__init__()
        self._call = call

    def run(self) -> None:
        try:
            self._call()
        except Exception:  # as a thread's failure: the window's excepthook reports it, no result is posted
            kind, value, tb = sys.exc_info()
            threading.excepthook(threading.ExceptHookArgs((kind, value, tb, threading.current_thread())))


_running: dict[int, str] = {}  # pool tasks in flight, by id, for the log at shutdown
_ids = itertools.count(1)


def drain(timeout_ms: int = 3000) -> bool:
    """Queued work is dropped and running work is given timeout_ms; False (and a log line naming it) when some is left."""
    POOL.clear()
    if POOL.waitForDone(timeout_ms):
        return True
    # a job still runs: it is journaled, the next start recovers it, and the program exits anyway
    run_logging.log_shown(f"closing with work still running: {', '.join(sorted(_running.values())) or '?'}")
    return False


def run_async(call: Callable[[], None], name: str | None = None) -> None:
    """Run call on a pool thread (name is only for the log of whoever asks)."""
    key = next(_ids)
    label = name or getattr(call, "__name__", "work")

    def tracked() -> None:
        _running[key] = label
        try:
            call()
        finally:
            _running.pop(key, None)

    POOL.start(_Task(tracked))


class Jobs(QObject):
    _arrived = Signal(object)  # a jobs.Event, emitted on a worker thread; Qt queues it to this object's thread

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._calls: dict[int, tuple[Callable[[Any], None] | None, Callable[[Any], None] | None]] = {}
        self._lock = threading.RLock()  # start() may be called from a worker thread (the shell's job observer)
        self._arrived.connect(self._deliver)
        self.runner = jobs.Runner(self._arrived.emit, lambda run, name: run_async(run, name))

    def start(
        self,
        work: Callable[[jobs.Progress], Any],
        on_result: Callable[[Any], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        name: str | None = None,
    ) -> int:
        """Run work(progress) on a worker thread; on_progress gets each step and on_result the return value, both on
        the UI thread."""
        with self._lock:  # an event is delivered only once the callbacks are in place
            task = self.runner.start(work, name=name)
            self._calls[task] = (on_progress, on_result)
        return task

    def start_job(self, job, launch, loc, title: str, on_done: Callable[[jobs.Outcome], None]) -> int:
        """A logged job (jobs.run_job); on_done gets its Outcome on the UI thread."""
        with self._lock:
            task = self.runner.start_job(job, launch, loc, title)
            self._calls[task] = (None, on_done)
        return task

    def _deliver(self, event: jobs.Event) -> None:
        with self._lock:
            on_progress, on_result = self._calls.get(event.task, (None, None))
            if event.kind != jobs.PROGRESS:
                self._calls.pop(event.task, None)
        if event.kind == jobs.PROGRESS:
            if on_progress is not None:
                on_progress(event.value)
            return
        if on_result is not None:
            on_result(event.value)

    def shutdown(self, timeout_ms: int = 3000) -> bool:
        return drain(timeout_ms)
