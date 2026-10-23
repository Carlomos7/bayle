import threading

import pytest

from bayle.views.common import Choice, Choose, Confirm, Pick, Refusal, prompt_dict
from bayle.work.prompts import Answer, PlanError, PlanStore, PromptBroker

WORDS = Confirm("Remove a?", ("a goes",), "Remove", safety="Undo in Activity.")


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_the_schema_is_json_clean_with_its_kind():
    assert prompt_dict(WORDS) == {
        "kind": "confirm",
        "title": "Remove a?",
        "changes": ["a goes"],
        "apply": "Remove",
        "warning": "",
        "safety": "Undo in Activity.",
        "detail": "",
        "option": "",
        "option_checked": False,
    }
    assert prompt_dict(Refusal("No", "Because"))["kind"] == "refusal"
    assert prompt_dict(Pick("t", "b", "Go", ticked=(1,)))["ticked"] == [1]
    assert prompt_dict(Choose("q", ("l",), (Choice("go", "Go", "primary"),)))["choices"] == [
        {"key": "go", "label": "Go", "role": "primary"}
    ]


def test_execute_runs_the_plan_once_with_the_answer():
    store, seen = PlanStore(), []
    plan = store.add(WORDS, lambda a: seen.append(a) or "done")
    assert plan.to_dict()["prompt"]["kind"] == "confirm"
    assert store.execute(plan.id, Answer(option=True)) == "done" and seen == [Answer(option=True)]
    with pytest.raises(PlanError) as e:  # a double click, or a replayed request
        store.execute(plan.id, Answer())
    assert e.value.code == "unknown_plan" and len(seen) == 1


def test_a_cancelled_answer_runs_nothing_and_closes_the_plan():
    store, seen = PlanStore(), []
    plan = store.add(WORDS, seen.append)
    assert store.execute(plan.id, Answer(ok=False)) is None and seen == []
    assert store.get(plan.id) is None


def test_a_plan_expires_after_its_ttl():
    clock, seen = Clock(), []
    store = PlanStore(clock, ttl=10)
    plan = store.add(WORDS, seen.append)
    clock.now = 9.9
    assert store.get(plan.id) is plan
    clock.now = 10
    with pytest.raises(PlanError) as e:
        store.execute(plan.id, Answer())
    assert e.value.code == "plan_expired" and seen == []
    other = store.add(WORDS, seen.append)
    clock.now = 25
    assert store.get(other.id) is None


def test_a_plan_is_refused_when_what_it_was_made_from_changed():
    state, seen = {"mtime": 1}, []
    store = PlanStore()
    plan = store.add(WORDS, seen.append, stale=lambda: state["mtime"])
    state["mtime"] = 2
    with pytest.raises(PlanError) as e:
        store.execute(plan.id, Answer())
    assert e.value.code == "plan_stale" and seen == []
    fresh = store.add(WORDS, seen.append, stale=lambda: state["mtime"])
    store.execute(fresh.id, Answer())
    assert len(seen) == 1


def test_the_broker_turns_a_prompt_into_an_event_and_routes_the_answer():
    sent, got = [], []
    broker = PromptBroker(sent.append)
    pid = broker.ask(Choose("q", (), (Choice("retry", "Retry"),)), got.append)
    assert sent[0]["prompt_id"] == pid and sent[0]["kind"] == "choose" and broker.pending() == 1
    assert broker.answer(pid, "retry") and got == ["retry"]
    assert not broker.answer(pid, "retry") and got == ["retry"]  # answered once


def test_a_job_thread_waits_for_the_answer():
    sent = []
    broker = PromptBroker(sent.append)
    box = []
    t = threading.Thread(target=lambda: box.append(broker.wait(Choose("q", (), ()), timeout=5)))
    t.start()
    while not sent:
        t.join(0.01)
    broker.answer(sent[0]["prompt_id"], "go")
    t.join()
    assert box == ["go"]
    assert broker.wait(Choose("q", (), ()), timeout=0.01) == "cancel" and broker.pending() == 0
