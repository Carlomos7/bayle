"""Pins how saves.transfer.copy_file puts a whole save over a live one, before it moves onto durable_write.
Tests marked xfail (strict) assert the SAFE behaviour that today's code does not have; the switch must flip them."""

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

from bayle.game import catalog as games
from bayle.saves import backups as save_backups
from bayle.saves import fix as F
from bayle.saves import library
from bayle.saves import transfer as T

ER = games.ELDEN_RING


@pytest.fixture
def world(tmp_path):
    old, new = build({0: b"old"}), build({0: b"new"})
    source = put(tmp_path / "from" / "ER0000.co2", new)
    target = put(tmp_path / "ER0000.sl2", old)
    return source, target, old, new


def test_success_writes_the_source_keeps_the_old_save_in_the_library_and_backs_it_up(world, tmp_path):
    source, target, old, new = world
    out = T.copy_file(source, target, ER, keep_as="before the copy")
    assert target.read_bytes() == new
    assert set(out) == {"kept", "backup", "signed"} and out["signed"] is False
    (bak,) = backups_of(target)
    assert out["backup"] == bak and re.fullmatch(r"ER0000\.sl2\.\d{8}-\d{6}\.bak", bak.name)
    assert bak.read_bytes() == old and bak.stat().st_mtime_ns == OLD_MTIME_NS
    note = F.read_manifest(bak)
    assert note["action"] == "Before copying ER0000.co2 over it" and note["changes"] == ["ER0000.co2"]
    kept = out["kept"]
    assert kept["name"] == "before the copy" and kept["from"] == "ER0000.sl2" and kept["format"] == "sl2"
    assert library.entry_path(tmp_path, kept).read_bytes() == old
    doc = library.load(tmp_path)
    assert [e["id"] for e in doc["entries"]] == [kept["id"]]
    assert [h["action"] for h in doc["history"]] == ["replaced"]
    assert strays(tmp_path) == []


def test_without_a_name_the_library_copy_gets_the_default_one(world, tmp_path):
    source, target, *_ = world
    out = T.copy_file(source, target, ER)
    assert re.fullmatch(r"ER0000\.sl2 · \d{4}-\d\d-\d\d \d\d:\d\d", out["kept"]["name"])


def test_a_missing_target_is_just_written(world, tmp_path):
    source, target, _, new = world
    target.unlink()
    assert T.copy_file(source, target, ER) == {"kept": None, "backup": None, "signed": False}
    assert target.read_bytes() == new and strays(tmp_path) == []


def test_a_busy_backup_stops_the_copy(world, tmp_path, monkeypatch):
    source, target, old, _ = world

    def busy(*_a, **_k):
        raise save_backups.BackupsBusy("busy")

    monkeypatch.setattr(F, "backup", busy)
    with pytest.raises(save_backups.BackupsBusy):
        T.copy_file(source, target, ER)
    assert target.read_bytes() == old and strays(tmp_path) == []


def test_today_the_library_copy_comes_first_and_stays_when_the_copy_fails(world, tmp_path, monkeypatch):
    # stays true after the switch: the outgoing library copy is a new file, not the live save
    source, target, old, _ = world
    monkeypatch.setattr(F, "backup", lambda *_a, **_k: (_ for _ in ()).throw(save_backups.BackupsBusy("busy")))
    with pytest.raises(save_backups.BackupsBusy):
        T.copy_file(source, target, ER, keep_as="kept anyway")
    (entry,) = library.load(tmp_path)["entries"]
    assert library.entry_path(tmp_path, entry).read_bytes() == old


def test_today_the_check_is_the_read_back_after_the_replace(world, tmp_path, monkeypatch):
    # A bad write to the temp file is only noticed after it replaced the save, and the backup was taken first.
    source, target, old, new = world
    corrupt_tmp(monkeypatch, target, 0x400)
    with pytest.raises(T.TransferError, match="did not read back the same"):
        T.copy_file(source, target, ER)
    assert target.read_bytes() not in (old, new)  # the bad bytes are in place
    (bak,) = backups_of(target)
    assert bak.read_bytes() == old


@pytest.mark.xfail(strict=True, reason="today: the bad temp file replaces the save and a backup was taken first")
def test_a_failed_check_leaves_the_save_untouched_and_takes_no_backup(world, tmp_path, monkeypatch):
    source, target, old, _ = world
    corrupt_tmp(monkeypatch, target, 0x400)
    with pytest.raises(T.TransferError):
        T.copy_file(source, target, ER)
    assert target.read_bytes() == old and backups_of(target) == [] and strays(tmp_path) == []


def test_a_read_back_mismatch_after_the_replace_is_reported(world, tmp_path, monkeypatch):
    # today and after the switch (after=): an error, the new file stays in place, the backup is kept
    source, target, old, new = world
    corrupt_after_replace(monkeypatch, target)
    with pytest.raises(T.TransferError, match="did not read back the same"):
        T.copy_file(source, target, ER)
    assert target.read_bytes() != new
    (bak,) = backups_of(target)
    assert bak.read_bytes() == old


@pytest.mark.xfail(strict=True, reason="today: one refused replace raises PermissionError (no retry)")
def test_a_replace_refused_once_is_retried_and_written(world, tmp_path, monkeypatch):
    source, target, _, new = world
    refuse_replace(monkeypatch, target, times=1)
    T.copy_file(source, target, ER)
    assert target.read_bytes() == new


def test_a_replace_refused_for_good_keeps_the_save_and_its_backup(world, tmp_path, monkeypatch):
    source, target, old, _ = world
    refuse_replace(monkeypatch, target)
    with pytest.raises(PermissionError):
        T.copy_file(source, target, ER)
    (bak,) = backups_of(target)
    assert target.read_bytes() == old and bak.read_bytes() == old


@pytest.mark.xfail(strict=True, reason="today: a refused replace leaves <save>.roundtable.tmp behind")
def test_a_replace_refused_for_good_leaves_no_temp_file(world, tmp_path, monkeypatch):
    source, target, *_ = world
    refuse_replace(monkeypatch, target)
    with pytest.raises(PermissionError):
        T.copy_file(source, target, ER)
    assert strays(tmp_path) == []


def test_disk_full_leaves_the_save_untouched(world, tmp_path, monkeypatch):
    source, target, old, _ = world
    disk_full_on_tmp(monkeypatch, target)
    with pytest.raises(OSError, match="No space"):
        T.copy_file(source, target, ER)
    assert target.read_bytes() == old


@pytest.mark.xfail(strict=True, reason="today: a failed temp write leaves <save>.roundtable.tmp behind")
def test_disk_full_leaves_no_temp_file(world, tmp_path, monkeypatch):
    source, target, *_ = world
    disk_full_on_tmp(monkeypatch, target)
    with pytest.raises(OSError):
        T.copy_file(source, target, ER)
    assert strays(tmp_path) == []
