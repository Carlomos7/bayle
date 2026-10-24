"""How services.saves.restore_backup puts a backup back over a live save through durable_write: the bytes, the backup
(taken only once the written copy verified), and what each failure leaves behind (the save untouched, no stray temp
file)."""

import re

import pytest
from synthetic_save import (
    OLD_MTIME_NS,
    backups_of,
    build,
    corrupt_after_replace,
    corrupt_tmp,
    disk_full_on_tmp,
    put,
    refuse_replace,
    strays,
)

from bayle.game.locate import Locations
from bayle.saves import backups as save_backups
from bayle.saves import fix as F
from bayle.services import saves
from support import er

NOW_MTIME_NS = OLD_MTIME_NS + 5_000_000_000  # the live save is newer than the backup's


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A live save (current), and a backup of an earlier version of it (earlier) taken through fix.backup."""
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    monkeypatch.setattr(saves, "SETTLE_SECONDS", 0.0)
    earlier, current = build({0: b"earlier"}), build({0: b"current"})
    save = put(tmp_path / "ER0000.sl2", earlier)
    bak = F.backup(save, {"action": "Fix loading", "changes": ["x"]})
    put(save, current, NOW_MTIME_NS)
    return save, bak, earlier, current


def test_success_restores_the_backup_and_returns_the_safety_copy(world, tmp_path):
    save, bak, earlier, current = world
    safety = saves.restore_backup(bak, save, loc=er())
    assert save.read_bytes() == earlier
    assert re.fullmatch(r"ER0000\.sl2\.\d{8}-\d{6}(-\d+)?\.bak", safety.name) and safety != bak
    assert safety.read_bytes() == current and safety.stat().st_mtime_ns == NOW_MTIME_NS
    note = F.read_manifest(safety)
    assert note["action"] == "Before restoring a backup"
    assert note["changes"] == [f"restored the copy from {F.read_manifest(bak)['when']}"]
    assert backups_of(save) == sorted([bak, safety])
    assert bak.read_bytes() == earlier  # the backup that was restored stays
    assert strays(tmp_path) == []


def test_a_backup_that_is_not_a_save_is_refused_before_anything_is_taken(world, tmp_path):
    save, _, _, current = world
    junk = save_backups.backups(save.parent) / "ER0000.sl2.junk.bak"
    junk.write_bytes(b"nope")
    with pytest.raises(RuntimeError, match="not a PC"):
        saves.restore_backup(junk, save, loc=er())
    assert save.read_bytes() == current and len(backups_of(save)) == 2  # the first backup and the junk file
    assert strays(tmp_path) == []


def test_a_busy_backup_stops_the_restore(world, tmp_path, monkeypatch):
    save, bak, _, current = world

    def busy(*_a, **_k):
        raise save_backups.BackupsBusy("busy")

    monkeypatch.setattr(F, "backup", busy)
    with pytest.raises(save_backups.BackupsBusy):
        saves.restore_backup(bak, save, loc=er())
    assert save.read_bytes() == current and strays(tmp_path) == []


def test_a_failed_check_leaves_the_save_untouched_and_takes_no_backup(world, tmp_path, monkeypatch):
    save, bak, _, current = world
    corrupt_tmp(monkeypatch, save, 0x400)
    with pytest.raises(RuntimeError):
        saves.restore_backup(bak, save, loc=er())
    assert save.read_bytes() == current and backups_of(save) == [bak] and strays(tmp_path) == []


def test_a_read_back_mismatch_after_the_replace_is_reported(world, tmp_path, monkeypatch):
    # today and after the switch (after=): an error, the new file stays in place, the safety copy is kept
    save, bak, earlier, current = world
    corrupt_after_replace(monkeypatch, save)
    with pytest.raises(RuntimeError, match="did not read back the same after the restore"):
        saves.restore_backup(bak, save, loc=er())
    assert save.read_bytes() != earlier
    (safety,) = [b for b in backups_of(save) if b != bak]
    assert safety.read_bytes() == current


def test_a_replace_refused_once_is_retried_and_written(world, tmp_path, monkeypatch):
    save, bak, earlier, _ = world
    refuse_replace(monkeypatch, save, times=1)
    safety = saves.restore_backup(bak, save, loc=er())
    assert save.read_bytes() == earlier and safety in backups_of(save)


def test_a_replace_refused_for_good_keeps_the_save_and_the_safety_copy(world, tmp_path, monkeypatch):
    save, bak, _, current = world
    refuse_replace(monkeypatch, save)
    with pytest.raises(PermissionError):
        saves.restore_backup(bak, save, loc=er())
    (safety,) = [b for b in backups_of(save) if b != bak]
    assert save.read_bytes() == current and safety.read_bytes() == current


def test_a_replace_refused_for_good_leaves_no_temp_file(world, tmp_path, monkeypatch):
    save, bak, _, _ = world
    refuse_replace(monkeypatch, save)
    with pytest.raises(PermissionError):
        saves.restore_backup(bak, save, loc=er())
    assert strays(tmp_path) == []


def test_disk_full_leaves_the_save_untouched(world, tmp_path, monkeypatch):
    save, bak, _, current = world
    disk_full_on_tmp(monkeypatch, save)
    with pytest.raises(OSError, match="No space"):
        saves.restore_backup(bak, save, loc=er())
    assert save.read_bytes() == current


def test_disk_full_leaves_no_temp_file_and_no_backup(world, tmp_path, monkeypatch):
    save, bak, _, _ = world
    disk_full_on_tmp(monkeypatch, save)
    with pytest.raises(OSError):
        saves.restore_backup(bak, save, loc=er())
    assert strays(tmp_path) == [] and backups_of(save) == [bak]
