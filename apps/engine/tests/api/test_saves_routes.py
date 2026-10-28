"""The Saves page and its reads and upkeep over HTTP, on a session whose Saves service is the real one. Invented saves
in the test's own folders; every request shape the OpenAPI declares goes through JSON (the removals' `expect` too)."""

import pytest
from fastapi.testclient import TestClient

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings
from bayle.modules.games import catalog
from bayle.modules.games.locate import Locations, Overrides
from bayle.modules.saves import backups as save_backups
from bayle.modules.saves import fix as save_fix
from bayle.modules.saves import library as save_library
from bayle.modules.saves import regulation as save_regulation
from bayle.modules.saves import service as saves_service
from bayle.modules.saves import transfer as save_transfer
from bayle.modules.saves.saves_page import SavesService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager

TOKEN = "t" * 32
OLD, OTHER = b"old save " * 40, b"other save " * 40


class Env:
    def __init__(self, tmp_path, client):
        self.tmp, self.client = tmp_path, client
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.save = self.folder / "ER0000.sl2"

    def post(self, name, body=None):
        return self.client.post(f"/v1/{name.replace('.', '/')}", json=body or {})

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
    services = {"saves": SavesService(jobs, lambda: loc)}
    with TestClient(
        create_app(ApiSettings(token=TOKEN), jobs=jobs, services=services), base_url="http://127.0.0.1"
    ) as c:
        c.headers.update({"Authorization": f"Bearer {TOKEN}"})
        e = Env(tmp_path, c)
        e.loc = loc
        yield e


# ------------------------------------------------------------------------------------------------ group A
def test_the_page_lists_saves_library_and_backups(env):
    env.backup()
    env.copy()
    page = env.client.get("/v1/saves")
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
    [row] = env.client.get("/v1/saves").json()["backups"]
    assert row["action"] == "Before a save fix"


def test_keep_keep_as_and_rename(env):
    bak = env.backup()
    assert env.post("saves.keep_backup", {"backup": str(bak)}).json() == {"text": ""}
    assert env.client.get("/v1/saves").json()["backups"][0]["keep"] is True
    env.post("saves.keep_backup", {"backup": str(bak), "keep": False})
    assert env.client.get("/v1/saves").json()["backups"][0]["keep"] is False
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
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
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
    assert stale.status_code == 409 and stale.json()["code"] == "stale" and bak.exists()


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


# ------------------------------------------------------------------------------------------------ groups C and D
def job_result(env, started):
    """A started job's id from the response (200), and what GET /v1/jobs/{id} says of it."""
    assert started.status_code == 200, started.text
    body = started.json()
    assert list(body) == ["job_id"]
    job = env.client.get(f"/v1/jobs/{body['job_id']}")
    assert job.status_code == 200
    return job.json()


def test_save_copy_returns_a_job_id_and_the_job_holds_the_result(env):
    job = job_result(env, env.post("saves.save_copy", {"path": str(env.save), "name": "Mine"}))
    [entry] = env.entries()
    assert job["state"] == "done" and job["error"] is None
    assert job["result"] == {"source": str(env.save), "entry_id": entry["id"], "name": "Mine"}
    assert env.save.read_bytes() == OLD


def test_back_up_returns_a_job_id_and_the_job_holds_the_result(env):
    job = job_result(env, env.post("saves.back_up", {"everything": True}))
    assert job["state"] == "done" and job["result"]["saves"] == [str(env.save)]
    [bak] = job["result"]["backups"]
    assert open(bak, "rb").read() == OLD


def test_import_returns_a_job_id_and_the_job_holds_imported_and_failed(env):
    good, bad = env.tmp / "good.sl2", env.tmp / "bad.sl2"
    good.write_bytes(OTHER)  # bad is never written: two files, so a missing one is a listed failure, not a refusal
    job = job_result(env, env.post("saves.import_files", {"files": [str(good), str(bad)]}))
    assert job["state"] == "done"
    assert [i["file"] for i in job["result"]["imported"]] == [str(good)]
    assert job["result"]["failed"] == [{"file": str(bad), "code": "not_found"}]
    assert [e["name"] for e in env.entries()] == [save_library.default_name(good, catalog.ELDEN_RING)]


def test_a_failed_job_reports_its_code_over_http(env, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(save_library, "_save", boom)
    job = job_result(env, env.post("saves.save_copy", {"path": str(env.save), "name": "Mine"}))
    assert job["state"] == "failed" and job["error"]["code"] == "failed" and env.entries() == []


def test_unlisted_and_missing_things_are_404_and_touch_nothing(env):
    stray = env.tmp / "stray.sl2"
    stray.write_bytes(OTHER)
    for name, body in (
        ("saves.back_up", {"paths": [str(stray)]}),
        ("saves.save_copy", {"path": str(stray), "name": "X"}),
        ("saves.import_files", {"files": [str(env.tmp / "nope.sl2")]}),
    ):
        got = env.post(name, body)
        assert got.status_code == 404 and got.json()["code"] == "not_found", name
    assert env.entries() == [] and stray.read_bytes() == OTHER and env.save.read_bytes() == OLD


def test_bad_names_and_nothing_to_do_are_refused_with_their_codes(env):
    cases = (
        ("saves.save_copy", {"path": str(env.save), "name": "   "}, "invalid_name"),
        ("saves.import_files", {"files": [str(env.save)], "name": ""}, "invalid_name"),
        ("saves.import_files", {"files": [], "name": None}, "invalid_params"),
        ("saves.back_up", {}, "invalid_params"),
    )
    for name, body, code in cases:
        got = env.post(name, body)
        assert got.status_code in (400, 422) and got.json()["code"] == code, name
    assert env.entries() == []


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("saves.back_up", {"paths": "x"}),
        ("saves.back_up", {"paths": [1]}),
        ("saves.back_up", {"everything": "maybe"}),
        ("saves.save_copy", {}),
        ("saves.save_copy", {"path": "p"}),
        ("saves.save_copy", {"path": 5, "name": "X"}),
        ("saves.save_copy", {"path": "p", "name": ["X"]}),
        ("saves.import_files", {}),
        ("saves.import_files", {"files": "a"}),
        ("saves.import_files", {"files": [1]}),
        ("saves.import_files", {"files": ["a"], "name": 5}),
    ],
)
def test_bad_params_for_back_up_save_copy_and_import_are_422_not_500(env, name, body):
    got = env.post(name, body)
    assert got.status_code == 422 and got.json()["code"] == "invalid_params"
    assert env.entries() == []


# ------------------------------------------------------------------------------------------------ group E: the writes
NEW = b"new save " * 40


def start(env, name, body):
    """A write's start over HTTP: 200 with a job id; the finished job's result."""
    return job_result(env, env.post(name, body))["result"]


def test_restore_is_a_check_then_a_start_and_undo_takes_it_back(env):
    bak = env.backup()
    env.save.write_bytes(NEW)
    ref = {"backup": str(bak), "target": str(env.save)}
    checked = env.post("saves.check_restore_backup", ref).json()
    assert checked["backup"]["save_name"] == "ER0000.sl2" and checked["target"] == str(env.save)
    assert len(checked["stamp"]) == 2 and env.save.read_bytes() == NEW  # a check changes nothing
    result = start(env, "saves.restore_backup", {**ref, "expect": checked["stamp"]})
    assert env.save.read_bytes() == OLD and result["file"] == "ER0000.sl2" and result["save"] == str(env.save)
    assert result["undo"] == {
        "type": "save-restore",
        "save": str(env.save),
        "backup": result["backup"],
        "name": "ER0000.sl2",
    }
    undone = start(env, "saves.undo_change", {"save": result["save"], "backup": result["backup"]})
    assert undone == {"file": "ER0000.sl2"} and env.save.read_bytes() == NEW


def test_replace_from_file_and_from_library_are_a_check_then_a_start(env):
    picked = env.tmp / "picked.co2"
    picked.write_bytes(OTHER)
    ref = {"source": str(picked), "target": str(env.save)}
    checked = env.post("saves.check_replace_from_file", ref).json()
    assert checked["label"] == "picked.co2" and checked["from_library"] is False and checked["signed"] is False
    got = start(env, "saves.replace_from_file", {**ref, "expect": checked["stamp"]})
    assert env.save.read_bytes() == OTHER and got["source"] == "picked.co2" and got["backup"]
    entry = env.copy("Older")
    env.save.write_bytes(OLD)
    ref = {"folder": str(env.folder), "entry_id": entry["id"], "target": str(env.save)}
    checked = env.post("saves.check_replace_from_library", ref).json()
    assert checked["label"] == "Older" and checked["from_library"] is True and checked["changed_outside"] is False
    got = start(env, "saves.replace_from_library", {**ref, "expect": checked["stamp"]})
    assert env.save.read_bytes() == OTHER and got["source"] == "Older"


def test_repair_copy_character_and_post_session_repair_over_http(env, monkeypatch):
    def fix(path, *, loc):
        bak = save_fix.backup(path, {"action": "Before fixing checksums"})
        path.write_bytes(NEW)
        return {"backup": bak}

    monkeypatch.setattr(saves_service, "fix_checksums", fix)
    ref = {"path": str(env.save), "keys": [["checksum", 1]]}
    checked = env.post("saves.check_repair", ref).json()
    assert (
        checked["info"]["name"] == "ER0000.sl2" and checked["keys"] == [["checksum", 1]] and len(checked["stamp"]) == 1
    )
    got = start(env, "saves.repair", {**ref, "expect": checked["stamp"]})
    assert env.save.read_bytes() == NEW and got["file"] == "ER0000.sl2" and got["backup"] and got["undo"]

    plan = {"character": {"name": "Ann", "level": 10}, "replaces": None, "steam_id_changes": False}
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda *a: plan)
    monkeypatch.setattr(
        save_transfer,
        "copy_character",
        lambda src, ss, dst, ds: {**plan, "backup": save_fix.backup(dst, {"action": "Before copying a character in"})},
    )
    ref = {"source": str(env.save), "src_slot": 1, "target": str(env.save), "dst_slot": 2}
    checked = env.post("saves.check_copy_character", ref).json()
    assert checked["plan"]["character"]["name"] == "Ann" and checked["same_file"] is True
    got = start(env, "saves.copy_character", {**ref, "expect": checked["stamp"]})
    assert (got["character"], got["slot"], got["file"]) == ("Ann", 2, "ER0000.sl2") and got["undo"]

    ran = []
    monkeypatch.setattr("bayle.modules.saves.repair.repair_all", lambda loc: ran.append(loc))
    assert start(env, "saves.post_session_repair", {}) == {"save": None, "backup": None, "undo": None} and ran == [
        env.loc
    ]


def test_a_character_may_be_copied_out_of_a_backup(env, monkeypatch):
    plan = {"character": {"name": "Ann", "level": 10}, "replaces": None, "steam_id_changes": False}
    seen = []
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda src, *a: seen.append(src) or plan)
    bak = env.backup()
    ref = {"source": str(bak), "src_slot": 1, "target": str(env.save), "dst_slot": 2}
    checked = env.post("saves.check_copy_character", ref)
    assert checked.status_code == 200 and checked.json()["same_file"] is False and seen == [bak]


def test_a_write_over_a_changed_file_is_stale_409_and_writes_nothing(env):
    bak = env.backup()
    ref = {"backup": str(bak), "target": str(env.save)}
    stamp = env.post("saves.check_restore_backup", ref).json()["stamp"]
    env.save.write_bytes(NEW)
    stale = env.post("saves.restore_backup", {**ref, "expect": stamp})
    assert stale.status_code == 409 and stale.json()["code"] == "stale"
    assert env.save.read_bytes() == NEW


def test_writes_to_things_the_page_does_not_list_are_404(env):
    stray = env.tmp / "stray.sl2"
    stray.write_bytes(OTHER)
    bak = env.backup()
    cases = (
        ("saves.check_restore_backup", {"backup": str(stray), "target": str(env.save)}),
        ("saves.check_replace_from_file", {"source": str(stray), "target": str(stray)}),
        ("saves.check_replace_from_library", {"folder": str(env.folder), "entry_id": "nope", "target": str(env.save)}),
        ("saves.check_repair", {"path": str(stray), "keys": [["checksum", 1]]}),
        ("saves.check_copy_character", {"source": str(stray), "src_slot": 1, "target": str(env.save), "dst_slot": 2}),
        ("saves.undo_change", {"save": str(stray), "backup": str(bak)}),
    )
    for name, body in cases:
        got = env.post(name, body)
        assert got.status_code == 404 and got.json()["code"] == "not_found", name
    assert env.save.read_bytes() == OLD and stray.read_bytes() == OTHER


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("saves.check_restore_backup", {"backup": "b"}),
        ("saves.restore_backup", {"backup": "b", "target": "t"}),
        ("saves.restore_backup", {"backup": "b", "target": "t", "expect": "stamp"}),
        ("saves.restore_backup", {"backup": "b", "target": "t", "expect": [[1]]}),
        ("saves.replace_from_file", {"source": "s", "target": "t"}),
        ("saves.replace_from_library", {"folder": "f", "entry_id": "i", "target": "t"}),
        ("saves.check_repair", {"path": "p", "keys": "checksum"}),
        ("saves.repair", {"path": "p", "keys": [["checksum", 1]]}),
        ("saves.copy_character", {"source": "s", "src_slot": 1, "target": "t", "dst_slot": 2}),
        ("saves.check_copy_character", {"source": "s", "src_slot": "one", "target": "t", "dst_slot": 2}),
        ("saves.undo_change", {"save": "s"}),
    ],
)
def test_bad_params_for_the_writes_are_422_not_500(env, name, body):
    got = env.post(name, body)
    assert got.status_code == 422 and got.json()["code"] == "invalid_params"


def test_a_write_while_the_game_runs_is_busy_409_and_writes_nothing(env):
    bak = env.backup()
    ref = {"backup": str(bak), "target": str(env.save)}
    stamp = env.post("saves.check_restore_backup", ref).json()["stamp"]
    env.client.app.state.jobs._game_running = lambda: True
    got = env.post("saves.restore_backup", {**ref, "expect": stamp})
    assert got.status_code == 409 and got.json()["details"]["reason"] == "game_running"
    assert env.save.read_bytes() == OLD
