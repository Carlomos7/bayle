"""The Saves operations through Session.run / snapshot / answer: no Qt, no window. Saves are invented files in the
test's own folders; the game is never running unless a test says so. The tests that matter most prove that every write
to a live save takes the SAME backup as before (the file as it was, with its note) and returns the undo record."""

import pytest

from bayle.config.settings import data_dir
from bayle.errors import OperationError
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.platform import logging as run_logging
from bayle.saves import fix as save_fix
from bayle.saves import library as save_library
from bayle.saves import regulation as save_regulation
from bayle.saves import transfer as save_transfer
from bayle.services import saves as saves_service
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm, Refusal
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanError, PlanStore

OLD, NEW, OTHER = b"old save " * 40, b"new save " * 40, b"other save " * 40


def inline(run, name=None):
    run()


class World:
    """One account with one Standard save in a temporary saves folder."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.folder.mkdir(parents=True)
        self.save = self.folder / "ER0000.sl2"
        self.save.write_bytes(OLD)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(self.root)))

    def session(self, **jobs) -> Session:
        return Session(JobManager(EventBus(), spawn=inline, **jobs), plans=PlanStore(), locations=lambda: self.loc)

    def backups(self):
        return saves_service.list_backups(loc=self.loc)


@pytest.fixture
def world(tmp_path, monkeypatch):
    # an invented file is not a whole save: the checks that read a save's layout accept it, and its signing is left alone
    monkeypatch.setattr(save_regulation, "is_pc_save", lambda data: True)
    monkeypatch.setattr(save_library, "check_whole", lambda data, game: None)
    monkeypatch.setattr(save_library, "signed_for_account", lambda data, target, game: (data, False))
    monkeypatch.setattr(save_library, "characters", lambda path, game=None: [])
    return World(tmp_path)


def finished(session: Session, job_id: str):
    snap = session.jobs.get(job_id)
    assert snap is not None and snap.state == "done", snap
    return snap


def ask_and_run(session: Session, name: str, params: dict):
    """A plan operation, answered yes: returns (the plan, the finished job)."""
    plan = session.run(name, params)
    assert not isinstance(plan, Refusal), plan
    return plan, finished(session, session.answer(plan.id, {"ok": True}))


def assert_took_the_backup(world: World, snap, before: bytes, action: str):
    """The write returned the backup of the file as it was, noted with the action, and the undo record for it."""
    result = snap.result
    backup = result["backup"]
    assert backup and open(backup, "rb").read() == before
    assert any(
        b["path"].name == backup.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] and b["action"] == action
        for b in world.backups()
    )
    record = {"type": "save-restore", "save": str(world.save), "backup": backup, "name": world.save.name}
    assert result["undo"] == record
    assert run_logging.read_jobs_from(None)[0]["undo"] == record  # the jobs index holds it too (Activity's Undo)


# ---------------------------------------------------------------------------------------------------- reads
def _tree(*roots):
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for r in roots for p in [r, *r.rglob("*")]}


def test_reading_the_page_writes_nothing(world, monkeypatch):
    world.session().run("saves.back_up", {"paths": [str(world.save)]})  # a backup to list
    info = {"path": world.save, "name": world.save.name, "kind": "Standard", "characters": [], "findings": []}
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: dict(info))
    s = world.session()
    before = _tree(world.root, data_dir())
    state = s.snapshot("saves")
    s.run("saves.default_name", {"path": str(world.save)})
    assert [i["name"] for i in state.infos] == ["ER0000.sl2"] and len(state.backups) == 1
    assert _tree(world.root, data_dir()) == before


def test_health_report_and_sheet_read_the_save(world, monkeypatch):
    info = {
        "path": world.save,
        "name": world.save.name,
        "characters": [
            {"slot": 1, "name": "Ann", "level": 10, "runes": 5, "hp": 300, "stats": {}, "ok": True},
        ],
        "findings": [],
        "vanilla_plan": [],
        "loading_plan": [],
        "checksum_fixes": {"slots": [], "ud10": False},
    }
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: info)
    monkeypatch.setattr(saves_service.save_analyze, "format_health_report", lambda i: f"report of {i['name']}")
    s = world.session()
    assert s.run("saves.health_report", {"path": str(world.save)}).text == "report of ER0000.sl2"
    assert s.run("saves.sheet", {"path": str(world.save), "slot": 1}).data["name"] == "Ann"
    assert s.run("saves.sheet", {"path": str(world.save), "slot": 9}).data == {}


def test_adopt_legacy_is_a_command_and_the_folders_command_makes_them(world):
    s = world.session()
    assert s.run("saves.adopt_legacy").folders == [str(world.folder)]
    assert s.run("saves.folder", {"which": "saves"}).path == str(world.folder)
    backups = s.run("saves.folder", {"which": "backups"}).path
    assert backups and "backups" in backups.lower()
    assert s.run("saves.folder", {"which": "library"}).path


# ---------------------------------------------------------------------------------------------------- writes
def test_back_up_one_and_all_take_a_backup_and_say_so(world):
    s = world.session()
    one = finished(s, s.run("saves.back_up", {"paths": [str(world.save)]}))
    assert one.result["text"].startswith("Backed up ER0000.sl2 (") and one.result["undo"] is None
    both = finished(s, s.run("saves.back_up", {"everything": True}))
    assert both.result["text"] == "Backed up 1 save file(s)."
    backups = world.backups()
    assert [b["action"] for b in backups] == ["Manual backup"] * 2
    assert all(b["path"].read_bytes() == OLD for b in backups)
    nothing = s.jobs.get(s.run("saves.back_up", {}))
    assert nothing is not None and nothing.error is not None and nothing.error.code == "invalid_params"


def test_restore_makes_the_same_backup_as_before_and_returns_the_undo_record(world):
    s = world.session()
    s.run("saves.back_up", {"everything": True})
    bak = world.backups()[0]["path"]
    world.save.write_bytes(NEW)  # the live save moved on since
    plan, snap = ask_and_run(s, "saves.restore_backup", {"backup": str(bak), "target": str(world.save)})
    assert isinstance(plan.words, Confirm) and "ER0000.sl2" in plan.words.title
    assert world.save.read_bytes() == OLD  # put back
    assert_took_the_backup(world, snap, NEW, "Before restoring a backup")  # the safety copy is the file as it was
    assert snap.result["text"] == "ER0000.sl2 is back as it was in the backup"
    undo = finished(s, s.run("saves.undo_change", {"save": str(world.save), "backup": snap.result["backup"]}))
    assert world.save.read_bytes() == NEW and "ER0000.sl2" in undo.result["text"]


def test_restore_writes_nothing_before_the_answer_and_nothing_when_declined(world):
    s = world.session()
    s.run("saves.back_up", {"everything": True})
    bak = world.backups()[0]["path"]
    world.save.write_bytes(NEW)
    plan = s.run("saves.restore_backup", {"backup": str(bak), "target": str(world.save)})
    assert world.save.read_bytes() == NEW and len(world.backups()) == 1
    assert s.answer(plan.id, {"ok": False}) is None
    assert world.save.read_bytes() == NEW and len(world.backups()) == 1


def test_replace_with_a_file_makes_the_same_backup_and_keeps_the_old_save_in_the_library(world):
    s = world.session()
    src = world.folder / "elsewhere.sl2"
    src.write_bytes(OTHER)
    plan, snap = ask_and_run(s, "saves.replace_from_file", {"source": str(src), "target": str(world.save)})
    assert isinstance(plan.words, Confirm) and plan.destructive
    assert world.save.read_bytes() == OTHER
    assert_took_the_backup(world, snap, OLD, "Before copying elsewhere.sl2 over it")
    assert snap.result["text"] == "ER0000.sl2 now holds elsewhere.sl2"
    entries = save_library.load(world.folder)["entries"]  # the save that was replaced went into the Library
    assert len(entries) == 1


def test_replace_with_a_library_copy_makes_the_same_backup(world):
    s = world.session()
    src = world.folder / "elsewhere.sl2"
    src.write_bytes(OTHER)
    entry = save_library.add(world.folder, src, "Before the boss", catalog.ELDEN_RING, action="import")
    got = s.run("saves.copy_entry", {"folder": str(world.folder), "entry_id": entry["id"]})
    assert got.name == "Before the boss" and not got.changed_outside
    plan, snap = ask_and_run(
        s,
        "saves.replace_from_library",
        {"folder": str(world.folder), "entry_id": entry["id"], "target": str(world.save)},
    )
    assert plan.destructive and world.save.read_bytes() == OTHER
    assert_took_the_backup(world, snap, OLD, "Before swapping in 'Before the boss'")
    assert snap.result["text"] == "ER0000.sl2 now holds Before the boss"


def test_a_copy_that_is_gone_is_a_refusal_not_a_write(world):
    plan = world.session().run(
        "saves.replace_from_library", {"folder": str(world.folder), "entry_id": "nope", "target": str(world.save)}
    )
    assert isinstance(plan, Refusal) and plan.title == "This copy cannot be used"
    assert world.save.read_bytes() == OLD and world.backups() == []


def test_copy_a_character_backs_up_the_target_and_returns_the_undo_record(world, monkeypatch):
    plan_info = {"character": {"name": "Ann", "level": 10}, "replaces": None, "steam_id_changes": False}
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda *a: plan_info)

    def copy(src, ss, dst, ds):
        bak = save_fix.backup(dst, {"action": "Before copying a character in", "changes": []})
        dst.write_bytes(NEW)
        return {**plan_info, "backup": bak}

    monkeypatch.setattr(save_transfer, "copy_character", copy)
    s = world.session()
    other = world.folder / "ER0000.co2"
    other.write_bytes(OTHER)
    params = {"source": str(other), "src_slot": 1, "target": str(world.save), "dst_slot": 2}
    plan, snap = ask_and_run(s, "saves.copy_character", params)
    assert isinstance(plan.words, Confirm) and not plan.destructive  # an empty slot loses nothing
    assert_took_the_backup(world, snap, OLD, "Before copying a character in")
    assert snap.result["text"] == "Ann is in slot 2 of ER0000.sl2"


def test_copy_a_character_that_cannot_be_planned_is_a_refusal(world, monkeypatch):
    def cannot(*a):
        raise save_transfer.TransferError("Slot 1 has no character.")

    monkeypatch.setattr(save_transfer, "plan_character_copy", cannot)
    got = world.session().run(
        "saves.copy_character", {"source": "a", "src_slot": 1, "target": str(world.save), "dst_slot": 2}
    )
    assert isinstance(got, Refusal) and "no character" in got.body


def test_repair_backs_up_first_and_returns_the_undo_record(world, monkeypatch):
    info = {"path": world.save, "name": "ER0000.sl2", "characters": [{"slot": 1, "name": "Ann"}]}
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: info)

    def fix(path, *, loc):
        bak = save_fix.backup(path, {"action": "Before fixing checksums"})
        path.write_bytes(NEW)
        return {"backup": bak}

    monkeypatch.setattr(saves_service, "fix_checksums", fix)
    s = world.session()
    plan, snap = ask_and_run(s, "saves.repair", {"path": str(world.save), "keys": [["checksum", 1]]})
    assert isinstance(plan.words, Confirm) and "Repair 1 item in ER0000.sl2" == plan.words.title
    assert_took_the_backup(world, snap, OLD, "Before fixing checksums")
    with pytest.raises(OperationError) as e:
        s.run("saves.repair", {"path": str(world.save), "keys": []})
    assert e.value.code == "invalid_params"


def test_post_session_repair_runs_as_a_job(world, monkeypatch):
    ran = []
    monkeypatch.setattr("bayle.saves.repair.repair_all", lambda loc: ran.append(loc))
    s = world.session()
    snap = finished(s, s.run("saves.post_session_repair"))
    assert snap.result["text"] == "Post-session repair finished" and ran == [world.loc]


# ---------------------------------------------------------------------------------------------------- the gate
PLANS = [
    ("saves.copy_character", {"source": "a", "src_slot": 1, "target": "b", "dst_slot": 2}),
    ("saves.replace_from_file", {"source": "a", "target": "b"}),
    ("saves.replace_from_library", {"folder": "f", "entry_id": "i", "target": "b"}),
    ("saves.restore_backup", {"backup": "a", "target": "b"}),
    ("saves.repair", {"path": "a", "keys": [["checksum", 1]]}),
]


@pytest.mark.parametrize(("name", "params"), PLANS)
def test_no_plan_is_offered_while_the_game_runs_or_a_job_runs(world, name, params):
    running = world.session(game_running=lambda: True).run(name, params)
    assert isinstance(running, Refusal) and "Close" in running.title
    busy = world.session(external_busy=lambda: True).run(name, params)
    assert isinstance(busy, Refusal) and busy.title == "A job is running"


def test_writing_jobs_are_refused_while_the_game_runs(world):
    from bayle.errors import Busy

    for name, params in (("saves.back_up", {"everything": True}), ("saves.post_session_repair", {})):
        with pytest.raises(Busy):
            world.session(game_running=lambda: True).run(name, params)
    assert world.backups() == [] and world.save.read_bytes() == OLD


def test_a_plan_is_refused_when_the_save_changed_since_it_was_asked(world):
    s = world.session()
    s.run("saves.back_up", {"everything": True})
    bak = world.backups()[0]["path"]
    plan = s.run("saves.restore_backup", {"backup": str(bak), "target": str(world.save)})
    world.save.write_bytes(NEW + b"!")  # the game wrote it meanwhile
    with pytest.raises(PlanError) as e:
        s.answer(plan.id, {"ok": True})
    assert e.value.code == "plan_stale" and world.save.read_bytes() == NEW + b"!"


# ---------------------------------------------------------------------------------------------------- the Library
def test_save_a_copy_and_import_add_to_the_library_even_while_the_game_runs(world):
    s = world.session(game_running=lambda: True)
    got = finished(s, s.run("saves.save_copy", {"path": str(world.save), "name": "Mine"}))
    assert got.result["text"] == "Saved a copy of ER0000.sl2 as 'Mine'" and got.result["backup"] is None
    extra = world.folder / "x.sl2"
    extra.write_bytes(OTHER)
    one = finished(s, s.run("saves.import_files", {"files": [str(extra)], "name": "Imported"}))
    assert one.result["text"] == "Imported 'Imported' into the Library"
    many = finished(s, s.run("saves.import_files", {"files": [str(extra), str(world.save)]}))
    assert many.result["text"] == "Imported 2 files into the Library"
    assert len(save_library.load(world.folder)["entries"]) == 4
    assert world.save.read_bytes() == OLD and world.backups() == []


def test_save_a_copy_waits_for_a_running_write(world):
    s = world.session(external_busy=lambda: True)
    snap = s.jobs.get(s.run("saves.save_copy", {"path": str(world.save), "name": "Mine"}))
    assert snap is not None and snap.state == "failed" and snap.error is not None and snap.error.code == "busy"


def test_import_without_a_save_folder_is_a_failed_job_with_a_code(world):
    world.save.unlink()
    s = world.session()
    snap = s.jobs.get(s.run("saves.import_files", {"files": [str(world.folder / "x.sl2")]}))
    assert snap is not None and snap.error is not None and snap.error.code == "no_saves"


def test_the_upkeep_of_copies_and_backups(world):
    s = world.session()
    s.run("saves.back_up", {"everything": True})
    bak = world.backups()[0]["path"]
    s.run("saves.keep_backup", {"backup": str(bak)})
    assert world.backups()[0]["keep"] is True
    s.run("saves.keep_backup", {"backup": str(bak), "keep": False})
    assert world.backups()[0]["keep"] is False
    assert s.run("saves.keep_as", {"backup": str(bak), "name": "Kept"}).text == "Kept"
    folder = str(world.folder)
    entry = save_library.load(world.folder)["entries"][0]
    s.run("saves.rename_copy", {"folder": folder, "entry_id": entry["id"], "name": "Renamed"})
    assert save_library.load(world.folder)["entries"][0]["name"] == "Renamed"
    plan = s.run("saves.remove_copy", {"folder": folder, "entry_id": entry["id"]})
    assert isinstance(plan.words, Confirm) and plan.destructive and len(save_library.load(world.folder)["entries"]) == 1
    assert s.answer(plan.id, {"ok": True}) is None
    assert save_library.load(world.folder).get("entries", []) == []
    gone = s.run("saves.delete_backup", {"backup": str(bak)})
    assert isinstance(gone.words, Confirm) and gone.destructive and bak.exists()
    s.answer(gone.id, {"ok": True})
    assert not bak.exists()
    with pytest.raises(OperationError) as e:
        s.run("saves.delete_backup", {"backup": str(bak)})
    assert e.value.code == "not_found"
    with pytest.raises(OperationError) as e:
        s.run("saves.finish_stranded", {"folder": folder, "entry_id": "nope", "restore": False})
    assert e.value.code == "failed"
