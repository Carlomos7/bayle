import pytest

from bayle.services.errors import Busy, OperationError
from bayle.session import (
    EventBus,
    JobManager,
    OperationRegistry,
    Params,
    PlanStore,
    Proposal,
    Result,
    Session,
    StartupStep,
)
from bayle.views.common import Confirm, Refusal


def inline(run, name=None):
    run()


class Add(Params):
    a: int
    b: int = 1


class MathScope(Params):
    game: str = "er"


class Sum(Result):
    total: int


@pytest.fixture
def reg():
    r = OperationRegistry()

    @r.operation("math.add", params=Add, result=Sum)
    def add(call, p):
        return {"total": p.a + p.b}

    @r.operation("math.slow_add", params=Add, result=Sum, kind="job", writes=True)
    def slow(call, p):
        call.job.progress(1, 1)
        return Sum(total=p.a + p.b)

    @r.operation("math.plan", params=Add, result=Sum, kind="plan", writes=True)
    def plan(call, p):
        return Proposal(
            Confirm("Add?", (), "Add"), lambda answer: call.session.start(lambda ctx: Sum(total=p.a), title="add")
        )

    @r.page("math", scope=MathScope)
    def page(session, game="er"):
        return {"game": game}

    return r


def make(reg, **kw):
    jobs = JobManager(EventBus(), spawn=inline, game_running=kw.pop("game_running", None))
    return Session(jobs, ops=reg, **kw)


def test_registry_introspection(reg):
    assert [(s.name, s.kind, s.writes, s.page) for s in reg.specs()] == [
        ("math.add", "read", False, "math"),
        ("math.plan", "plan", True, "math"),
        ("math.slow_add", "job", True, "math"),
    ]
    assert reg.get("math.add").params is Add and reg.get("math.add").result is Sum
    assert reg.pages() == ["math"]


def test_duplicate_and_bad_registration(reg):
    with pytest.raises(ValueError, match="already"):
        reg.operation("math.add", result=Sum)(lambda c, p: None)
    with pytest.raises(ValueError, match="kind"):
        reg.operation("x.y", result=Sum, kind="query")(lambda c, p: None)
    with pytest.raises(ValueError, match="must not write"):
        reg.operation("x.z", result=Sum, writes=True)(lambda c, p: None)


def test_read_returns_validated_result_from_dict_or_model(reg):
    s = make(reg)
    assert s.run("math.add", {"a": 2, "b": 3}) == Sum(total=5)
    assert s.run("math.add", Add(a=2)) == Sum(total=3)


def test_job_returns_id_and_result_is_json(reg):
    s = make(reg)
    snap = s.jobs.get(s.run("math.slow_add", {"a": 4}))
    assert snap.state == "done" and snap.result == {"total": 5} and snap.title == "math.slow_add"


def test_job_write_hits_busy_gate(reg):
    with pytest.raises(Busy):
        make(reg, game_running=lambda: True).run("math.slow_add", {"a": 1})
    make(reg, game_running=lambda: True).run("math.add", {"a": 1})  # reads are not gated


def test_unknown_operation_and_page(reg):
    s = make(reg)
    with pytest.raises(OperationError) as e:
        s.run("nope")
    assert e.value.code == "unknown_operation"
    with pytest.raises(OperationError) as e:
        s.snapshot("nope")
    assert e.value.code == "unknown_page"


@pytest.mark.parametrize("bad", [{}, {"a": "x"}, {"a": 1, "zzz": 2}])
def test_bad_params_are_invalid_params(reg, bad):
    with pytest.raises(OperationError) as e:
        make(reg).run("math.add", bad)
    assert e.value.code == "invalid_params" and e.value.details["errors"]


def test_snapshot_passes_scope(reg):
    assert make(reg).snapshot("math", game="ds3") == {"game": "ds3"}


def test_answer_needs_a_plan_store(reg):
    with pytest.raises(OperationError) as e:
        make(reg).answer("t", {})
    assert e.value.code == "no_plans"

    class Store:
        def answer(self, token, answers):
            return (token, dict(answers))

    assert make(reg, plans=Store()).answer("t", {"k": 1}) == ("t", {"k": 1})


def test_startup_runs_in_order_and_survives_a_failure(reg):
    seen = []

    def boom():
        raise RuntimeError("bad")

    steps = [
        StartupStep("a", lambda: seen.append("a") or ["did a"]),
        StartupStep("b", boom),
        StartupStep("c", lambda: seen.append("c")),
    ]
    reports = make(reg, startup_steps=steps).startup()
    assert seen == ["a", "c"]
    assert [(r.name, r.ok) for r in reports] == [("a", True), ("b", False), ("c", True)]
    assert reports[0].done == ["did a"] and reports[1].error == "bad"


def test_a_command_runs_inline_and_may_write(reg):
    @reg.operation("math.note", params=Add, result=Sum, kind="command", writes=True)
    def note(call, p):
        return Sum(total=p.a)

    assert make(reg).run("math.note", {"a": 7}) == Sum(total=7)


def test_a_plan_is_offered_with_an_id_and_answering_it_starts_the_job(reg):
    s = make(reg, plans=PlanStore())
    plan = s.run("math.plan", {"a": 9})
    assert plan.words.title == "Add?" and plan.id
    job_id = s.answer(plan.id, {"ok": True})
    assert s.jobs.get(job_id).result == {"total": 9}
    with pytest.raises(OperationError) as e:
        s.answer(plan.id, {"ok": True})  # a plan runs once
    assert e.value.code == "unknown_plan"


def test_a_cancelled_answer_starts_nothing(reg):
    s = make(reg, plans=PlanStore())
    assert s.answer(s.run("math.plan", {"a": 1}).id, {"ok": False}) is None
    assert s.jobs.get("j1") is None


def test_a_plan_can_be_a_refusal_and_needs_a_plan_store(reg):
    @reg.operation("math.no", result=Sum, kind="plan")
    def no(call, p):
        return Refusal("Not now", "Because.")

    assert make(reg).run("math.no") == Refusal("Not now", "Because.")  # nothing to store
    with pytest.raises(OperationError) as e:
        make(reg).run("math.plan", {"a": 1})
    assert e.value.code == "no_plans"


def test_a_job_takes_its_title_from_its_params_and_is_refused_before_it_starts_when_checked():
    r = OperationRegistry()

    def check(call, p):
        if p.a < 0:
            raise OperationError("negative", "No negatives.")

    @r.operation(
        "math.checked",
        params=Add,
        result=Sum,
        kind="job",
        writes=True,
        title=lambda call, p: f"Adding {p.a}...",
        check=check,
        quiet=True,
    )
    def checked(call, p):
        return Sum(total=p.a + p.b)

    s = Session(JobManager(EventBus(), spawn=inline), ops=r)
    sub = s.jobs.bus.subscribe()
    job = s.run("math.checked", {"a": 2})
    snap = s.jobs.get(job)
    assert (snap.title, snap.state, snap.result) == ("Adding 2...", "done", {"total": 3})
    started = [e for e in iter(lambda: sub.get(0), None) if e.type == "started"]
    assert started[0].data == {"title": "Adding 2...", "quiet": True}
    with pytest.raises(OperationError) as e:
        s.run("math.checked", {"a": -1})
    assert e.value.code == "negative" and s.jobs.get("j2") is None  # nothing started
