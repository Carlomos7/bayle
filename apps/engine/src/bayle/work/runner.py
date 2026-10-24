"""Background work, without Qt. A Runner starts each piece of work on a thread of its own and reports what happens as
events: progress while it runs, then its result. The window's adapter (ui/jobs.py) delivers the events on the UI
thread, so work never touches the window itself.

A logged job (run_job) is one the Activity page lists: its lines go to a log file of its own and the jobs index
records how it ended; its result is an Outcome, what the window's status line shows.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from bayle.errors import Cancelled, ErrorInfo, OperationError
from bayle.game.locate import Locations
from bayle.platform import cpu
from bayle.platform import logging as run_logging

PROGRESS = "progress"
RESULT = "result"


@dataclass(frozen=True)
class Event:
    task: int  # what Runner.start returned
    kind: str  # PROGRESS or RESULT
    value: Any = None


@dataclass(frozen=True)
class Outcome:
    """How a logged job ended: ok, and the status the window shows ("Finished", "Stopped (see details)", ...)."""

    ok: bool
    status: str


@dataclass(frozen=True)
class JobResult:
    """How a logged job ended: state ("done", "failed", "cancelled"), what the job returned, why it did not complete
    (error), and the undo record it left (done only)."""

    state: str
    result: Any = None
    error: ErrorInfo | None = None
    undo: dict | None = None
    unexpected: bool = False  # an exception nobody planned for (the status line says Error, not Stopped)

    @property
    def outcome(self) -> Outcome:
        if self.state == "done":
            return Outcome(True, "Finished")
        return Outcome(False, "Error (see details)" if self.unexpected else "Stopped (see details)")


class Progress:
    """Handed to the work: progress(value) reports a step (a line of text, a value the window shows)."""

    def __init__(self, post: Callable[[Event], None], task: int):
        self._post, self._task = post, task

    def __call__(self, value: Any) -> None:
        self._post(Event(self._task, PROGRESS, value))


class Runner:
    """post receives every event, on the worker's thread (the adapter passes them on to the UI thread)."""

    def __init__(
        self, post: Callable[[Event], None], spawn: Callable[[Callable[[], None], str | None], None] | None = None
    ):
        """spawn(run, name) starts run on a worker; without one each piece of work gets a daemon thread (the window
        passes its QThreadPool)."""
        self._post = post
        self._spawn = spawn or self._thread
        self._ids = itertools.count(1)

    @staticmethod
    def _thread(run: Callable[[], None], name: str | None) -> None:
        threading.Thread(target=run, daemon=True, name=name).start()

    def start(self, work: Callable[[Progress], Any], name: str | None = None) -> int:
        """Run work(progress) on a daemon thread and post its return value as the result. An exception is not caught
        here: it reaches threading.excepthook (the window reports it) and no result is posted. name: the thread's
        (crash reports show it); without one the thread is named after the work, as threading names it."""
        task = next(self._ids)
        progress = Progress(self._post, task)

        def run():
            self._post(Event(task, RESULT, work(progress)))

        run.__name__ = getattr(work, "__name__", run.__name__)
        self._spawn(run, name)
        return task

    def start_job(self, job: Callable[[Any, Locations], None], launch, loc: Locations, title: str = "Job") -> int:
        """A logged job (run_job) on a thread of its own; its result is the job's Outcome."""

        def logged(_progress: Progress) -> Outcome:
            return run_job(job, launch, loc, title)

        logged.__name__ = "run_job"  # the thread's name, as when run_job itself was the thread's target
        return self.start(logged)


@contextmanager
def run_logged(title: str, game: str) -> Iterator[None]:
    """Name the running job (start_log) and turn any failure inside into an OperationError, which run_job logs and
    reports; replaces the start_log + try/except + SystemExit(1) each job wrote. SystemExit and OperationError pass."""
    run_logging.start_log(title, game)
    try:
        yield
    except SystemExit, OperationError:
        raise
    except Exception as e:  # reported to the player
        raise OperationError("failed", str(e)) from e


def run_job_result(job: Callable[[Any, Locations], Any], launch, loc: Locations, title: str = "Job") -> JobResult:
    """Run job(setup, loc) on this (worker) thread as a logged job of its own: its lines go to its log file and the
    window, and the jobs index records how it ended. The job stops early with Cancelled / OperationError or, for old
    jobs, SystemExit (130: the user stopped it; anything else but 0: failed). Its return value is the result."""
    profile = str(getattr(launch, "profile", "") or "")
    record = run_logging.begin_job(title.rstrip(". "), game=loc.game.key, profile=profile)
    log = run_logging.get_logger("job")
    value, error, state, unexpected = None, None, "done", False
    try:
        try:
            value = job(launch, loc)
        finally:
            cpu.invalidate("item_names")  # installs, removals and rebuilds change which mods give items names
    except SystemExit as e:
        if e.code not in (0, None):
            state = "cancelled" if e.code == 130 else "failed"
            error = ErrorInfo(state, "Stopped.")
    except OperationError as e:
        log.error("error: %s", e.message)
        state, error = ("cancelled" if isinstance(e, Cancelled) else "failed"), e.info
    except Exception as e:
        log.exception("the job failed with an unexpected error")
        state, error, unexpected = "failed", ErrorInfo("unexpected", str(e)), True
    run_logging.end_job(record, {"done": None, "cancelled": "stopped"}.get(state, "failed"))
    return JobResult(state, value, error, getattr(record, "undo", None) if state == "done" else None, unexpected)


def run_job_value(job: Callable[[Any, Locations], Any], loc: Locations, title: str = "Job") -> Any:
    """run_job_result for work that already runs as a session job: the job's value, or the OperationError / Cancelled
    it ended with."""
    done = run_job_result(job, None, loc, title)
    if done.state == "done":
        return done.result
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError.from_info(done.error)


def run_job(job: Callable[[Any, Locations], Any], launch, loc: Locations, title: str = "Job") -> Outcome:
    """run_job_result for callers that want the window's status line (an Outcome)."""
    return run_job_result(job, launch, loc, title).outcome
