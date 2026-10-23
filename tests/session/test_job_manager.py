import threading

import pytest

from bayle.platform import logging as run_logging
from bayle.services.errors import Busy, Cancelled, OperationError
from bayle.services.jobs import JobResult
from bayle.session import EventBus, JobManager, current_context
from bayle.session.jobs import notice


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def inline(run, name=None):  # work runs on the caller's thread: deterministic
    run()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def mgr(clock):
    return JobManager(EventBus(), clock=clock, spawn=inline)


def events(mgr, job_id=None):
    sub = mgr.bus.subscribe(since=0)
    out = []
    while (e := sub.get(0)) is not None:
        if job_id is None or e.job_id == job_id:
            out.append(e)
    return out


def test_a_job_emits_started_then_progress_then_finished_with_its_result(mgr, clock):
    def work(ctx):
        ctx.progress(1, 4, "one")
        clock.now += 1
        ctx.progress(4, 4, "done")
        return {"n": 4}

    job = mgr.start(work, title="Count")
    got = events(mgr, job)
    assert [e.type for e in got] == ["started", "progress", "progress", "finished"]
    assert got[1].data == {"done": 1, "total": 4, "label": "one"}
    assert got[-1].data["result"] == {"n": 4}
    snap = mgr.get(job)
    assert (snap.state, snap.result, snap.progress["done"]) == ("done", {"n": 4}, 4)


def test_progress_is_coalesced_to_the_interval_but_the_final_step_passes(mgr, clock):
    def work(ctx):
        for i in range(1, 11):  # 10 steps within 0.05 s
            ctx.progress(i, 10)
            clock.now += 0.005

    job = mgr.start(work)
    steps = [e.data["done"] for e in events(mgr, job) if e.type == "progress"]
    assert steps == [1, 10]
    # past the interval the next step goes through
    clock.now += 0.2

    def more(ctx):
        ctx.progress(1, 10)
        clock.now += 0.11
        ctx.progress(2, 10)

    job = mgr.start(more)
    assert [e.data["done"] for e in events(mgr, job) if e.type == "progress"] == [1, 2]


def test_an_operation_error_ends_the_job_failed_with_its_code(mgr):
    def work(ctx):
        raise OperationError("bad_input", "nope", {"field": "x"})

    job = mgr.start(work)
    last = events(mgr, job)[-1]
    assert last.type == "failed"
    assert last.data["error"] == {"code": "bad_input", "message": "nope", "details": {"field": "x"}}
    assert mgr.get(job).state == "failed"


def test_an_unexpected_exception_is_a_failed_event_not_a_crash(mgr):
    def work(ctx):
        raise RuntimeError("boom")

    job = mgr.start(work)
    last = events(mgr, job)[-1]
    assert last.type == "failed" and last.data["unexpected"] and last.data["error"]["message"] == "boom"


def test_cancelled_error_and_exit_130_end_the_job_cancelled(mgr):
    def a(ctx):
        raise Cancelled()

    def b(ctx):
        raise SystemExit(130)

    assert events(mgr, mgr.start(a))[-1].type == "cancelled"
    assert events(mgr, mgr.start(b))[-1].type == "cancelled"


def test_a_returned_job_result_is_used_as_it_is(mgr):
    job = mgr.start(lambda ctx: JobResult("done", 7, undo={"u": 1}))
    last = events(mgr, job)[-1]
    assert last.type == "finished" and last.data == {"result": 7, "undo": {"u": 1}}


def test_cancel_reaches_the_running_work_through_the_token():
    mgr = JobManager(EventBus())  # real thread
    running, release = threading.Event(), threading.Event()

    def work(ctx):
        running.set()
        release.wait(5)
        ctx.raise_if_cancelled()
        return "not reached"

    sub = mgr.bus.subscribe()
    job = mgr.start(work)
    assert running.wait(5)
    assert mgr.cancel(job) is True
    release.set()
    seen = []
    while (e := sub.get(5)) is not None:
        seen.append(e.type)
        if e.type in ("cancelled", "finished", "failed"):
            break
    assert seen == ["started", "cancelled"]
    assert mgr.cancel(job) is False  # over
    assert mgr.cancel("nope") is False


def test_a_second_writing_job_is_busy_but_reads_and_later_jobs_run():
    mgr = JobManager(EventBus())
    running, release = threading.Event(), threading.Event()

    def slow(ctx):
        running.set()
        release.wait(5)

    sub = mgr.bus.subscribe()
    first = mgr.start(slow)
    assert running.wait(5)
    with pytest.raises(Busy) as busy:
        mgr.start(lambda ctx: None)
    assert busy.value.details["job_id"] == first
    read = mgr.start(lambda ctx: "r", writes=False)  # reads do not queue behind writes
    release.set()
    done = set()
    while len(done) < 2:
        e = sub.get(5)
        assert e is not None
        if e.type == "finished":
            done.add(e.job_id)
    assert done == {first, read}
    mgr.start(lambda ctx: None)  # the writer slot is free again


def test_no_writes_while_the_game_runs_but_reads_are_fine(clock):
    running = [True]
    mgr = JobManager(EventBus(), clock=clock, spawn=inline, game_running=lambda: running[0])
    with pytest.raises(Busy) as busy:
        mgr.start(lambda ctx: None)
    assert busy.value.details == {"reason": "game_running"} and busy.value.code == "busy"
    assert mgr.get(mgr.start(lambda ctx: 1, writes=False)).state == "done"
    running[0] = False
    assert mgr.get(mgr.start(lambda ctx: 1)).state == "done"


def test_log_lines_go_to_the_job_that_wrote_them_and_to_no_other(mgr):
    log = run_logging.get_logger("scope_test")
    a = mgr.start(lambda ctx: log.info("from a"))
    b = mgr.start(lambda ctx: log.warning("from b"))
    log.info("outside any job")
    texts = {j: [(e.data["text"], e.data["level"]) for e in events(mgr, j) if e.type == "log"] for j in (a, b)}
    assert texts == {a: [("from a", "info")], b: [("from b", "warning")]}
    assert not [e for e in events(mgr) if e.type == "log" and e.data["text"] == "outside any job"]


def test_the_job_context_is_reachable_from_old_code_on_the_worker(mgr):
    seen = []
    job = mgr.start(lambda ctx: seen.append(current_context() is ctx and ctx.job_id))
    assert seen == [job] and current_context() is None


def test_finished_jobs_beyond_keep_are_forgotten(clock):
    mgr = JobManager(EventBus(), clock=clock, spawn=inline, keep=2)
    ids = [mgr.start(lambda ctx: None, writes=False) for _ in range(4)]
    assert [mgr.get(i) is not None for i in ids] == [False, False, True, True]


def test_a_notice_from_a_job_reaches_the_bus_as_the_shells_own_and_is_logged(mgr, monkeypatch):
    lines = []
    monkeypatch.setattr(run_logging, "log_line", lambda m, *a: lines.append(m))
    mgr.start(lambda ctx: notice("the game was updated"), writes=False)
    notice("outside a job")  # no job: only logged
    got = [(e.data, e.job_id) for e in events(mgr) if e.type == "notice"]
    assert got == [({"text": "the game was updated", "error": False, "details": True}, None)]
    assert lines == ["warning: the game was updated", "warning: outside a job"]
