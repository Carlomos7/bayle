"""The Mods page and its operations over HTTP, on a session whose Mods service is the real one: the same Session,
reached through the mods routes. Profiles are invented in the test's own folders; every request shape the OpenAPI
declares goes through JSON."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from support import mods_profile, mods_session

TOKEN = "t" * 32


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


@pytest.fixture
def client():
    calls = mods_session()
    app = create_app(ApiSettings(token=TOKEN), jobs=calls.jobs, services=calls.services)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield c


def post(client, name, body=None):
    return client.post("/v1/" + name.replace(".", "/"), json=body)


def job(client, got) -> dict:
    assert got.status_code == 200, got.text
    return client.get(f"/v1/jobs/{got.json()['job_id']}").json()


def test_the_page_snapshot_is_served_as_facts_with_its_filters(client, profile):
    body = client.get("/v1/mods", params={"profile": str(profile)}).json()
    assert body["has_profile"] and [e["name"] for e in body["facts"]["entries"]] == ["flora", "cloud", "a.dll"]
    assert body["facts"]["display"]["package"] == [0, 1] and body["scan"] is not None
    empty = client.get("/v1/mods").json()
    assert (empty["profile"], empty["has_profile"], empty["facts"]) == ("", False, None)
    assert client.get("/v1/mods", params={"nope": 1}).status_code == 422


def test_a_command_a_refusal_with_a_code_and_a_job_over_http(client, profile):
    ref = {"profile": str(profile), "index": 0}
    assert post(client, "mods.set_enabled", {**ref, "enabled": False}).json() == {"name": "flora"}
    gone = post(client, "mods.set_enabled", {**ref, "index": 99, "enabled": False})
    assert gone.status_code == 404 and gone.json()["code"] == "not_found"
    stale = post(client, "mods.set_enabled", {**ref, "enabled": True, "expect": "cloud"})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    asked = post(client, "mods.set_setting", {"profile": str(profile), "key": "start_online", "value": 1})
    assert asked.json()["code"] == "needs_confirmation" and asked.json()["details"] == {"reason": "online"}
    snap = job(client, post(client, "mods.rename", {**ref, "index": 1, "name": "cloud2"}))
    assert snap["state"] == "done" and snap["result"] == {"name": "cloud", "to": "cloud2"}


def test_a_plan_over_http_is_a_check_then_a_start_with_its_stamp(client, profile):
    ref = {"profile": str(profile)}
    plan = post(client, "mods.check_dll_folders", ref).json()
    assert plan["refusals"] == [] and plan["moves"] == 1 and len(plan["stamp"]) == 2
    assert (profile.parent / "natives" / "a.dll").is_file()  # a check writes nothing
    wrong = post(client, "mods.dll_folders", {**ref, "expect": [1, 2]})
    assert wrong.status_code == 409 and wrong.json()["code"] == "stale"
    assert job(client, post(client, "mods.dll_folders", {**ref, "expect": plan["stamp"]}))["state"] == "done"
    again = post(client, "mods.check_dll_folders", ref).json()
    assert again["refusals"] == ["Every DLL is in its own folder."]
    cannot = post(client, "mods.dll_folders", {**ref, "expect": again["stamp"]})
    assert cannot.json()["code"] == "cannot_move" and cannot.json()["details"]["refusals"]


def test_a_failed_job_carries_its_code_and_details_over_http(client, profile):
    snap = job(client, post(client, "mods.rename", {"profile": str(profile), "index": 1, "name": "flora"}))
    assert snap["state"] == "failed" and snap["error"]["code"] == "rename_failed"
    assert snap["error"]["details"] == {"name": "cloud"}


def test_a_profile_that_is_not_there_or_not_a_profile_is_not_found(client, profile, tmp_path):
    notes = tmp_path / "notes.txt"
    notes.write_text("secret", encoding="utf-8")
    for target in (tmp_path / "ghost.me3", notes):
        for name, body in (
            ("mods.text", {}),
            ("mods.versions", {}),
            ("mods.settings", {}),
            ("mods.fix_order", {}),
            ("mods.check_dll_folders", {}),
            ("mods.save_text", {"text": "a = 1\n"}),
        ):
            got = post(client, name, {"profile": str(target), **body})
            assert got.status_code == 404 and got.json()["code"] == "not_found", name
    assert notes.read_text(encoding="utf-8") == "secret"


def test_a_malformed_body_is_422_never_500(client, profile):
    ref = {"profile": str(profile)}
    for name, body in (
        ("mods.set_enabled", {**ref, "index": "zero", "enabled": True}),
        ("mods.set_enabled", {**ref, "index": 0}),
        ("mods.remove", {**ref, "index": 0}),
        ("mods.move", {**ref, "index": 0, "to": None}),
        ("mods.save_options", {**ref, "index": 0, "load_after": [{"optional": True}]}),
        ("mods.dll_folders", {**ref, "expect": "soon"}),
        ("mods.seamless", {**ref, "expect": ["move"]}),
        ("mods.trim_backups", {**ref, "expect": [1]}),
        ("mods.undo_removal", {"undo": "x"}),
        ("mods.add_existing", {**ref, "kind": "package", "paths": "a"}),
        ("mods.set_setting", {**ref, "key": "mem_patch", "value": [1]}),
        ("mods.rename_profile", {**ref, "name": 1}),
        ("mods.check_text", {"text": None}),
        ("mods.drag", {"profile": str(profile), "extra": 1, "index": 0}),
    ):
        got = post(client, name, body)
        assert got.status_code == 422 and got.json()["code"] == "invalid_params", (name, got.text)
    assert post(client, "mods.drag", None).status_code == 422
    assert (
        client.post("/v1/mods/drag", content=b"{not json", headers={"Content-Type": "application/json"}).status_code
        == 422
    )
    assert profile.read_text(encoding="utf-8").startswith("profileVersion")


def test_an_app_without_the_service_answers_with_a_code(profile):
    with TestClient(create_app(ApiSettings(token=TOKEN)), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        got = post(c, "mods.versions", {"profile": str(profile)})
        assert got.status_code == 400 and got.json()["code"] == "not_available"
