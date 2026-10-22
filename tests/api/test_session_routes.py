"""The generic page / operation / plan routes, with Activity as the page."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.mods import undo as mod_undo
from bayle.session import EventBus, JobManager, PlanStore, Session
from support import FakeActivityFacts, er

TOKEN = "t" * 32
AUTH = {"Authorization": f"Bearer {TOKEN}"}
JOBS = [
    {"id": "i1", "title": "install mod GM", "kind": "install", "game": "eldenring", "start": "2026-10-09T09:30:00",
     "outcome": "done", "log": "i1.log", "summary": "done", "undo": {"type": "install", "name": "GM", "profile": "a.me3"}},
    {"id": "r1", "title": "rebuild", "kind": "rebuild", "game": "eldenring", "start": "2026-10-08T21:03:00",
     "outcome": "failed", "log": "r1.log", "problem": "clash"},
]  # fmt: skip


@pytest.fixture
def client():
    session = Session(
        JobManager(EventBus(), spawn=lambda run, name=None: run()),
        plans=PlanStore(),
        locations=er,
        services={
            "activity": FakeActivityFacts(JOBS, logs={"i1.log": {"entries": [], "cut": False, "missing": False}})
        },
    )
    with TestClient(create_app(ApiSettings(token=TOKEN), session), base_url="http://127.0.0.1") as c:
        c.headers.update(AUTH)
        yield c


def test_a_page_snapshot_with_filters(client):
    body = client.get("/v1/pages/activity").json()
    assert [j["id"] for d in body["days"] for j in d["jobs"]] == ["i1", "r1"] and body["unseen"] == 1
    failed = client.get("/v1/pages/activity", params={"failed_only": "true"}).json()
    assert [j["id"] for d in failed["days"] for j in d["jobs"]] == ["r1"]
    assert client.get("/v1/pages/activity", params={"nope": 1}).status_code == 422


def test_a_read_and_a_command_answer_with_their_result(client):
    assert client.post("/v1/ops/activity.unseen").json() == {"count": 1}
    log = client.post("/v1/ops/activity.log", json={"job_id": "i1"}).json()
    assert log["rows"] == [] and log["missing"] is False
    assert client.post("/v1/ops/activity.mark_seen").json()["at"] > 0


def test_bad_params_and_unknown_names_are_problems(client):
    r = client.post("/v1/ops/activity.log", json={})
    assert r.status_code == 422 and r.json()["code"] == "invalid_params"
    r = client.post("/v1/ops/activity.log", json={"job_id": "i1", "zzz": 1})
    assert r.status_code == 422
    assert client.post("/v1/ops/activity.nope").status_code == 404
    assert client.get("/v1/pages/nope").status_code == 404


def test_a_plan_is_offered_answered_once_and_starts_a_job(client, monkeypatch):
    monkeypatch.setattr(mod_undo, "run", lambda u, log, loc: "undid it")
    offer = client.post("/v1/ops/activity.undo", json={"job_id": "i1"}).json()
    assert offer["prompt"]["kind"] == "confirm" and offer["prompt"]["title"] == "Undo the install of GM"
    done = client.post(f"/v1/plans/{offer['plan_id']}", json={"ok": True})
    assert done.status_code == 200
    job = client.get(f"/v1/jobs/{done.json()['job_id']}").json()
    assert (job["state"], job["result"]) == ("done", {"said": "undid it"})
    again = client.post(f"/v1/plans/{offer['plan_id']}", json={"ok": True})
    assert again.status_code == 404 and again.json()["code"] == "unknown_plan"


def test_a_refusal_has_no_plan(client):
    # a failed rebuild with no undo record: nothing to take back
    r = client.post("/v1/ops/activity.undo", json={"job_id": "r1"}).json()
    assert r["plan_id"] is None and r["prompt"]["kind"] == "refusal"


def test_the_spec_carries_each_operations_own_schemas(app):
    spec = app.openapi()
    undo = spec["paths"]["/v1/ops/activity.undo"]["post"]
    assert undo["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/JobRef")
    assert "/v1/pages/activity" in spec["paths"] and "/v1/plans/{plan_id}" in spec["paths"]
    mark = spec["paths"]["/v1/ops/activity.mark_seen"]["post"]
    assert "requestBody" not in mark
