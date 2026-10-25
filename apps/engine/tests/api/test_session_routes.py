"""The generic page and operation routes, with Activity as the page (the plan routes: test_mods_routes)."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.modules.mods import undo as mod_undo
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import FakeActivityFacts

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
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    logs = {"i1.log": {"entries": [], "cut": False, "missing": False}}
    services = {"activity": FakeActivityFacts(JOBS, logs=logs, manager=jobs)}
    with TestClient(
        create_app(ApiSettings(token=TOKEN), jobs=jobs, services=services), base_url="http://127.0.0.1"
    ) as c:
        c.headers.update(AUTH)
        yield c


def test_a_page_snapshot_is_the_records(client):
    body = client.get("/v1/activity").json()
    assert [j["id"] for j in body["jobs"]] == ["i1", "r1"] and body["unseen"] == 1
    assert client.get("/v1/activity", params={"nope": 1}).status_code == 422


def test_a_read_and_a_command_answer_with_their_result(client):
    assert client.post("/v1/activity/unseen").json() == {"count": 1}
    log = client.post("/v1/activity/log", json={"job_id": "i1"}).json()
    assert log["entries"] == [] and log["attachment"] is False and log["missing"] is False
    assert client.post("/v1/activity/mark_seen").json()["at"] > 0


def test_bad_params_and_unknown_names_are_problems(client):
    r = client.post("/v1/activity/log", json={})
    assert r.status_code == 422 and r.json()["code"] == "invalid_params"
    r = client.post("/v1/activity/log", json={"job_id": "i1", "zzz": 1})
    assert r.status_code == 422
    assert client.post("/v1/activity/nope").status_code == 404
    assert client.get("/v1/pages/nope").status_code == 404


def test_undo_starts_a_job_for_the_record_the_client_saw(client, monkeypatch):
    monkeypatch.setattr(mod_undo, "run", lambda u, log, loc: "undid it")
    expect = JOBS[0]["undo"]
    stale = client.post("/v1/activity/undo", json={"job_id": "i1", "expect": {**expect, "name": "other"}})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    started = client.post("/v1/activity/undo", json={"job_id": "i1", "expect": expect}).json()
    job = client.get(f"/v1/jobs/{started['job_id']}").json()
    assert (job["state"], job["result"]) == ("done", {"said": "undid it"})


def test_an_undo_refusal_is_a_problem_with_a_code(client):
    # a failed rebuild with no undo record: nothing to take back
    r = client.post("/v1/activity/undo", json={"job_id": "r1", "expect": {}})
    assert r.status_code == 400 and r.json()["code"] == "gone"
    assert client.post("/v1/activity/undo", json={"job_id": "nope", "expect": {}}).status_code == 404


def test_the_spec_carries_each_operations_own_schemas(app):
    spec = app.openapi()
    undo = spec["paths"]["/v1/activity/undo"]["post"]
    assert undo["requestBody"]["content"]["application/json"]["schema"]["$ref"].endswith("/TakeBack")
    assert "/v1/activity" in spec["paths"] and "/v1/prompts/{prompt_id}" in spec["paths"]
    assert not any(p.startswith(("/v1/ops", "/v1/pages", "/v1/plans")) for p in spec["paths"])  # the registry is gone
    mark = spec["paths"]["/v1/activity/mark_seen"]["post"]
    assert "requestBody" not in mark
