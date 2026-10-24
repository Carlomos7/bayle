"""The Saves writes to live saves through Session.run: each is a check (facts and stamp) and a start (refused as stale
when a file changed since). Saves are invented (tests/unit/synthetic_save.py), in the test's own folders; the real
writers run, so the bytes, the backup and the Undo record are the writers' own. Nothing here knows a window."""

import hashlib
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from synthetic_save import build, disk_full_on_tmp, put, stale_slot, strays  # noqa: E402

from bayle.errors import Busy, OperationError  # noqa: E402
from bayle.game import catalog  # noqa: E402
from bayle.game.locate import Locations, Overrides  # noqa: E402
from bayle.platform import logging as run_logging  # noqa: E402
from bayle.saves import fix as save_fix  # noqa: E402
from bayle.saves import layout as L  # noqa: E402
from bayle.saves import library as save_library  # noqa: E402
from bayle.saves import transfer as save_transfer  # noqa: E402
from bayle.services import saves as saves_service  # noqa: E402
from bayle.services.saves_page import SavesService  # noqa: E402
from bayle.session import Session  # noqa: E402
from bayle.session import ops as _ops  # noqa: E402,F401  registers the operations
from bayle.work.events import EventBus  # noqa: E402
from bayle.work.jobs import JobManager  # noqa: E402

ACCOUNT = 76561198000000001  # the folder's name: a save that carries it is not re-signed when it is put over another


def for_account(data: bytes) -> bytes:
    d, pos = bytearray(data), L.parse_bytes(data)["ud10_pos"]
    struct.pack_into("<Q", d, pos + 0x14, ACCOUNT)
    save_fix._sign_ud10(d, pos)
    return bytes(d)


OLD, NEW, OTHER = (for_account(build({0: b}, active=())) for b in (b"old", b"new", b"other"))


class World:
    """One account with one Standard save, a second file to put over it, a backup of it and a Library copy."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.save = put(self.folder / "ER0000.sl2", OLD)
        self.picked = put(tmp_path / "picked" / "ER0000.co2", OTHER)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(self.root)))

    def session(self, **jobs) -> Session:
        jobs_ = JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs)
        return Session(
            jobs_,
            locations=lambda: self.loc,
            services={"saves": SavesService(jobs_, lambda: self.loc)},
        )

    def backups(self):
        return saves_service.list_backups(loc=self.loc)

    def backup(self) -> Path:
        return saves_service.back_up_now(self.save, loc=self.loc)

    def copy(self, data: bytes = OTHER, name: str = "Mine") -> dict:
        src = put(self.tmp / "lib-src.sl2", data)
        return save_library.add(self.folder, src, name, catalog.ELDEN_RING, action="import")

    def entries(self):
        return save_library.load(self.folder)["entries"]


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def finished(session: Session, job_id: str):
    snap = session.jobs.get(job_id)
    assert snap is not None and snap.state == "done", snap
    return snap


def run_write(session: Session, name: str, params: dict):
    """The check, then the start with its stamp: returns (the check, the finished job)."""
    checked = session.run(f"saves.check_{name}", params)
    job = session.run(f"saves.{name}", {**params, "expect": checked.stamp})
    return checked, finished(session, job.job_id)


def assert_took_the_backup(world: World, snap, before: bytes, action: str):
    """The write returned the backup of the file as it was, noted with the action, and the undo record for it."""
    result = snap.result
    backup = result["backup"]
    assert backup and Path(backup).read_bytes() == before
    assert any(str(b["path"]) == backup and b["action"] == action for b in world.backups())
    record = {"type": "save-restore", "save": str(world.save), "backup": backup, "name": world.save.name}
    assert result["undo"] == record and result["save"] == str(world.save)
    assert run_logging.read_jobs_from(None)[0]["undo"] == record  # the jobs index holds it too (Activity's Undo)


def undo(session: Session, snap):
    return finished(
        session, session.run("saves.undo_change", {"save": snap.result["save"], "backup": snap.result["backup"]}).job_id
    )


# ------------------------------------------------------------------------------------ each write, check then start
def test_restore_puts_the_backup_back_and_undo_takes_that_back(world):
    s = world.session()
    bak = world.backup()
    world.save.write_bytes(NEW)  # the live save moved on since
    checked, snap = run_write(s, "restore_backup", {"backup": str(bak), "target": str(world.save)})
    assert checked.backup["action"] == "Manual backup" and checked.target == str(world.save)
    assert world.save.read_bytes() == OLD
    assert snap.result["file"] == "ER0000.sl2"
    assert_took_the_backup(world, snap, NEW, "Before restoring a backup")  # the safety copy is the file as it was
    assert undo(s, snap).result == {"file": "ER0000.sl2"} and world.save.read_bytes() == NEW


def test_replace_from_file_checks_then_writes_and_keeps_the_old_save_in_the_library(world):
    s = world.session()
    checked, snap = run_write(s, "replace_from_file", {"source": str(world.picked), "target": str(world.save)})
    assert checked.label == "ER0000.co2" and not checked.from_library and checked.holders == 0
    assert checked.source == str(world.picked) and checked.signed is False
    assert world.save.read_bytes() == OTHER
    assert snap.result["file"] == "ER0000.sl2" and snap.result["source"] == "ER0000.co2"
    assert_took_the_backup(world, snap, OLD, "Before copying ER0000.co2 over it")
    assert len(world.entries()) == 1  # the save that was replaced went into the Library
    assert undo(s, snap) and world.save.read_bytes() == OLD


def test_replace_from_library_checks_then_writes(world):
    s = world.session()
    entry = world.copy()
    params = {"folder": str(world.folder), "entry_id": entry["id"], "target": str(world.save)}
    checked, snap = run_write(s, "replace_from_library", params)
    assert checked.label == "Mine" and checked.from_library and not checked.changed_outside
    assert world.save.read_bytes() == OTHER and snap.result["source"] == "Mine"
    assert_took_the_backup(world, snap, OLD, "Before swapping in 'Mine'")


def test_a_library_copy_changed_outside_says_so_in_the_check(world):
    entry = world.copy()
    save_library.entry_path(world.folder, entry).write_bytes(NEW)
    got = world.session().run(
        "saves.check_replace_from_library",
        {"folder": str(world.folder), "entry_id": entry["id"], "target": str(world.save)},
    )
    assert got.changed_outside is True


def test_repair_fixes_the_checksum_backs_up_first_and_undo_takes_it_back(world):
    broken = stale_slot(build({0: b"hello"}, active=(0,)), 0)
    world.save.write_bytes(broken)
    s = world.session()
    checked, snap = run_write(s, "repair", {"path": str(world.save), "keys": [["checksum", 1]]})
    assert checked.info["name"] == "ER0000.sl2" and checked.keys == [["checksum", 1]]
    fixed = world.save.read_bytes()
    assert (
        fixed[L.HEADER : L.HEADER + 0x10]
        == hashlib.md5(broken[L.HEADER + 0x10 : L.HEADER + save_fix.SLOT_STRIDE]).digest()
    )
    assert_took_the_backup(world, snap, broken, "Before fixing checksums")
    assert snap.result["file"] == "ER0000.sl2"
    undo(s, snap)
    assert world.save.read_bytes() == broken


def test_copy_a_character_checks_then_writes_and_returns_the_undo_record(world, monkeypatch):
    plan = {"character": {"name": "Ann", "level": 10}, "replaces": None, "steam_id_changes": False}
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda *a: plan)

    def copy(src, ss, dst, ds):
        bak = save_fix.backup(dst, {"action": "Before copying a character in", "changes": []})
        dst.write_bytes(NEW)
        return {**plan, "backup": bak}

    monkeypatch.setattr(save_transfer, "copy_character", copy)
    s = world.session()
    params = {"source": str(world.save), "src_slot": 1, "target": str(world.save), "dst_slot": 2}
    checked, snap = run_write(s, "copy_character", params)
    assert checked.plan == plan and checked.same_file  # a duplicate in the same file
    assert snap.result["character"] == "Ann" and snap.result["slot"] == 2 and snap.result["file"] == "ER0000.sl2"
    assert_took_the_backup(world, snap, OLD, "Before copying a character in")


def test_copy_a_character_from_a_listed_library_copy(world, monkeypatch):
    seen = []
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda src, *a: seen.append(src) or {"character": None})
    entry = world.copy()
    path = save_library.entry_path(world.folder, entry)
    got = world.session().run(
        "saves.check_copy_character", {"source": str(path), "src_slot": 1, "target": str(world.save), "dst_slot": 2}
    )
    assert seen == [path] and not got.same_file


def test_a_character_copy_that_cannot_be_planned_is_not_possible(world, monkeypatch):
    def cannot(*a):
        raise save_transfer.TransferError("Slot 1 has no character.")

    monkeypatch.setattr(save_transfer, "plan_character_copy", cannot)
    with pytest.raises(OperationError) as e:
        world.session().run(
            "saves.check_copy_character",
            {"source": str(world.save), "src_slot": 1, "target": str(world.save), "dst_slot": 2},
        )
    assert e.value.code == "not_possible" and "no character" in e.value.message


def test_post_session_repair_and_undo_are_jobs(world, monkeypatch):
    ran = []
    monkeypatch.setattr("bayle.saves.repair.repair_all", lambda loc: ran.append(loc))
    s = world.session()
    snap = finished(s, s.run("saves.post_session_repair").job_id)
    assert ran == [world.loc] and snap.result == {"save": None, "backup": None, "undo": None}


# ------------------------------------------------------------------------------------ the call of each write
def calls(world: World):
    """(write name, its params) for each write that takes a check, with a live target and a backup/copy/file."""
    bak = world.backup()
    entry = world.copy()
    return {
        "restore_backup": {"backup": str(bak), "target": str(world.save)},
        "replace_from_file": {"source": str(world.picked), "target": str(world.save)},
        "replace_from_library": {"folder": str(world.folder), "entry_id": entry["id"], "target": str(world.save)},
        "repair": {"path": str(world.save), "keys": [["regulation", 0]]},
    }


SOURCE = {  # the file a write reads besides the live save
    "restore_backup": lambda w, p: Path(p["backup"]),
    "replace_from_file": lambda w, p: w.picked,
    "replace_from_library": lambda w, p: save_library.entry_path(w.folder, w.entries()[0]),
}


@pytest.mark.parametrize(
    ("name", "what"),
    [(n, "target") for n in ("restore_backup", "replace_from_file", "replace_from_library", "repair")]
    + [(n, "source") for n in SOURCE],
)
def test_a_start_is_stale_when_a_file_changed_since_the_check_and_writes_nothing(world, name, what):
    params = calls(world)[name]
    s = world.session()
    stamp = s.run(f"saves.check_{name}", params).stamp
    touched = world.save if what == "target" else SOURCE[name](world, params)
    touched.write_bytes(touched.read_bytes() + b"!")  # the game (or another program) wrote it meanwhile
    files = {p: p.read_bytes() for p in (world.save, world.picked, touched)}
    backups, entries = len(world.backups()), len(world.entries())
    with pytest.raises(OperationError) as e:
        s.run(f"saves.{name}", {**params, "expect": stamp})
    assert e.value.code == "stale"
    assert {p: p.read_bytes() for p in files} == files and strays(world.tmp) == []
    assert (len(world.backups()), len(world.entries())) == (backups, entries)


def test_copy_character_is_stale_too(world, monkeypatch):
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda *a: {"character": None})
    wrote = []
    monkeypatch.setattr(save_transfer, "copy_character", lambda *a: wrote.append(a))
    s = world.session()
    params = {"source": str(world.save), "src_slot": 1, "target": str(world.save), "dst_slot": 2}
    stamp = s.run("saves.check_copy_character", params).stamp
    world.save.write_bytes(NEW)
    with pytest.raises(OperationError) as e:
        s.run("saves.copy_character", {**params, "expect": stamp})
    assert e.value.code == "stale" and wrote == []


def test_a_start_confirmed_with_the_stamp_of_nothing_is_stale(world):
    s = world.session()
    bak = world.backup()
    params = {"backup": str(bak), "target": str(world.save)}
    with pytest.raises(OperationError) as e:
        s.run("saves.restore_backup", {**params, "expect": [None, None]})
    assert e.value.code == "stale" and world.save.read_bytes() == OLD


# ------------------------------------------------------------------------------------ the boundary
def test_unlisted_targets_backups_and_copies_are_not_found_and_nothing_is_written(world):
    s = world.session()
    stray = put(world.tmp / "stray.sl2", OTHER)
    bak = world.backup()
    entry = world.copy()
    ghost = {"folder": str(world.folder), "entry_id": "nope", "target": str(world.save)}
    cases = [
        ("check_restore_backup", {"backup": str(bak), "target": str(stray)}),
        ("check_restore_backup", {"backup": str(stray), "target": str(world.save)}),
        ("check_replace_from_file", {"source": str(world.picked), "target": str(stray)}),
        ("check_replace_from_file", {"source": str(world.tmp / "nothing.sl2"), "target": str(world.save)}),
        ("check_replace_from_library", ghost),
        ("check_replace_from_library", {**ghost, "entry_id": entry["id"], "folder": str(world.tmp)}),
        ("check_replace_from_library", {**ghost, "entry_id": entry["id"], "target": str(stray)}),
        ("check_repair", {"path": str(stray), "keys": [["checksum", 1]]}),
        ("check_copy_character", {"source": str(stray), "src_slot": 1, "target": str(world.save), "dst_slot": 2}),
        ("check_copy_character", {"source": str(world.save), "src_slot": 1, "target": str(stray), "dst_slot": 2}),
        ("restore_backup", {"backup": str(stray), "target": str(world.save), "expect": [None, None]}),
        ("replace_from_file", {"source": str(world.picked), "target": str(stray), "expect": [None, None]}),
        ("replace_from_library", {**ghost, "expect": [None, None]}),
        ("repair", {"path": str(stray), "keys": [["checksum", 1]], "expect": [None]}),
        (
            "copy_character",
            {"source": str(stray), "src_slot": 1, "target": str(world.save), "dst_slot": 2, "expect": [None, None]},
        ),
        ("undo_change", {"save": str(stray), "backup": str(bak)}),
        ("undo_change", {"save": str(world.save), "backup": str(stray)}),
    ]
    for name, params in cases:
        with pytest.raises(OperationError) as e:
            s.run(f"saves.{name}", params)
        assert e.value.code == "not_found", (name, params, e.value.code)
    assert world.save.read_bytes() == OLD and stray.read_bytes() == OTHER and len(world.backups()) == 1
    assert len(world.entries()) == 1


def test_a_picked_file_that_is_far_too_big_is_not_a_save(world, monkeypatch):
    monkeypatch.setattr(save_library, "MAX_SAVE_BYTES", 10)
    with pytest.raises(OperationError) as e:
        world.session().run("saves.check_replace_from_file", {"source": str(world.picked), "target": str(world.save)})
    assert e.value.code == "not_a_save"


def test_a_repair_with_nothing_ticked_is_invalid(world):
    for name, extra in (("check_repair", {}), ("repair", {"expect": [None]})):
        with pytest.raises(OperationError) as e:
            world.session().run(f"saves.{name}", {"path": str(world.save), "keys": [], **extra})
        assert e.value.code == "invalid_params"


# ------------------------------------------------------------------------------------ the gates
@pytest.mark.parametrize("gate", [{"game_running": lambda: True}, {"external_busy": lambda: True}])
@pytest.mark.parametrize("name", ["restore_backup", "replace_from_file", "replace_from_library", "repair"])
def test_no_write_starts_while_the_game_runs_or_another_write_runs(world, name, gate):
    params = calls(world)[name]
    stamp = world.session().run(f"saves.check_{name}", params).stamp  # a check is a read: allowed
    backups = len(world.backups())
    with pytest.raises(Busy):
        world.session(**gate).run(f"saves.{name}", {**params, "expect": stamp})
    assert world.save.read_bytes() == OLD and len(world.backups()) == backups and len(world.entries()) == 1


@pytest.mark.parametrize("gate", [{"game_running": lambda: True}, {"external_busy": lambda: True}])
def test_copy_character_post_session_repair_and_undo_are_refused_too(world, gate, monkeypatch):
    monkeypatch.setattr(save_transfer, "plan_character_copy", lambda *a: {"character": None})
    wrote = []
    monkeypatch.setattr(save_transfer, "copy_character", lambda *a: wrote.append(a))
    bak = world.backup()
    copy = {"source": str(world.save), "src_slot": 1, "target": str(world.save), "dst_slot": 2}
    stamp = world.session().run("saves.check_copy_character", copy).stamp
    s = world.session(**gate)
    for name, params in (
        ("copy_character", {**copy, "expect": stamp}),
        ("post_session_repair", {}),
        ("undo_change", {"save": str(world.save), "backup": str(bak)}),
    ):
        with pytest.raises(Busy):
            s.run(f"saves.{name}", params)
    assert wrote == [] and world.save.read_bytes() == OLD


# ------------------------------------------------------------------------------------ a failed write
@pytest.mark.parametrize("name", ["restore_backup", "replace_from_file"])
def test_a_failed_write_leaves_the_save_as_it_was_and_reports_its_code(world, name, monkeypatch):
    params = calls(world)[name]
    s = world.session()
    stamp = s.run(f"saves.check_{name}", params).stamp
    disk_full_on_tmp(monkeypatch, world.save)
    snap = s.jobs.get(s.run(f"saves.{name}", {**params, "expect": stamp}).job_id)
    assert snap.state == "failed" and snap.error.code == "failed" and snap.result is None
    assert world.save.read_bytes() == OLD and strays(world.tmp) == []
    assert run_logging.read_jobs_from(None)[0].get("undo") is None  # nothing to take back
