"""Jobs for every client: start work, get an id, follow it as events on the EventBus, cancel it, read its outcome.
A JobManager owns a work.runner.Runner (the thread seam); its post hook turns what the work reports into bus events.
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

from bayle.errors import Busy, Cancelled, ErrorInfo, OperationError
from bayle.game.locate import Locations
from bayle.platform import logging as run_logging
from bayle.work import runner as service_jobs
from bayle.work.events import EventBus
from bayle.work.prompts import Choose, PromptBroker
from bayle.work.runner import Event as RunnerEvent
from bayle.work.runner import JobResult

PROGRESS_INTERVAL = 0.1  # seconds: at most 10 progress events a second per job

_current: contextvars.ContextVar[JobContext | None] = contextvars.ContextVar("bayle_job_context", default=None)


def current_context() -> JobContext | None:
    """The context of the job running on this thread, for code that cannot be handed one (old jobs)."""
    return _current.get()


def notice(text: str) -> None:
    """A warning the player should see at once: logged (run_logging.notice) and, from inside a job, a `notice` event
    on its manager's bus, the one the shell publishes. What services are handed as their notice callable."""
    run_logging.notice(text)
    ctx = _current.get()
    if ctx is not None:
        ctx._report("notice", {"text": text, "error": False, "details": True})


class JobContext:
    """Handed to the work: report progress and prompts, look at the cancel token."""

    def __init__(
        self,
        job_id: str,
        report: Callable[[str, dict], None],
        clock: Callable[[], float],
        interval: float,
        prompts: PromptBroker | None = None,
    ):
        self.job_id = job_id
        self._report, self._clock, self._interval, self._prompts = report, clock, interval, prompts
        self._cancel = threading.Event()
        self._last: float | None = None

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def raise_if_cancelled(self) -> None:
        if self._cancel.is_set():
            raise Cancelled()

    def progress(
        self, done: float | None = None, total: float | None = None, label: str = "", detail: dict | None = None
    ) -> None:
        """Coalesced to one event per interval (the final step, done >= total, always passes).
        shortcut: a step skipped by coalescing is not sent later; the next one (or the end) carries the state."""
        now = self._clock()
        final = total is not None and done is not None and done >= total
        if self._last is not None and now - self._last < self._interval and not final:
            return
        self._last = now
        self._report(
            "progress", {"done": done, "total": total, "label": label, **({"detail": detail} if detail else {})}
        )

    def prompt(self, data: dict[str, Any]) -> None:
        """Tell the client something mid-job that wants no answer (never dropped)."""
        self._report("prompt", dict(data))

    def ask(self, words: Choose, timeout: float | None = None, default: str = "cancel") -> str:
        """Ask the client which way to go and wait for the key it answers with (JobManager.prompts.answer, or
        POST /v1/prompts/{id}). `default` when the timeout passes or the job is cancelled meanwhile."""
        if self._prompts is None:
            return default
        return self._prompts.wait(words, timeout, default, self.job_id, self.cancelled)


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
        self.state, self.progress, self.result = "running", None, None
        self.error: ErrorInfo | None = None
        self.undo: dict | None = None

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
        external_busy: Callable[[], bool] | None = None,
        observer: Callable[[str, dict, str | None], None] | None = None,
        progress_interval: float = PROGRESS_INTERVAL,
        keep: int = 50,
        store: run_logging.JobStore | None = None,
    ):
        """spawn: how work gets a thread (Runner's; tests pass a synchronous one). game_running: the writes gate.
        keep: how many finished jobs get() still knows. observer(type, data, job_id): called on the emitting thread
        before the event reaches the bus, so state it updates is current when a client reads after the event.
        store: where the records of the jobs it runs go besides jobs.jsonl (the engine's activity log)."""
        self.store = store
        self.bus = bus or EventBus()
        self._clock, self._game_running, self._interval, self._keep = clock, game_running, progress_interval, keep
        self._external_busy = external_busy  # work that runs outside this manager (the window's own jobs)
        self._observer = observer
        self.prompts = PromptBroker(self._publish_prompt)
        self._runner = service_jobs.Runner(self._on_event, spawn)
        self._lock = threading.Lock()
        self._records: dict[str, _Record] = {}
        self._progress: dict[str, service_jobs.Progress] = {}  # job id -> the Runner's channel while it runs
        self._writer: str | None = None
        self._count = 0

    def attach(
        self,
        *,
        game_running: Callable[[], bool] | None,
        external_busy: Callable[[], bool] | None,
        observer: Callable[[str, dict, str | None], None] | None,
    ) -> None:
        """The client's gates and observer, for a manager the Engine made before its client (the shell) existed."""
        self._game_running, self._external_busy, self._observer = game_running, external_busy, observer

    # ------------------------------------------------------------------ start

    def start(
        self,
        work: Callable[[JobContext], Any],
        *,
        title: str = "Job",
        writes: bool = True,
        external: bool = False,
        while_game_runs: bool = False,
        quiet: bool = False,
    ) -> str:
        """Run work(ctx) on a worker; return the job id. Raises Busy (writes only) while another writing job runs or
        the game is running (while_game_runs: this job may, like clearing leftover processes). external: the caller
        is the outside work external_busy counts (the Launch flow), so that count does not refuse it. quiet: the client
        speaks for the job itself (its own words when it ends), so a window need not announce it. Whatever work
        returns is the result (a JobResult is used as it is); an exception ends the
        job as failed/cancelled and never escapes."""
        with self._lock:
            if writes:
                if not while_game_runs and self._game_running is not None and self._game_running():
                    raise Busy("The game is running.", {"reason": "game_running"})
                if self._writer is not None:
                    raise Busy("Another operation is running.", {"reason": "job", "job_id": self._writer})
                if not external and self._external_busy is not None and self._external_busy():
                    raise Busy("Another operation is running.", {"reason": "job"})
            self._count += 1
            job_id = f"j{self._count}"
            ctx = JobContext(
                job_id, lambda t, d: self._progress[job_id]((job_id, t, d)), self._clock, self._interval, self.prompts
            )
            self._records[job_id] = _Record(job_id, title, ctx)
            if writes:
                self._writer = job_id
            self._forget_old()
        self._emit("started", {"title": title, **({"quiet": True} if quiet else {})}, job_id)

        def run(progress: service_jobs.Progress) -> tuple[str, JobResult]:
            self._progress[job_id] = progress
            token = _current.set(ctx)
            try:
                with (
                    run_logging.job_store_scope(self.store),
                    run_logging.job_log_scope(lambda text, level: ctx._report("log", {"text": text, "level": level})),
                ):
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
        self,
        job: Callable[[Any, Locations], Any],
        launch: Any,
        loc: Locations,
        title: str = "Job",
        writes: bool = True,
        **gates: bool,
    ) -> str:
        """An old-style logged job (work.runner.run_job_result): its log file, jobs-index record and undo record
        stay as they were, and its lines also reach the bus as log events."""
        return self.start(
            lambda _ctx: service_jobs.run_job_result(job, launch, loc, title), title=title, writes=writes, **gates
        )

    # ------------------------------------------------------------------ facts
    @property
    def busy(self) -> bool:
        """A writing job runs (here or, by external_busy, outside this manager)."""
        return self._writer is not None or bool(self._external_busy and self._external_busy())

    @property
    def game_running(self) -> bool:
        return bool(self._game_running and self._game_running())

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
            self._emit(type, data, None if type == "notice" else job_id)  # a notice is the player's, not the job's
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
            self._emit("finished", {"result": result.result, "undo": result.undo}, job_id)
        else:
            data = {"error": _error_data(result.error), "unexpected": result.unexpected}
            self._emit(result.state == "cancelled" and "cancelled" or "failed", data, job_id)

    def _emit(self, type: str, data: dict, job_id: str | None) -> None:
        if self._observer is not None:
            try:
                self._observer(type, data, job_id)
            except Exception:  # an observer never stops a job
                run_logging.get_logger("job").exception("a job observer failed")
        self.bus.publish(type, data, job_id)

    def _publish_prompt(self, data: dict) -> None:
        data = dict(data)
        self._emit("prompt", data, data.pop("job_id", None))

    def _forget_old(self) -> None:
        over = len(self._records) - self._keep
        for job_id in [i for i, r in self._records.items() if r.state != "running"][: max(over, 0)]:
            del self._records[job_id]
