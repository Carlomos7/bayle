"""The Settings page and operations over HTTP, on a session whose Settings service is the real one."""

import pytest
from fastapi.testclient import TestClient

from bayle.adapters.system.app_paths import data_dir
from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.modules.launch import play as play_service
from bayle.modules.mods.layout import LayoutError
from bayle.modules.settings import locations as layout_service
from bayle.modules.settings.service import SettingsService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import er

TOKEN = "t" * 32


@pytest.fixture
def client():
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    services = {"settings": SettingsService(jobs, er)}
    with TestClient(
        create_app(ApiSettings(token=TOKEN), jobs=jobs, services=services), base_url="http://127.0.0.1"
    ) as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def test_the_page_a_change_and_a_refusal(client):
    page = client.get("/v1/settings").json()
    assert page["game"] == "eldenring" and any(s["key"] == "logo" for s in page["specs"])
    got = client.post("/v1/settings/set", json={"key": "logo", "value": "gold"}).json()
    assert got == {"key": "logo", "value": "gold", "stored_as": "logo", "follow": "settings", "kind": "choice"}
    assert client.get("/v1/settings").json()["settings"]["logo"] == "gold"
    bad = client.post("/v1/settings/set", json={"key": "logo", "value": "purple"})
    assert bad.status_code == 400 and bad.json()["code"] == "invalid_choice"


def test_folders_and_the_name_check(client):
    assert client.post("/v1/settings/folder", json={"kind": "settings"}).json() == {"path": str(data_dir())}
    assert client.post("/v1/settings/folder", json={"kind": "attic"}).json()["code"] == "unknown_folder"
    ok = client.post("/v1/settings/layout_check", json={"pattern": "b-{game}"}).json()
    assert ok == {"errors": {}, "preview": "b-eldenring"}


def test_renaming_checks_then_starts_a_job_for_what_the_client_saw(client, monkeypatch):
    monkeypatch.setattr(layout_service, "rename_layout", lambda loc, **names: {})
    names = {"pattern": "x-{game}"}
    changes = client.post("/v1/settings/check_rename", json=names).json()["changes"]
    assert list(changes) == ["pattern"]
    stale = client.post("/v1/settings/rename_layout", json={**names, "expect": {"pattern": ["a", "b"]}})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    started = client.post("/v1/settings/rename_layout", json={**names, "expect": changes}).json()
    assert client.get(f"/v1/jobs/{started['job_id']}").json()["state"] == "done"
    nothing = client.post("/v1/settings/check_rename", json={})
    assert nothing.status_code == 400 and nothing.json()["code"] == "nothing_to_change"


def test_a_refused_layout_change_is_a_failed_job(client, monkeypatch):
    def refuse(loc, **names):
        raise LayoutError("The game is open.")

    monkeypatch.setattr(layout_service, "_fn", lambda name: refuse)
    names = {"pattern": "x-{game}"}
    changes = client.post("/v1/settings/check_rename", json=names).json()["changes"]
    job_id = client.post("/v1/settings/rename_layout", json={**names, "expect": changes}).json()["job_id"]
    job = client.get(f"/v1/jobs/{job_id}").json()
    assert job["state"] == "failed" and job["error"]["code"] == "layout_refused"


def test_relocating_and_moving_profiles(client, monkeypatch, tmp_path):
    monkeypatch.setattr(layout_service, "profiles_facts", lambda loc: (3, 2048))
    monkeypatch.setattr(layout_service, "free_bytes", lambda p: 4096)
    target = str(tmp_path / "Bayle")
    got = client.post("/v1/settings/check_relocate", json={"folder": target}).json()
    assert got == {"folder": target, "profiles": 3, "size": 2048, "free": 4096}
    stale = client.post("/v1/settings/relocate", json={"folder": target, "expect_root": "Z:/else"})
    assert stale.json()["code"] == "stale"
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [tmp_path / "a.me3"])
    monkeypatch.setattr(layout_service, "move_all", lambda loc, found: len(found))
    assert client.post("/v1/settings/check_move_all").json() == {"names": ["a"]}
    job_id = client.post("/v1/settings/move_all", json={"expect": ["a"]}).json()["job_id"]
    assert client.get(f"/v1/jobs/{job_id}").json()["result"] == {"count": 1}


def test_clearing_leftovers_starts_a_job(client, monkeypatch):
    monkeypatch.setattr(play_service, "job_clear", lambda launch, loc: None)
    job_id = client.post("/v1/settings/clear_leftovers").json()["job_id"]
    assert client.get(f"/v1/jobs/{job_id}").json()["state"] == "done"


def test_no_settings_route_carries_wording():
    from bayle.api.routers import settings as router

    routes = router.router.routes
    assert len(routes) == 11
    for r in routes:
        assert "said" not in r.response_model.model_fields, r.path
