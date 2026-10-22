"""Jobs for every client: start work, get an id, follow it as events on the EventBus, cancel it, read its outcome.
A JobManager owns a services.jobs.Runner (the thread seam); its post hook turns what the work reports into bus events.
No Qt, no event loop; start/cancel/get may be called from any thread.

Event order for one job: started, then progress/log/prompt (any number), then exactly one of finished/failed/cancelled.
At most one writing job runs at a time and none while the game runs (Busy); reads pass writes=False.
"""

from __future__ import annotations

import contextvars
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bayle.game.locate import Locations
from bayle.platform import logging as run_logging
from bayle.services import jobs as service_jobs
from bayle.services.errors import Busy, Cancelled, ErrorInfo, OperationError
from bayle.services.jobs import Event as RunnerEvent
from bayle.services.jobs import JobResult
from bayle.session.events import EventBus

PROGRESS_INTERVAL = 0.1  # seconds: at most 10 progress events a second per job

_current: contextvars.ContextVar[JobContext | None] = contextvars.ContextVar("bayle_job_context", default=None)


def current_context() -> JobContext | None:
    """The context of the job running on this thread, for code that cannot be handed one (old jobs)."""
    return _current.get()


class JobContext:
    """Handed to the work: report progress and prompts, look at the cancel token."""

    def __init__(self, job_id: str, report: Callable[[str, dict], None], clock: Callable[[], float], interval: float):
        self.job_id = job_id
        self._report, self._clock, self._interval = report, clock, interval
        self._cancel = threading.Event()
        self._last: float | None = None

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def progress(self, done: float | None = None, total: float | None = None, label: str = "") -> None:
        """Coalesced to one event per interval (the final step, done >= total, always passes).
        shortcut: a step skipped by coalescing is not sent later; the next one (or the end) carries the state."""
        now = self._clock()
        final = total is not None and done is not None and done >= total
        if self._last is not None and now - self._last < self._interval and not final:
            return
        self._last = now
        self._report("progress", {"done": done, "total": total, "label": label})

    def prompt(self, data: dict[str, Any]) -> None:
        """Ask the client something mid-job (never dropped).
        shortcut: answers are not routed yet (plan/execute covers most flows); add the answer route with the launch flow."""
        self._report("prompt", dict(data))


@dataclass(frozen=True)
class JobSnapshot:
    id: str
    title: str
    state: str  # running | done | failed | cancelled
    progress: dict | None = None  # the last progress event sent
    result: Any = None
    error: ErrorInfo | None = None
    undo: dict | None = None


class _Record:
    def __init__(self, job_id: str, title: str, ctx: JobContext):
        self.id, self.title, self.ctx = job_id, title, ctx
        self.state, self.progress, self.result, self.error, self.undo = "running", None, None, None, None

    def snapshot(self) -> JobSnapshot:
        return JobSnapshot(self.id, self.title, self.state, self.progress, self.result, self.error, self.undo)


def _error_data(error: ErrorInfo | None) -> dict:
    return {} if error is None else {"code": error.code, "message": error.message, "details": error.details}


def _execute(work: Callable[[JobContext], Any], ctx: JobContext) -> JobResult:
    """Run work(ctx) and say how it ended, as run_job_result does (SystemExit 130 = stopped)."""
    try:
        value = work(ctx)
    except SystemExit as e:
        if e.code in (0, None):
            return JobResult("done")
        state = "cancelled" if e.code == 130 else "failed"
        return JobResult(state, error=ErrorInfo(state, "Stopped."))
    except OperationError as e:
        return JobResult("cancelled" if isinstance(e, Cancelled) else "failed", error=e.info)
    except Exception as e:  # reported to the client, with the traceback in the log
        run_logging.get_logger("job").exception("the job failed with an unexpected error")
        return JobResult("failed", error=ErrorInfo("unexpected", str(e)), unexpected=True)
    return value if isinstance(value, JobResult) else JobResult("done", value)


class JobManager:
    def __init__(
        self,
        bus: EventBus | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        spawn: Callable[[Callable[[], None], str | None], None] | None = None,
        game_running: Callable[[], bool] | None = None,
        progress_interval: float = PROGRESS_INTERVAL,
        keep: int = 50,
    ):
        """spawn: how work gets a thread (Runner's; tests pass a synchronous one). game_running: the writes gate.
        keep: how many finished jobs get() still knows."""
        self.bus = bus or EventBus()
        self._clock, self._game_running, self._interval, self._keep = clock, game_running, progress_interval, keep
        self._runner = service_jobs.Runner(self._on_event, spawn)
        self._lock = threading.Lock()
        self._records: dict[str, _Record] = {}
        self._progress: dict[str, service_jobs.Progress] = {}  # job id -> the Runner's channel while it runs
        self._writer: str | None = None
        self._count = 0

    # ------------------------------------------------------------------ start
    def start(self, work: Callable[[JobContext], Any], *, title: str = "Job", writes: bool = True) -> str:
        """Run work(ctx) on a worker; return the job id. Raises Busy (writes only) while another writing job runs or
        the game is running. Whatever work returns is the result (a JobResult is used as it is); an exception ends the
        job as failed/cancelled and never escapes."""
        with self._lock:
            if writes:
                if self._game_running is not None and self._game_running():
                    raise Busy("The game is running.", {"reason": "game_running"})
                if self._writer is not None:
                    raise Busy("Another operation is running.", {"reason": "job", "job_id": self._writer})
            self._count += 1
            job_id = f"j{self._count}"
            ctx = JobContext(job_id, lambda t, d: self._progress[job_id]((job_id, t, d)), self._clock, self._interval)
            self._records[job_id] = _Record(job_id, title, ctx)
            if writes:
                self._writer = job_id
            self._forget_old()
        self.bus.publish("started", {"title": title}, job_id)

        def run(progress: service_jobs.Progress) -> tuple[str, JobResult]:
            self._progress[job_id] = progress
            token = _current.set(ctx)
            try:
                with run_logging.job_log_scope(lambda text, level: ctx._report("log", {"text": text, "level": level})):
                    return job_id, _execute(work, ctx)
            finally:
                _current.reset(token)
                self._progress.pop(job_id, None)

        run.__name__ = "job"
        try:
            self._runner.start(run, name=f"bayle-{job_id}")
        except BaseException:
            self._finish(job_id, JobResult("failed", error=ErrorInfo("unexpected", "could not start")))
            raise
        return job_id

    def start_logged(
        self, job: Callable[[Any, Locations], Any], launch: Any, loc: Locations, title: str = "Job", writes: bool = True
    ) -> str:
        """An old-style logged job (services.jobs.run_job_result): its log file, jobs-index record and undo record
        stay as they were, and its lines also reach the bus as log events."""
        return self.start(lambda _ctx: service_jobs.run_job_result(job, launch, loc, title), title=title, writes=writes)

    # ------------------------------------------------------------------ control
    def cancel(self, job_id: str) -> bool:
        """Ask a running job to stop (cooperatively: it sees ctx.cancelled()). False if unknown or already over."""
        with self._lock:
            record = self._records.get(job_id)
            if record is None or record.state != "running":
                return False
        record.ctx._cancel.set()
        return True

    def get(self, job_id: str) -> JobSnapshot | None:
        with self._lock:
            record = self._records.get(job_id)
            return record.snapshot() if record else None

    # ------------------------------------------------------------------ inside
    def _on_event(self, event: RunnerEvent) -> None:
        """The Runner's post hook, on the worker's thread."""
        if event.kind == service_jobs.PROGRESS:
            job_id, type, data = event.value
            if type == "progress":
                with self._lock:
                    self._records[job_id].progress = data
            self.bus.publish(type, data, job_id)
        else:
            job_id, result = event.value
            self._finish(job_id, result)

    def _finish(self, job_id: str, result: JobResult) -> None:
        with self._lock:
            record = self._records[job_id]
            record.state, record.result, record.error, record.undo = (
                result.state,
                result.result,
                result.error,
                result.undo,
            )
            if self._writer == job_id:
                self._writer = None
        if result.state == "done":
            self.bus.publish("finished", {"result": result.result, "undo": result.undo}, job_id)
        else:
            data = {"error": _error_data(result.error), "unexpected": result.unexpected}
            self.bus.publish(result.state == "cancelled" and "cancelled" or "failed", data, job_id)

    def _forget_old(self) -> None:
        over = len(self._records) - self._keep
        for job_id in [i for i, r in self._records.items() if r.state != "running"][: max(over, 0)]:
            del self._records[job_id]
