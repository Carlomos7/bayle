"""The Activity interface (services.activity) without Qt: its reads, its undo rules on the shared job manager, and the
store it is handed. The HTTP ops over it: tests/api/test_session_routes.py."""

import time

import pytest

from bayle.config.settings import DATA_ENV, data_dir
from bayle.errors import Busy, OperationError
from bayle.mods import models as mod_models
from bayle.mods import undo as mod_undo
from bayle.platform import logging as run_logging
from bayle.services.activity import ActivityService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import FakeActivityFacts, er


def inline(run, name=None):
    run()


JOBS = [
    {"id": "i1", "title": "install mod GM", "kind": "install", "game": "eldenring", "start": "2026-10-09T09:30:00",
     "outcome": "done", "log": "i1.log", "summary": "done", "undo": {"type": "install", "name": "GM", "profile": "a.me3"}},
    {"id": "r1", "title": "rebuild", "kind": "rebuild", "game": "eldenring", "start": "2026-10-08T21:03:00",
     "outcome": "done", "log": "r1.log", "undo": {"type": "rebuild"}},
]  # fmt: skip


def make(jobs=JOBS, available=bool, **gates) -> FakeActivityFacts:
    logs = {
        "i1.log": {"entries": [{"time": "09:30", "level": "error", "source": "job", "text": "x"}], "cut": True, "missing": False},
        "i1.me3.log": {"text": "me3 said", "cut": False, "missing": False},
    }  # fmt: skip
    manager = JobManager(EventBus(), spawn=inline, **gates)
    return FakeActivityFacts(jobs, available, logs=logs, files={"i1.log": "C:/logs/i1.log"}, manager=manager)


def code(call) -> str:
    with pytest.raises(OperationError) as e:
        call()
    return e.value.code


def test_a_jobs_log_its_attachment_and_its_file():
    a = make()
    log = a.log("i1")
    assert (log.entries[0]["text"], log.attachment, log.cut, log.missing) == ("x", False, True, False)
    other = a.log("i1", "i1.me3.log")
    assert (other.text, other.attachment) == ("me3 said", True)
    assert a.log("i1", "gone.log").missing and a.log("nope").missing
    assert a.log_path("i1") == "C:/logs/i1.log" and a.log_path("r1") is None


def test_undo_says_why_not_now_as_codes():
    assert code(lambda: make().check_undo("nope")) == "not_found"
    assert code(lambda: make(external_busy=lambda: True).check_undo("i1")) == "busy"
    assert code(lambda: make(available=lambda u: False).check_undo("i1")) == "gone"
    running = make(game_running=lambda: True)
    assert code(lambda: running.check_undo("r1")) == "game_running"  # the rebuild's files are in use
    assert running.check_undo("i1")["id"] == "i1"  # other kinds are refused by the job manager when they start


def test_undo_runs_as_a_writing_job_on_the_shared_manager(monkeypatch):
    ran = []
    monkeypatch.setattr(mod_undo, "run", lambda u, log, loc: ran.append(u["type"]) or "undid it")
    a = make()
    snap = a._jobs.get(a.undo("i1", JOBS[0]["undo"], "Restoring GM..."))
    assert (snap.state, snap.result, snap.title) == ("done", {"said": "undid it"}, "Restoring GM...")
    assert ran == ["install"]
    default = a._jobs.get(a.undo("r1", JOBS[1]["undo"]))
    assert default.title == "launcher: undo the rebuild"


def test_undo_checks_again_when_it_starts(monkeypatch):
    monkeypatch.setattr(mod_undo, "run", lambda *a, **k: pytest.fail("ran"))
    assert code(lambda: make().undo("i1", {**JOBS[0]["undo"], "name": "other"})) == "stale"  # changed since asked
    assert code(lambda: make(external_busy=lambda: True).undo("i1", JOBS[0]["undo"])) == "busy"
    with pytest.raises(Busy) as e:  # the manager's own gate: no writing job while the game runs
        make(game_running=lambda: True).undo("i1", JOBS[0]["undo"])
    assert e.value.details == {"reason": "game_running"}


def test_a_failed_undo_is_a_failed_job_with_a_code(monkeypatch):
    def boom(u, log, loc):
        raise mod_models.UndoError("the files moved")

    monkeypatch.setattr(mod_undo, "run", boom)
    a = make()
    snap = a._jobs.get(a.undo("i1", JOBS[0]["undo"]))
    assert snap.state == "failed" and snap.error is not None and snap.error.code == "undo_failed"
    assert "files moved" in snap.error.message


class Store:
    def __init__(self, records):
        self._records, self.saved = records, []

    def save(self, record):
        self.saved.append(record)
        return True

    def records(self):
        return list(self._records)


class Unbound:
    def save(self, record):
        raise AssertionError("the runtime's slot was used")

    records = save


def test_the_records_come_from_the_store_it_is_handed(monkeypatch):
    row = {
        "id": "db1",
        "title": "rebuild",
        "kind": "rebuild",
        "start": "2026-10-09T09:30:00",
        "outcome": "failed",
        "t": time.time(),
    }
    store = Store([row])
    a = ActivityService(JobManager(EventBus(), spawn=inline), store, er)
    assert [r["id"] for r in a.jobs()] == ["db1"] and a.record("db1") is not None
    assert a.unseen() == 1
    run_logging.mark_undone("db1", store)  # what a finished undo writes goes to the same store
    assert store.saved[-1]["id"] == "db1" and store.saved[-1]["undone"]


def test_a_job_the_manager_runs_writes_to_the_managers_store_whatever_else_is_in_scope():
    mine = Store([])
    manager = JobManager(EventBus(), spawn=inline, store=mine)
    with run_logging.job_store_scope(Unbound()):  # another store in scope around the call: the manager's work wins
        job_id = manager.start(lambda _ctx: run_logging.end_job(run_logging.begin_job("rebuild x", game="eldenring")))
    assert manager.get(job_id).state == "done"
    assert [r["title"] for r in mine.saved] == ["rebuild x", "rebuild x"]  # begun, then ended
    assert mine.saved[-1]["outcome"] == "done"


def test_unseen_and_mark_seen_with_the_real_reads():
    a = ActivityService(JobManager(EventBus(), spawn=inline), None, er)  # the test's data folder, no database
    job = run_logging.begin_job("rebuild combined parameters", game="eldenring")
    run_logging.end_job(job, "failed")
    assert a.unseen() == 1
    assert a.mark_seen() > 0
    assert a.unseen() == 0


def _tree():
    root = data_dir()
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def test_reading_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv(DATA_ENV, str(tmp_path))  # scan only this test's data, not the repository a source run uses
    job = run_logging.begin_job("install mod GM", game="eldenring")
    run_logging.log("hello")
    run_logging.end_job(job, "failed")
    a = ActivityService(JobManager(EventBus(), spawn=inline), None, er)
    before = _tree()
    assert [r["id"] for r in a.jobs()] == [job.id]
    a.unseen(), a.log(job.id), a.log_path(job.id)
    assert _tree() == before
