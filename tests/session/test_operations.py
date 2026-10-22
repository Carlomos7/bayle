import pytest

from bayle.services.errors import Busy, OperationError
from bayle.session import EventBus, JobManager, OperationRegistry, Params, Result, Session, StartupStep


def inline(run, name=None):
    run()


class Add(Params):
    a: int
    b: int = 1


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

    @r.operation("math.plan", params=Add, result=Sum, kind="plan")
    def plan(call, p):
        return Sum(total=0)

    @r.page("math")
    def page(session, game="er"):
        return {"game": game}

    return r


def make(reg, **kw):
    jobs = JobManager(EventBus(), spawn=inline, game_running=kw.pop("game_running", None))
    return Session(jobs, ops=reg, **kw)


def test_registry_introspection(reg):
    assert [(s.name, s.kind, s.writes, s.page) for s in reg.specs()] == [
        ("math.add", "read", False, "math"),
        ("math.plan", "plan", False, "math"),
        ("math.slow_add", "job", True, "math"),
    ]
    assert reg.get("math.add").params is Add and reg.get("math.add").result is Sum
    assert reg.pages() == ["math"]


def test_duplicate_and_bad_registration(reg):
    with pytest.raises(ValueError, match="already"):
        reg.operation("math.add", result=Sum)(lambda c, p: None)
    with pytest.raises(ValueError, match="kind"):
        reg.operation("x.y", result=Sum, kind="query")(lambda c, p: None)
    with pytest.raises(ValueError, match="only a job"):
        reg.operation("x.z", result=Sum, writes=True)(lambda c, p: None)


def test_read_returns_validated_result_from_dict_or_model(reg):
    s = make(reg)
    assert s.run("math.add", {"a": 2, "b": 3}) == Sum(total=5)
    assert s.run("math.add", Add(a=2)) == Sum(total=3)
    assert s.run("math.plan", {"a": 0}) == Sum(total=0)


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
