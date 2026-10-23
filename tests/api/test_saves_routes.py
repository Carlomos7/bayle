"""The Saves page and its reads and upkeep over HTTP, on a session whose Saves service is the real one. Invented saves
in the test's own folders; every request shape the OpenAPI declares goes through JSON (the removals' `expect` too)."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.saves import backups as save_backups
from bayle.saves import library as save_library
from bayle.saves import regulation as save_regulation
from bayle.services import saves as saves_service
from bayle.services.saves_page import SavesService
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore

TOKEN = "t" * 32
OLD, OTHER = b"old save " * 40, b"other save " * 40


class Env:
    def __init__(self, tmp_path, client):
        self.tmp, self.client = tmp_path, client
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.save = self.folder / "ER0000.sl2"

    def post(self, name, body=None):
        return self.client.post(f"/v1/ops/{name}", json=body or {})

    def backup(self):
        return saves_service.back_up_now(self.save, loc=self.loc)

    def copy(self, name="Mine"):
        src = self.tmp / f"src-{name}.sl2"
        src.write_bytes(OTHER)
        return save_library.add(self.folder, src, name, catalog.ELDEN_RING, action="import")

    def entries(self):
        return save_library.load(self.folder)["entries"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(save_regulation, "is_pc_save", lambda data: True)
    monkeypatch.setattr(save_library, "check_whole", lambda data, game: None)
    monkeypatch.setattr(save_library, "signed_for_account", lambda data, target, game: (data, False))
    monkeypatch.setattr(save_library, "characters", lambda path, game=None: [])
    root = tmp_path / "saves"
    folder = root / "76561198000000001"
    folder.mkdir(parents=True)
    (folder / "ER0000.sl2").write_bytes(OLD)
    loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(root)))
    info = {
        "path": folder / "ER0000.sl2",
        "name": "ER0000.sl2",
        "kind": "Standard",
        "characters": [{"slot": 1, "name": "Ann", "level": 10}],
        "findings": [],
    }
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: dict(info))
    monkeypatch.setattr(saves_service.save_analyze, "format_health_report", lambda i: f"report of {i['name']}")
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    session = Session(
        jobs, plans=PlanStore(), locations=lambda: loc, services={"saves": SavesService(jobs, lambda: loc)}
    )
    with TestClient(create_app(ApiSettings(token=TOKEN), session), base_url="http://127.0.0.1") as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        e = Env(tmp_path, c)
        e.loc = loc
        yield e


# ------------------------------------------------------------------------------------------------ group A
def test_the_page_lists_saves_library_and_backups(env):
    env.backup()
    env.copy()
    page = env.client.get("/v1/pages/saves")
    assert page.status_code == 200
    body = page.json()
    assert [i["name"] for i in body["infos"]] == ["ER0000.sl2"]
    assert [e["name"] for e in body["libraries"][str(env.folder)]["entries"]] == ["Mine"]
    assert len(body["backups"]) == 1 and body["backups"][0]["save_name"] == "ER0000.sl2"


def test_the_reads(env):
    path = str(env.save)
    assert env.post("saves.health_report", {"path": path}).json() == {"text": "report of ER0000.sl2"}
    sheet = env.post("saves.sheet", {"path": path, "slot": 1}).json()
    assert sheet["data"]["characters"][0]["name"] == "Ann" and sheet["data"]["path"] == path
    assert env.post("saves.default_name", {"path": path}).json()["text"]
    entry = env.copy()
    got = env.post("saves.copy_entry", {"folder": str(env.folder), "entry_id": entry["id"]}).json()
    assert got["name"] == "Mine" and got["changed_outside"] is False
    unusable = env.post("saves.copy_entry", {"folder": str(env.folder), "entry_id": "nope"})
    assert unusable.status_code == 400 and unusable.json()["code"] == "copy_unusable"


def test_the_folders(env):
    assert env.post("saves.folder", {"which": "saves"}).json() == {"path": str(env.folder)}
    assert env.post("saves.folder", {"which": "backups"}).json()["path"]
    assert env.post("saves.folder", {"which": "library"}).json()["path"]
    bad = env.post("saves.folder", {"which": "attic"})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_params"


# ------------------------------------------------------------------------------------------------ group B
def test_adopt_legacy_over_http(env):
    legacy = env.folder / "save-fix-backups"
    legacy.mkdir()
    (legacy / "ER0000.sl2.20260101-000000.bak").write_bytes(OLD)
    assert env.post("saves.adopt_legacy").json() == {"folders": [str(env.folder)]}
    assert not legacy.exists() or not any(legacy.iterdir())
    [row] = env.client.get("/v1/pages/saves").json()["backups"]
    assert row["action"] == "Before a save fix"


def test_keep_keep_as_and_rename(env):
    bak = env.backup()
    assert env.post("saves.keep_backup", {"backup": str(bak)}).json() == {"text": ""}
    assert env.client.get("/v1/pages/saves").json()["backups"][0]["keep"] is True
    env.post("saves.keep_backup", {"backup": str(bak), "keep": False})
    assert env.client.get("/v1/pages/saves").json()["backups"][0]["keep"] is False
    assert env.post("saves.keep_as", {"backup": str(bak), "name": "Kept"}).json() == {"text": "Kept"}
    assert bak.exists()
    [entry] = env.entries()
    got = env.post("saves.rename_copy", {"folder": str(env.folder), "entry_id": entry["id"], "name": "R"})
    assert got.json() == {"text": "R"} and env.entries()[0]["name"] == "R"


def test_removing_a_copy_is_a_check_then_a_start(env):
    entry = env.copy()
    ref = {"folder": str(env.folder), "entry_id": entry["id"]}
    name = env.post("saves.check_remove_copy", ref).json()["text"]
    assert name == "Mine" and len(env.entries()) == 1  # a check changes nothing
    assert env.post("saves.remove_copy", {**ref, "expect": name}).json() == {"text": ""}
    assert env.entries() == []
    removed = save_library.folder_for(env.folder) / save_backups.LIBRARY_REMOVED
    assert (removed / entry["file"]).read_bytes() == OTHER and (removed / f"{entry['file']}.json").is_file()


def test_removing_a_copy_that_changed_is_stale(env):
    entry = env.copy()
    ref = {"folder": str(env.folder), "entry_id": entry["id"]}
    name = env.post("saves.check_remove_copy", ref).json()["text"]
    env.post("saves.rename_copy", {**ref, "name": "Other"})
    stale = env.post("saves.remove_copy", {**ref, "expect": name})
    assert stale.status_code == 400 and stale.json()["code"] == "stale"
    assert [e["name"] for e in env.entries()] == ["Other"]


def test_deleting_a_backup_is_a_check_then_a_start_and_the_stamp_round_trips_json(env):
    bak = env.backup()
    facts = env.post("saves.check_delete_backup", {"backup": str(bak)}).json()
    assert facts["path"] == str(bak) and facts["save_name"] == "ER0000.sl2" and len(facts["stamp"]) == 2
    assert bak.exists()
    done = env.post("saves.delete_backup", {"backup": str(bak), "expect": facts["stamp"]})
    assert done.status_code == 200 and done.json() == {"text": ""} and not bak.exists()


def test_deleting_a_rewritten_backup_is_stale(env):
    bak = env.backup()
    stamp = env.post("saves.check_delete_backup", {"backup": str(bak)}).json()["stamp"]
    bak.write_bytes(OLD + b"more")
    stale = env.post("saves.delete_backup", {"backup": str(bak), "expect": stamp})
    assert stale.status_code == 400 and stale.json()["code"] == "stale" and bak.exists()


def test_finish_stranded_over_http(env, monkeypatch):
    entry = env.copy()
    ref = {"folder": str(env.folder), "entry_id": entry["id"]}

    def boom(*a, **k):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(save_library, "_save", boom)
        m.setattr(save_library, "_undo_remove", lambda *a: None)
        assert env.post("saves.remove_copy", {**ref, "expect": "Mine"}).json()["code"] == "failed"
    assert env.post("saves.finish_stranded", {**ref, "restore": True}).json() == {"warning": ""}
    assert (save_library.folder_for(env.folder) / entry["file"]).read_bytes() == OTHER
    again = env.post("saves.finish_stranded", {**ref, "restore": True})  # in place now: refused, nothing changed
    assert again.status_code == 400 and again.json()["code"] == "failed"


def test_not_found_is_a_404_and_touches_nothing(env):
    stray = env.tmp / "stray.bak"
    stray.write_bytes(b"x")
    for target in (stray, env.save):
        ref = {"backup": str(target)}
        for name, body in (
            ("saves.check_delete_backup", ref),
            ("saves.delete_backup", {**ref, "expect": [1, 1.0]}),
            ("saves.keep_backup", ref),
            ("saves.keep_as", {**ref, "name": "X"}),
        ):
            got = env.post(name, body)
            assert got.status_code == 404 and got.json()["code"] == "not_found", name
    entry = env.copy()
    for folder, entry_id in ((str(env.folder), "nope"), (str(env.tmp / "elsewhere"), entry["id"])):
        ref = {"folder": folder, "entry_id": entry_id}
        for name, body in (
            ("saves.check_remove_copy", ref),
            ("saves.remove_copy", {**ref, "expect": "Mine"}),
            ("saves.rename_copy", {**ref, "name": "X"}),
        ):
            got = env.post(name, body)
            assert got.status_code == 404 and got.json()["code"] == "not_found", name
    assert stray.read_bytes() == b"x" and env.save.read_bytes() == OLD and list(env.folder.glob("*.json")) == []
    assert [e["name"] for e in env.entries()] == ["Mine"]


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("saves.keep_backup", {}),
        ("saves.keep_backup", {"backup": "x", "keep": "maybe"}),
        ("saves.keep_as", {"backup": "x"}),
        ("saves.rename_copy", {"folder": "f", "entry_id": "i"}),
        ("saves.check_remove_copy", {"folder": "f"}),
        ("saves.remove_copy", {"folder": "f", "entry_id": "i"}),
        ("saves.remove_copy", {"folder": "f", "entry_id": "i", "expect": 5}),
        ("saves.check_delete_backup", {}),
        ("saves.delete_backup", {"backup": "x"}),
        ("saves.delete_backup", {"backup": "x", "expect": [1]}),
        ("saves.delete_backup", {"backup": "x", "expect": "stamp"}),
        ("saves.finish_stranded", {"folder": "f", "entry_id": "i"}),
        ("saves.sheet", {"path": "p", "slot": "one"}),
    ],
)
def test_bad_params_are_422_not_500(env, name, body):
    got = env.post(name, body)
    assert got.status_code == 422 and got.json()["code"] == "invalid_params"
