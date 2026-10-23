"""The Mods page and its operations over HTTP: the same Session, reached through the generic routes."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore
from support import er, mods_profile

TOKEN = "t" * 32


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


@pytest.fixture
def client():
    session = Session(JobManager(EventBus(), spawn=lambda run, name=None: run()), plans=PlanStore(), locations=er)
    with TestClient(create_app(ApiSettings(token=TOKEN), session), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def test_the_page_snapshot_is_served_with_its_filters(client, profile):
    body = client.get("/v1/pages/mods", params={"profile": str(profile)}).json()
    assert body["has_profile"] and [r["name"] for r in body["state"]["groups"][0]["rows"]] == ["flora", "cloud"]
    assert body["load_order"]["clash_total"] == 0 and len(body["entries"]) == 3
    assert client.get("/v1/pages/mods", params={"nope": 1}).status_code == 422


def test_a_command_a_refusal_with_a_code_and_a_job_over_http(client, profile):
    ref = {"profile": str(profile), "index": 0}
    done = client.post("/v1/ops/mods.set_enabled", json={**ref, "enabled": False}).json()
    assert done["note"] == "profile: flora off"
    gone = client.post("/v1/ops/mods.set_enabled", json={**ref, "index": 99, "enabled": False})
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"
    asked = client.post("/v1/ops/mods.set_setting", json={"profile": str(profile), "key": "start_online", "value": 1})
    assert asked.json()["code"] == "needs_confirmation" and asked.json()["details"]["prompt"]["kind"] == "confirm"
    job = client.post("/v1/ops/mods.rename", json={**ref, "index": 1, "name": "cloud2"})
    assert job.status_code == 202
    assert client.get(f"/v1/jobs/{job.json()['job_id']}").json()["state"] == "done"


def test_a_plan_over_http_asks_then_starts_its_job(client, profile):
    offer = client.post("/v1/ops/mods.dll_folders", json={"profile": str(profile)}).json()
    assert offer["prompt"]["kind"] == "confirm" and offer["plan_id"]
    done = client.post(f"/v1/plans/{offer['plan_id']}", json={"ok": True})
    assert client.get(f"/v1/jobs/{done.json()['job_id']}").json()["state"] == "done"
    used = client.post(f"/v1/plans/{offer['plan_id']}", json={"ok": True})  # a plan is answered once
    assert used.status_code == 404 and used.json()["code"] == "unknown_plan"
    again = client.post("/v1/ops/mods.dll_folders", json={"profile": str(profile)}).json()
    assert again["plan_id"] is None and again["prompt"]["kind"] == "refusal"
