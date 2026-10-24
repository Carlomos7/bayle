"""The job runner (work/runner.py): work runs on a thread of its own and reports progress, then its result, as
events in order; a failure reaches threading.excepthook and posts no result."""

import threading

import pytest

from bayle.errors import Busy, Cancelled, ErrorInfo, OperationError
from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.work import runner as jobs


def collect():
    events, finished = [], threading.Event()

    def post(event):
        events.append(event)
        if event.kind == jobs.RESULT:
            finished.set()

    return events, finished, post


def test_progress_then_the_result_in_order():
    events, finished, post = collect()

    def work(progress):
        progress("one")
        progress("two")
        return 42

    task = jobs.Runner(post).start(work)
    assert finished.wait(5)
    assert [(e.task, e.kind, e.value) for e in events] == [
        (task, jobs.PROGRESS, "one"),
        (task, jobs.PROGRESS, "two"),
        (task, jobs.RESULT, 42),
    ]


def test_threads_are_named_like_threading_names_them(monkeypatch):
    names, finished = [], threading.Event()

    def work(_progress):
        names.append(threading.current_thread().name)

    runner = jobs.Runner(lambda e: finished.set() if e.kind == jobs.RESULT else None)
    runner.start(work, name="launcher-update")
    assert finished.wait(5)
    finished.clear()
    runner.start(work)
    assert finished.wait(5)
    assert names[0] == "launcher-update" and names[1].endswith("(work)")  # crash reports name the thread


def test_a_failure_reaches_the_excepthook_and_posts_no_result(monkeypatch):
    events, seen = [], threading.Event()
    caught = []
    monkeypatch.setattr(threading, "excepthook", lambda a: (caught.append(a.exc_type), seen.set()))

    def work(_progress):
        raise ValueError("boom")

    jobs.Runner(events.append).start(work)
    assert seen.wait(5)
    assert caught == [ValueError] and events == []


def test_a_logged_job_posts_its_outcome():
    events, finished, post = collect()
    jobs.Runner(post).start_job(lambda launch, loc: None, None, Locations(catalog.ELDEN_RING), "Testing...")
    assert finished.wait(5)
    assert events[-1].value == jobs.Outcome(True, "Finished")


LOC = Locations(catalog.ELDEN_RING)


def exits(code):
    def job(_launch, _loc):
        raise SystemExit(code)

    return job


def raises(exc):
    def job(_launch, _loc):
        raise exc

    return job


@pytest.mark.parametrize(
    ("job", "state", "status"),
    [
        (lambda a, b: None, "done", "Finished"),
        (exits(0), "done", "Finished"),
        (exits(None), "done", "Finished"),
        (exits(1), "failed", "Stopped (see details)"),
        (exits(130), "cancelled", "Stopped (see details)"),
        (raises(ValueError("boom")), "failed", "Error (see details)"),
        (raises(Cancelled()), "cancelled", "Stopped (see details)"),
        (raises(Busy()), "failed", "Stopped (see details)"),
        (raises(OperationError("x", "no")), "failed", "Stopped (see details)"),
    ],
)
def test_every_ending_maps_to_a_state_and_the_old_outcome(job, state, status):
    result = jobs.run_job_result(job, None, LOC, "Testing...")
    assert result.state == state
    assert jobs.run_job(job, None, LOC, "Testing...") == jobs.Outcome(state == "done", status)


def test_a_job_returns_its_result_and_an_operation_error_its_code():
    assert jobs.run_job_result(lambda a, b: {"n": 3}, None, LOC).result == {"n": 3}
    err = jobs.run_job_result(raises(OperationError("bad_thing", "Nope", {"k": 1})), None, LOC).error
    assert err == ErrorInfo("bad_thing", "Nope", {"k": 1})
    assert jobs.run_job_result(raises(Cancelled()), None, LOC).error.code == "cancelled"
    assert jobs.run_job_result(exits(1), None, LOC).error.code == "failed"


def test_run_logged_turns_a_plain_failure_into_an_operation_error():
    def job(_launch, loc):
        with jobs.run_logged("Testing...", loc.game.key):
            raise OSError("disk gone")

    err = jobs.run_job_result(job, None, LOC).error
    assert (err.code, err.message) == ("failed", "disk gone")


def test_run_logged_lets_codes_and_exits_through():
    def coded(_launch, loc):
        with jobs.run_logged("Testing...", loc.game.key):
            raise Busy()

    def stopped(_launch, loc):
        with jobs.run_logged("Testing...", loc.game.key):
            raise SystemExit(130)

    assert jobs.run_job_result(coded, None, LOC).error.code == "busy"
    assert jobs.run_job_result(stopped, None, LOC).state == "cancelled"
