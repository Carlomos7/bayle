"""The Activity operations through Session.run / snapshot / answer: no Qt, no window."""

import pytest

from bayle.config.settings import data_dir
from bayle.mods import undo as mod_undo
from bayle.platform import logging as run_logging
from bayle.services.errors import OperationError
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm, Refusal
from support import FakeActivityFacts, er


def inline(run, name=None):
    run()


JOBS = [
    {"id": "i1", "title": "install mod GM", "kind": "install", "game": "eldenring", "start": "2026-10-09T09:30:00",
     "outcome": "done", "log": "i1.log", "summary": "done", "undo": {"type": "install", "name": "GM", "profile": "a.me3"}},
    {"id": "r1", "title": "rebuild", "kind": "rebuild", "game": "eldenring", "start": "2026-10-08T21:03:00",
     "outcome": "failed", "log": "r1.log", "problem": "clash", "undo": {"type": "rebuild"}},
]  # fmt: skip


def make(facts=None, **jobs_kw):
    jobs = JobManager(EventBus(), spawn=inline, **jobs_kw)
    return Session(jobs, plans=PlanStore(), locations=er, services={"activity": facts or FakeActivityFacts(JOBS)})


def test_the_snapshot_lists_jobs_with_undo_and_the_unseen_count():
    state = make().snapshot("activity")
    items = [j for d in state.days for j in d.jobs]
    assert [(j.id, bool(j.undo_label)) for j in items] == [("i1", True), ("r1", False)]  # a failed job is not undone
    assert state.unseen == 1


def test_the_snapshot_takes_filters():
    state = make().snapshot("activity", failed_only=True)
    assert [j.id for d in state.days for j in d.jobs] == ["r1"]
    with pytest.raises(OperationError) as e:
        make().snapshot("activity", failed_only="maybe")
    assert e.value.code == "invalid_params"


def test_log_attachment_and_copy_reads():
    entries = [{"time": "09:30:00.000", "level": "error", "source": "job", "text": "path C:/Users/carlos/x"}]
    facts = FakeActivityFacts(
        JOBS,
        logs={"i1.log": {"entries": entries, "cut": False, "missing": False}, "i1.me3.log": {"text": "me3 said", "cut": False, "missing": False}},
        files={"i1.log": "C:/logs/i1.log"},
    )  # fmt: skip
    s = make(facts)
    log = s.run("activity.log", {"job_id": "i1"})
    assert [(r.level, r.text) for r in log.rows] == [("error", "path C:/Users/carlos/x")]
    assert s.run("activity.log", {"job_id": "i1", "source": "i1.me3.log"}).plain == "me3 said"
    assert s.run("activity.log", {"job_id": "i1", "source": "gone.log"}).missing
    assert "path C:/Users/carlos/x" in s.run("activity.copy", {"job_id": "i1"}).text
    assert s.run("activity.log_file", {"job_id": "i1"}).path == "C:/logs/i1.log"
    assert s.run("activity.log_file", {"job_id": "r1"}).path is None


def test_unseen_and_mark_seen_with_the_real_service():
    s = Session(
        JobManager(EventBus(), spawn=inline), plans=PlanStore()
    )  # the default service, on the test's data folder
    job = run_logging.begin_job("rebuild combined parameters", game="eldenring")
    run_logging.end_job(job, "failed")
    assert s.run("activity.unseen").count == 1
    assert s.run("activity.mark_seen").at > 0
    assert s.run("activity.unseen").count == 0
    assert s.snapshot("activity").unseen == 0


def _tree():
    root = data_dir()
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def test_reading_the_page_writes_nothing():
    job = run_logging.begin_job("install mod GM", game="eldenring")
    run_logging.log("hello")
    run_logging.end_job(job, "failed")
    s = Session(JobManager(EventBus(), spawn=inline), plans=PlanStore())
    before = _tree()
    state = s.snapshot("activity")
    s.run("activity.unseen")
    s.run("activity.log", {"job_id": job.id})
    s.run("activity.copy", {"job_id": job.id, "for_support": True})
    s.run("activity.log_file", {"job_id": job.id})
    assert [j.id for d in state.days for j in d.jobs] == [job.id]
    assert _tree() == before


def test_undo_offers_a_confirm_and_answering_it_runs_the_undo_as_a_job(monkeypatch):
    ran = []
    monkeypatch.setattr(mod_undo, "run", lambda u, log, loc: ran.append(u["type"]) or "undid it")
    s = make()
    plan = s.run("activity.undo", {"job_id": "i1"})
    assert plan.id and isinstance(plan.words, Confirm) and plan.words.title == "Undo the install of GM"
    assert ran == []  # nothing before the answer
    job_id = s.answer(plan.id, {"ok": True})
    snap = s.jobs.get(job_id)
    assert (snap.state, snap.result, snap.title) == ("done", {"said": "undid it"}, "Restoring GM...")
    assert ran == ["install"]


def test_a_declined_undo_runs_nothing(monkeypatch):
    monkeypatch.setattr(mod_undo, "run", lambda *a, **k: pytest.fail("ran"))
    s = make()
    assert s.answer(s.run("activity.undo", {"job_id": "i1"}).id, {"ok": False}) is None


def test_a_failed_undo_is_a_failed_job_with_a_code(monkeypatch):
    def boom(u, log, loc):
        raise mod_undo.UndoError("the files moved")

    monkeypatch.setattr(mod_undo, "run", boom)
    s = make()
    snap = s.jobs.get(s.answer(s.run("activity.undo", {"job_id": "i1"}).id, {}))
    assert (
        snap.state == "failed"
        and snap.error is not None
        and snap.error.code == "undo_failed"
        and "files moved" in snap.error.message
    )


def test_undo_says_why_not_now():
    s = make(game_running=lambda: True)
    rebuild = s.run("activity.undo", {"job_id": "r1"})
    assert isinstance(
        rebuild, Refusal
    )  # the failed rebuild cannot be undone while the game runs, or is no longer offered
    busy = make(external_busy=lambda: True).run("activity.undo", {"job_id": "i1"})
    assert isinstance(busy, Refusal) and busy.title == "Wait for the current job"
    with pytest.raises(OperationError) as e:
        make().run("activity.undo", {"job_id": "nope"})
    assert e.value.code == "not_found"


def test_a_plan_is_refused_when_the_job_was_taken_back_meanwhile(monkeypatch):
    from bayle.session import PlanError

    monkeypatch.setattr(mod_undo, "run", lambda *a, **k: "x")
    jobs = [dict(JOBS[0])]
    s = make(FakeActivityFacts(jobs))
    plan = s.run("activity.undo", {"job_id": "i1"})
    jobs[0]["undo"] = None  # another client undid it
    with pytest.raises(PlanError) as e:
        s.answer(plan.id, {"ok": True})
    assert e.value.code == "plan_stale"
