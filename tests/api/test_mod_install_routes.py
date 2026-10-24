"""The install, overhaul and Library operations over HTTP, on a session whose services are the real ones. Profiles,
downloads and the Library are invented in the test's own folders; every request shape goes through JSON."""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.platform import trash
from bayle.services.mod_install import ModInstallService
from bayle.services.shared_mods import ModLibraryService
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore

TOKEN = "t" * 32
HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


def make_profile(root: Path, name: str, mods: dict[str, bytes]) -> Path:
    entries = ""
    for mod, data in mods.items():
        (root / name / "packages" / mod / "parts").mkdir(parents=True)
        (root / name / "packages" / mod / "parts" / f"{mod}.dcx").write_bytes(data)
        entries += f"\n[[packages]]\nid = '{mod}'\npath = 'packages/{mod}'\n"
    profile = root / name / f"{name}.me3"
    profile.write_bytes((HEAD + entries).encode())
    return profile


class Env:
    def __init__(self, client: TestClient, a: Path, b: Path, tmp: Path):
        self.client, self.a, self.b, self.tmp = client, a, b, tmp

    def post(self, name, body=None):
        return self.client.post(f"/v1/ops/{name}", json=body)

    def job(self, got) -> dict:
        assert got.status_code == 200, got.text
        return self.client.get(f"/v1/jobs/{got.json()['job_id']}").json()


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "profiles"
    root = home / "b-eldenring"
    a = make_profile(root, "a", {"grass": b"same"})
    b = make_profile(root, "b", {"grass": b"same"})
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    monkeypatch.setattr(trash, "exists", lambda r: False)
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    services = {
        "mod_install": ModInstallService(jobs, lambda: loc),
        "mod_library": ModLibraryService(jobs, lambda: loc),
    }
    session = Session(jobs, plans=PlanStore(), locations=lambda: loc, services=services)
    with TestClient(create_app(ApiSettings(token=TOKEN), session), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        yield Env(c, a, b, tmp_path)


def test_a_download_is_opened_planned_again_and_installed_over_http(env):
    src = env.tmp / "dl" / "sky"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "sky.partsbnd.dcx").write_bytes(b"s")
    sources = env.post("mods.install_sources", {"paths": [str(src), str(env.tmp / "notes.txt")]}).json()
    assert sources == {"usable": [str(src)], "skipped": [str(env.tmp / "notes.txt")]}
    opened = env.post("mods.install_open", {"profile": str(env.a), "source": str(src)})
    assert opened.status_code == 200
    got = opened.json()
    assert got["plan"]["name"] == "sky" and got["plan"]["option"] == "plain" and got["stamp"]
    ref = {"install_id": got["install_id"]}
    assert env.post("mods.install_replan", {**ref, "name": "sky2", "id": "sky2"}).json()["plan"]["name"] == "sky2"
    choices = {"name": "sky2", "id": "sky2"}
    bad = env.post("mods.install_finish", {**ref, "choices": {**choices, "name": " "}, "expect": got["stamp"]})
    assert bad.json()["code"] == "not_ready"
    assert bad.json()["details"]["reason"] == "name_blank"
    done = env.job(env.post("mods.install_finish", {**ref, "choices": choices, "expect": got["stamp"]}))
    assert done["state"] == "done" and done["result"] == {"name": "sky2", "overhaul": False, "update": False}
    assert "sky2" in env.a.read_text(encoding="utf-8")
    assert env.post("mods.install_close", ref).json()["code"] == "unknown_install"


def test_a_stale_install_or_a_missing_download_is_a_coded_refusal(env):
    src = env.tmp / "dl" / "sky"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "sky.partsbnd.dcx").write_bytes(b"s")
    missing = env.post("mods.install_open", {"profile": str(env.a), "source": str(env.tmp / "nope.zip")})
    assert missing.status_code == 404 and missing.json()["code"] == "not_found"
    got = env.post("mods.install_open", {"profile": str(env.a), "source": str(src)}).json()
    env.a.write_bytes(env.a.read_bytes() + b"\n# edited\n")
    stale = env.post(
        "mods.install_finish",
        {"install_id": got["install_id"], "choices": {"name": "sky", "id": "sky"}, "expect": got["stamp"]},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    assert env.post("mods.install_close", {"install_id": got["install_id"]}).status_code == 200  # still open until now


def test_the_library_is_shared_and_listed_over_http(env):
    ref = {"profile": str(env.a), "index": 0}
    plan = env.post("mods.check_share", ref).json()
    assert plan["name"] == "grass"
    stale = env.post("mods.share", {**ref, "expect": [1, 2]})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    done = env.job(env.post("mods.share", {**ref, "expect": plan["stamp"]}))
    assert done["state"] == "done"
    rows = env.post("mods.library", {"profile": str(env.a)}).json()["mods"]
    assert [m["name"] for m in rows] == ["grass"] and rows[0]["versions"][0]["used_by"] == ["a"]
    offer = env.post("mods.library_use_choices", ref).json()
    assert [p["name"] for p in offer["profiles"]] == ["b"] and offer["profiles"][0]["has_copy"]
    linked = env.job(env.post("mods.library_use", {**ref, "targets": [offer["profiles"][0]["profile"]]}))
    assert linked["state"] == "done"
    other = env.post("mods.library_use", {**ref, "targets": [str(env.tmp / "elsewhere.me3")]})
    assert other.status_code == 404 and other.json()["code"] == "not_found"
    assert env.post("mods.check_remove_unused", {}).json()["code"] == "nothing_unused"


def test_a_profile_without_an_overhaul_has_nothing_to_remove_or_take_over(env):
    ref = {"profile": str(env.a)}
    for name in ("mods.overhaul_remove_choices", "mods.takeover_choices"):
        assert env.post(name, ref).json()["code"] == "no_overhaul", name
    assert env.post("mods.check_overhaul_remove", ref).json()["code"] == "no_overhaul"
    assert env.post("mods.check_overhaul_install", {**ref, "folder": str(env.tmp / "gone")}).status_code == 404
    left = env.post("mods.leftovers", ref).json()
    assert left == {"folders": [], "backups": []}
    nothing = env.post("mods.leftovers_clean", {**ref, "paths": []})
    assert nothing.json()["code"] == "nothing_chosen"
    outside = env.post("mods.leftovers_clean", {**ref, "paths": [str(env.tmp)]})
    assert outside.status_code == 404 and outside.json()["code"] == "not_found"


def test_a_malformed_body_is_422_never_500(env):
    p = str(env.a)
    for name, body in (
        ("mods.install_sources", {"paths": "x"}),
        ("mods.install_open", {"profile": p}),
        ("mods.install_replan", {"install_id": "i1"}),
        ("mods.install_preview", {"install_id": "i1", "name": "n", "setup": {"natives": "no"}}),
        ("mods.install_finish", {"install_id": "i1", "choices": {"name": "n", "exclude": "no"}, "expect": None}),
        ("mods.install_finish", {"install_id": "i1", "choices": {"name": "n"}}),
        ("mods.check_share", {"profile": p, "index": "zero"}),
        ("mods.share", {"profile": p, "index": 0, "expect": [1]}),
        ("mods.library_use", {"profile": p, "index": 0, "targets": 3}),
        ("mods.remove_unused", {"expect": "x"}),
        ("mods.check_overhaul_install", {"profile": p}),
        ("mods.overhaul_remove", {"profile": p, "chosen": ["a"], "expect": None}),
        ("mods.takeover", {"profile": p, "extra": 1, "expect": None}),
        ("mods.leftovers_clean", {"profile": p, "paths": [1]}),
    ):
        got = env.post(name, body)
        assert got.status_code == 422 and got.json()["code"] == "invalid_params", name
    assert env.client.post("/v1/ops/mods.install_open", content=b"{not json").status_code == 422
