"""The Mod Configs page and its operations over HTTP, on a session whose Mod configs service is the real one. A
profile and mods invented in the test's own folders; every request shape the OpenAPI declares goes through JSON."""

import pytest
from fastapi.testclient import TestClient
from test_overhaul_install import PROFILE, World, mixed_mod

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.services.mod_configs import ModConfigsService
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore

TOKEN = "t" * 32


class Env:
    def __init__(self, world: World, client: TestClient):
        self.world, self.client = world, client
        self.profile = str(world.profile)
        self.ini = world.base / "natives/SeamlessCoop/ersc_settings.ini"
        self.ini.write_text("[PASSWORD]\ncooppassword = room\n[GAMEPLAY]\nallow_invaders = 1\n", encoding="utf-8")

    def post(self, name, body=None):
        return self.client.post(f"/v1/ops/{name}", json=body)

    def job(self, got) -> dict:
        assert got.status_code == 200, got.text
        return self.client.get(f"/v1/jobs/{got.json()['job_id']}").json()


@pytest.fixture
def env(tmp_path, monkeypatch):
    world = World(tmp_path, monkeypatch)
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    service = ModConfigsService(jobs, lambda: world.loc)
    session = Session(jobs, plans=PlanStore(), locations=lambda: world.loc, services={"mod_configs": service})
    with TestClient(create_app(ApiSettings(token=TOKEN), session), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield Env(world, c)


def test_the_page_lists_the_mods_with_settings_files(env):
    page = env.client.get("/v1/pages/mod_configs", params={"profile": env.profile})
    assert page.status_code == 200
    body = page.json()
    assert body["profile"] == env.profile and body["nodes"][0]["kind"] == "seamless"
    assert body["nodes"][0]["files"][0]["path"] == str(env.ini)
    assert env.client.get("/v1/pages/mod_configs").json()["nodes"] == []  # no profile
    assert env.client.get("/v1/pages/mod_configs", params={"nope": 1}).status_code == 422


def test_open_stamp_and_a_stale_save_over_http(env):
    p, path = env.profile, str(env.ini)
    read = env.post("mod_configs.open", {"profile": p, "path": path, "seamless": True}).json()
    assert read["text"].startswith("[PASSWORD]") and read["seamless"]["password"] == "room"
    assert env.post("mod_configs.stamp", {"profile": p, "path": path}).json()["stamp"] == read["stamp"]
    body = {"profile": p, "path": path, "expect": read["sha"], "kind": "seamless"}
    saved = env.post("mod_configs.save", {**body, "edits": [{"key": "cooppassword", "value": "new"}]})
    assert saved.json() == {"name": "ersc_settings.ini", "saved": 1, "missing": []}
    stale = env.post("mod_configs.save", {**body, "edits": [{"key": "cooppassword", "value": "newer"}]})
    assert stale.status_code == 400 and stale.json()["code"] == "stale"
    assert "cooppassword = new\n" in env.ini.read_text(encoding="utf-8")
    empty = env.post("mod_configs.save", {**body, "edits": [{"key": "cooppassword", "value": " "}]})
    assert empty.json()["code"] == "password_empty"


def test_a_file_outside_the_tree_is_not_found_and_a_malformed_body_is_422(env, tmp_path):
    p = env.profile
    secret = tmp_path / "secret.ini"
    secret.write_text("a = 1\n", encoding="utf-8")
    for name, body in (
        ("mod_configs.open", {"profile": p, "path": str(secret)}),
        ("mod_configs.stamp", {"profile": p, "path": str(secret)}),
        ("mod_configs.save", {"profile": p, "path": str(secret), "expect": "x", "kind": "text", "text": "b"}),
        ("mod_configs.share", {"profile": p, "ini": str(secret)}),
        ("mod_configs.export_share", {"profile": p, "ini": str(secret), "to": str(tmp_path / "o.ini")}),
        ("mod_configs.attach", {"profile": p, "target": str(secret), "file": str(secret)}),
    ):
        got = env.post(name, body)
        assert got.status_code == 404 and got.json()["code"] == "not_found", name
    assert secret.read_text(encoding="utf-8") == "a = 1\n" and not (tmp_path / "o.ini").exists()
    for name, body in (
        ("mod_configs.open", {"profile": p}),  # no path
        ("mod_configs.save", {"profile": p, "path": "x", "expect": "e", "kind": "nonsense"}),
        ("mod_configs.stamp", {"profile": p, "path": 3}),
        ("mod_configs.paste", {"profile": p, "ini": "x", "text": "t", "expect": [1]}),
        ("mod_configs.install_setup", {"profile": p, "folder": "x", "name": "n", "form": {"natives": "no"}}),
        ("mod_configs.open", {"profile": p, "path": "x", "extra": 1}),
    ):
        got = env.post(name, body)
        assert got.status_code == 422 and got.json()["code"] == "invalid_params", name
    assert env.client.post("/v1/ops/mod_configs.open", content=b"{not json").status_code == 422


def test_sharing_and_pasting_over_http(env, tmp_path):
    p, ini = env.profile, str(env.ini)
    text = env.post("mod_configs.share", {"profile": p, "ini": ini}).json()["text"]
    assert "cooppassword = room" in text
    out = tmp_path / "friend.ini"
    done = env.job(env.post("mod_configs.export_share", {"profile": p, "ini": ini, "to": str(out)}))
    assert done["state"] == "done" and done["result"] == {"path": str(out)}
    assert out.read_text(encoding="utf-8") == text
    failed = env.job(env.post("mod_configs.export_share", {"profile": p, "ini": ini, "to": str(tmp_path)}))
    assert failed["state"] == "failed" and failed["error"]["code"] == "not_saved"
    body = {"profile": p, "ini": ini, "text": "allow_invaders = 0\nmade_up = 1\n"}
    plan = env.post("mod_configs.check_paste", body).json()
    assert plan["changes"] == {"allow_invaders": ["1", "0"]} and plan["unknown"] == ["made_up"]
    assert env.post("mod_configs.paste", {**body, "expect": plan["stamp"]}).json() == {"saved": 1}
    again = env.post("mod_configs.check_paste", body)
    assert again.json()["code"] == "nothing_to_change" and again.json()["details"] == {"unknown": ["made_up"]}
    nothing = env.post("mod_configs.check_paste", {**body, "text": "no settings here"})
    assert nothing.json()["code"] == "not_settings"
    stale = env.post("mod_configs.paste", {**body, "text": "allow_invaders = 1\n", "expect": plan["stamp"]})
    assert stale.json()["code"] == "stale"


def test_the_overhaul_plans_over_http(env):
    world = env.world
    inside = world.base / "Mixed Mod"
    mixed_mod(world).rename(inside)
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = 'mixed'\npath = 'Mixed Mod'\n", encoding="utf-8")
    p = env.profile
    mods = env.post("mod_configs.setup_candidates", {"profile": p}).json()["mods"]
    assert str(inside) in [m["folder"] for m in mods]
    form = env.post("mod_configs.overhaul_form", {"profile": p, "folder": str(inside), "name": "Mixed Mod"}).json()
    assert form["new"] and form["values"]["natives"]
    body = {
        "profile": p,
        "folder": str(inside),
        "name": "Mixed Mod",
        "form": {k: form["values"][k] for k in ("natives", "files", "tables")},
    }
    plan = env.post("mod_configs.check_install_setup", body).json()
    assert plan["refusals"] == [] and plan["lines"]
    stale = env.post("mod_configs.install_setup", {**body, "expect": [1, 2]})
    assert stale.json()["code"] == "stale"
    done = env.job(env.post("mod_configs.install_setup", {**body, "expect": plan["stamp"]}))
    assert done["state"] == "done" and done["result"]["name"]
    off = env.post("mod_configs.check_turn_off", {"profile": p}).json()
    assert off["refusals"] == [] and off["label"]
    assert env.job(env.post("mod_configs.turn_off", {"profile": p, "expect": off["stamp"]}))["state"] == "done"
    gone = env.post("mod_configs.check_turn_off", {"profile": p})
    assert gone.status_code == 400 and gone.json()["code"] == "cannot_turn_off"
