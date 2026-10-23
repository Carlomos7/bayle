"""The upkeep of Library copies and backups (group B), through Session.run and straight on SavesService. Every file is
invented, in the test's own folders (the data folder is the conftest's temporary one). Upkeep never touches a live
save, so it is not gated on the game running."""

import os
import threading

import pytest

from bayle.errors import OperationError
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

OLD, OTHER = b"old save " * 40, b"other save " * 40


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.folder.mkdir(parents=True)
        self.save = self.folder / "ER0000.sl2"
        self.save.write_bytes(OLD)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(self.root)))
        self.svc = SavesService(JobManager(EventBus()), lambda: self.loc)

    def session(self, **jobs) -> Session:
        jobs_ = JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs)
        return Session(
            jobs_,
            plans=PlanStore(),
            locations=lambda: self.loc,
            services={"saves": SavesService(jobs_, lambda: self.loc)},
        )

    def backup(self):
        """One backup of the live save, taken the way the app takes it."""
        return saves_service.back_up_now(self.save, loc=self.loc)

    def backups(self):
        return saves_service.list_backups(loc=self.loc)

    def copy(self, name="Mine", data=OTHER):
        src = self.tmp / f"src-{name}.sl2"
        src.write_bytes(data)
        return save_library.add(self.folder, src, name, catalog.ELDEN_RING, action="import")

    @property
    def removed(self):
        return save_library.folder_for(self.folder) / save_backups.LIBRARY_REMOVED

    def entries(self):
        return save_library.load(self.folder)["entries"]

    def removed_names(self):
        return sorted(p.name for p in self.removed.glob("*")) if self.removed.exists() else []


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(save_regulation, "is_pc_save", lambda data: True)
    monkeypatch.setattr(save_library, "check_whole", lambda data, game: None)
    monkeypatch.setattr(save_library, "signed_for_account", lambda data, target, game: (data, False))
    monkeypatch.setattr(save_library, "characters", lambda path, game=None: [])
    return World(tmp_path)


def code(fn, *a, **kw) -> str:
    with pytest.raises(OperationError) as e:
        fn(*a, **kw)
    return e.value.code


# ------------------------------------------------------------------------------------------------ happy paths
def test_keep_backup_round_trips_through_the_session(world):
    s = world.session()
    bak = world.backup()
    s.run("saves.keep_backup", {"backup": str(bak)})
    assert world.backups()[0]["keep"] is True
    s.run("saves.keep_backup", {"backup": str(bak), "keep": False})
    assert world.backups()[0]["keep"] is False


def test_keep_as_adds_a_copy_and_the_backup_stays(world):
    s = world.session()
    bak = world.backup()
    assert s.run("saves.keep_as", {"backup": str(bak), "name": "Kept"}).text == "Kept"
    assert [e["name"] for e in world.entries()] == ["Kept"]
    assert bak.read_bytes() == OLD and len(world.backups()) == 1


def test_rename_returns_the_name_it_got(world):
    entry = world.copy()
    ref = {"folder": str(world.folder), "entry_id": entry["id"]}
    assert world.session().run("saves.rename_copy", {**ref, "name": "Renamed"}).text == "Renamed"
    assert world.entries()[0]["name"] == "Renamed"


def test_remove_copy_moves_the_file_to_removed_with_its_note(world):
    entry = world.copy()
    s = world.session()
    ref = {"folder": str(world.folder), "entry_id": entry["id"]}
    before = (world.entries(), world.removed_names())
    assert s.run("saves.check_remove_copy", ref).text == "Mine"
    assert (world.entries(), world.removed_names()) == before  # a check writes nothing
    s.run("saves.remove_copy", {**ref, "expect": "Mine"})
    assert world.entries() == []
    assert (world.removed / entry["file"]).read_bytes() == OTHER  # moved, not deleted
    assert (world.removed / f"{entry['file']}.json").is_file()
    assert not (save_library.folder_for(world.folder) / entry["file"]).exists()


def test_delete_backup_removes_it_and_its_notes(world):
    s = world.session()
    bak = world.backup()
    s.run("saves.keep_backup", {"backup": str(bak)})
    notes = save_backups.note_files(bak)
    assert notes and all(n.exists() for n in notes)
    got = s.run("saves.check_delete_backup", {"backup": str(bak)})
    assert got.path == str(bak) and got.save_name == "ER0000.sl2" and bak.exists()  # a check writes nothing
    s.run("saves.delete_backup", {"backup": str(bak), "expect": list(got.stamp)})
    assert not bak.exists() and not any(n.exists() for n in notes) and world.backups() == []


def test_adopt_legacy_moves_an_older_tools_backups_into_bayles(world):
    legacy = world.folder / "save-fix-backups"
    legacy.mkdir()
    old = legacy / "ER0000.sl2.20260101-000000.bak"
    old.write_bytes(OLD)
    assert world.session().run("saves.adopt_legacy").folders == [str(world.folder)]
    assert not old.exists()
    [row] = world.backups()
    assert row["action"] == "Before a save fix" and row["path"].read_bytes() == OLD
    assert row["path"].parent == save_backups.account_dir(world.folder) / save_backups.BACKUPS


def test_the_service_answers_the_same_directly(world):
    bak = world.backup()
    entry = world.copy()
    svc = world.svc
    svc.keep_backup(bak)
    assert world.backups()[0]["keep"] is True
    assert svc.keep_as(bak, "Kept") == "Kept"
    assert svc.rename_copy(world.folder, entry["id"], "R") == "R"
    assert svc.check_remove_copy(world.folder, entry["id"]) == "R"
    svc.remove_copy(world.folder, entry["id"], "R")
    facts = svc.check_delete_backup(bak)
    assert facts.stamp == (facts.size, facts.mtime)
    svc.delete_backup(bak, facts.stamp)
    assert not bak.exists()


# ------------------------------------------------------------------------------------------------ stale
def test_delete_backup_is_stale_when_the_backup_was_rewritten_after_the_check(world):
    s = world.session()
    bak = world.backup()
    stamp = list(s.run("saves.check_delete_backup", {"backup": str(bak)}).stamp)
    bak.write_bytes(OLD + b"more")  # size changed
    assert code(s.run, "saves.delete_backup", {"backup": str(bak), "expect": stamp}) == "stale"
    assert bak.read_bytes() == OLD + b"more"
    stamp = list(s.run("saves.check_delete_backup", {"backup": str(bak)}).stamp)
    st = bak.stat()
    os.utime(bak, (st.st_atime, st.st_mtime + 100))  # only the time changed
    assert code(s.run, "saves.delete_backup", {"backup": str(bak), "expect": stamp}) == "stale"
    assert bak.exists()


def test_remove_copy_is_stale_when_the_copy_was_renamed_after_the_check(world):
    entry = world.copy()
    s = world.session()
    ref = {"folder": str(world.folder), "entry_id": entry["id"]}
    name = s.run("saves.check_remove_copy", ref).text
    s.run("saves.rename_copy", {**ref, "name": "Other"})
    assert code(s.run, "saves.remove_copy", {**ref, "expect": name}) == "stale"
    assert [e["name"] for e in world.entries()] == ["Other"] and not world.removed.exists()


# ------------------------------------------------------------------------------------------------ not_found
def test_a_path_that_is_not_a_listed_backup_is_not_found_and_untouched(world):
    s = world.session()
    stray = world.tmp / "stray.bak"
    stray.write_bytes(b"x")
    for target in (stray, world.save):
        ref = {"backup": str(target)}
        assert code(s.run, "saves.delete_backup", {**ref, "expect": [1, 1.0]}) == "not_found"
        assert code(s.run, "saves.check_delete_backup", ref) == "not_found"
        assert code(s.run, "saves.keep_backup", ref) == "not_found"
        assert code(s.run, "saves.keep_as", {**ref, "name": "X"}) == "not_found"
    assert stray.read_bytes() == b"x" and world.save.read_bytes() == OLD
    assert list(world.tmp.glob("*.json")) == [] and list(world.folder.glob("*.json")) == []  # no keep note
    assert world.entries() == []


def test_an_unknown_entry_or_folder_is_not_found(world):
    s = world.session()
    entry = world.copy()
    nope = {"folder": str(world.folder), "entry_id": "nope"}
    elsewhere = {"folder": str(world.tmp / "elsewhere"), "entry_id": entry["id"]}
    for ref in (nope, elsewhere):
        assert code(s.run, "saves.check_remove_copy", ref) == "not_found"
        assert code(s.run, "saves.remove_copy", {**ref, "expect": "Mine"}) == "not_found"
        assert code(s.run, "saves.rename_copy", {**ref, "name": "X"}) == "not_found"
    assert code(s.run, "saves.finish_stranded", {**nope, "restore": True}) == "not_found"
    assert code(s.run, "saves.finish_stranded", {**elsewhere, "restore": True}) == "not_found"
    assert [e["name"] for e in world.entries()] == ["Mine"]


def test_a_backup_already_gone_is_not_found(world):
    s = world.session()
    bak = world.backup()
    stamp = list(s.run("saves.check_delete_backup", {"backup": str(bak)}).stamp)
    s.run("saves.delete_backup", {"backup": str(bak), "expect": stamp})
    assert code(s.run, "saves.delete_backup", {"backup": str(bak), "expect": stamp}) == "not_found"
    assert code(s.run, "saves.keep_backup", {"backup": str(bak)}) == "not_found"


# ------------------------------------------------------------------------------------------------ interrupted removals
def break_manifest(m):
    def boom(*a, **k):
        raise OSError("disk full")

    m.setattr(save_library, "_save", boom)


def test_a_removal_whose_manifest_write_fails_puts_the_copy_back(world, monkeypatch):
    entry = world.copy()
    home = save_library.folder_for(world.folder) / entry["file"]
    ref = {"folder": str(world.folder), "entry_id": entry["id"], "expect": "Mine"}
    with monkeypatch.context() as m:
        break_manifest(m)
        assert code(world.session().run, "saves.remove_copy", ref) == "failed"
    assert home.read_bytes() == OTHER and [e["name"] for e in world.entries()] == ["Mine"]
    assert world.removed_names() == []  # no stray note, no stray file


def strand(world, monkeypatch):
    """The state when even the move back failed: the file and its note in removed/, the entry still listed."""
    entry = world.copy()
    with monkeypatch.context() as m:
        break_manifest(m)
        m.setattr(save_library, "_undo_remove", lambda *a: None)
        assert code(world.svc.remove_copy, world.folder, entry["id"], "Mine") == "failed"
    moved = world.removed / entry["file"]
    assert moved.is_file() and (world.removed / f"{entry['file']}.json").is_file()
    assert world.entries()[0]["in_removed"] == str(moved)
    return entry, moved


def test_finish_stranded_restore_puts_the_copy_back(world, monkeypatch):
    entry, moved = strand(world, monkeypatch)
    ref = {"folder": str(world.folder), "entry_id": entry["id"], "restore": True}
    assert world.session().run("saves.finish_stranded", ref).warning == ""
    assert (save_library.folder_for(world.folder) / entry["file"]).read_bytes() == OTHER
    assert not moved.exists() and not (world.removed / f"{entry['file']}.json").exists()
    assert not world.entries()[0]["missing"]


def test_finish_stranded_without_restore_finishes_the_removal(world, monkeypatch):
    entry, moved = strand(world, monkeypatch)
    ref = {"folder": str(world.folder), "entry_id": entry["id"], "restore": False}
    world.session().run("saves.finish_stranded", ref)
    assert world.entries() == [] and moved.read_bytes() == OTHER  # kept in removed/, like any removal
    assert (world.removed / f"{entry['file']}.json").is_file()


@pytest.mark.parametrize("restore", [True, False])
def test_finish_stranded_refuses_when_the_note_is_missing(world, monkeypatch, restore):
    entry, moved = strand(world, monkeypatch)
    (world.removed / f"{entry['file']}.json").unlink()
    assert code(world.svc.finish_stranded, world.folder, entry["id"], restore) == "failed"
    assert moved.read_bytes() == OTHER and len(world.entries()) == 1


@pytest.mark.parametrize("restore", [True, False])
def test_finish_stranded_refuses_when_the_file_changed(world, monkeypatch, restore):
    entry, moved = strand(world, monkeypatch)
    assert entry.get("sha256")
    moved.write_bytes(b"tampered")
    assert code(world.svc.finish_stranded, world.folder, entry["id"], restore) == "failed"
    assert moved.read_bytes() == b"tampered" and len(world.entries()) == 1
    assert (world.removed / f"{entry['file']}.json").is_file()


def test_finish_stranded_on_a_copy_that_is_in_place_changes_nothing(world):
    entry = world.copy()
    assert code(world.svc.finish_stranded, world.folder, entry["id"], False) == "failed"
    assert [e["name"] for e in world.entries()] == ["Mine"]


# ------------------------------------------------------------------------------------------------ the account lock
@pytest.mark.parametrize("op", ["keep_backup", "delete_backup"])
def test_upkeep_fails_while_the_backups_lock_is_held_elsewhere(world, monkeypatch, op):
    monkeypatch.setattr(save_backups, "LOCK_TIMEOUT", 0.3)
    bak = world.backup()
    facts = world.svc.check_delete_backup(bak)
    held, release = threading.Event(), threading.Event()

    def hold():
        with save_backups.account_lock(bak.parent):
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    try:
        assert held.wait(5)
        if op == "keep_backup":
            assert code(world.svc.keep_backup, bak) == "failed"
        else:
            assert code(world.svc.delete_backup, bak, facts.stamp) == "failed"
    finally:
        release.set()
        t.join(10)
    assert bak.read_bytes() == OLD and world.backups()[0]["keep"] is False


# ------------------------------------------------------------------------------------------------ the game runs
def test_the_whole_upkeep_works_while_the_game_runs(world):
    s = world.session(game_running=lambda: True)
    assert s.jobs.game_running
    bak = world.backup()
    entry = world.copy()
    ref = {"folder": str(world.folder), "entry_id": entry["id"]}
    s.run("saves.keep_backup", {"backup": str(bak)})
    assert s.run("saves.keep_as", {"backup": str(bak), "name": "Kept"}).text == "Kept"
    assert s.run("saves.rename_copy", {**ref, "name": "R"}).text == "R"
    s.run("saves.adopt_legacy")
    assert s.run("saves.check_remove_copy", ref).text == "R"
    s.run("saves.remove_copy", {**ref, "expect": "R"})
    stamp = list(s.run("saves.check_delete_backup", {"backup": str(bak)}).stamp)
    s.run("saves.delete_backup", {"backup": str(bak), "expect": stamp})
    assert not bak.exists() and world.save.read_bytes() == OLD
    assert [e["name"] for e in world.entries()] == ["Kept"]
