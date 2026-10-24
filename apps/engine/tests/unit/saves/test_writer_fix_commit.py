"""How saves.fix._commit (reached through repair_checksums) puts bytes on a live save through durable_write: the bytes,
the backup (taken only once the written copy verified), the return value, and what each failure leaves behind (the
save untouched, no stray temp file)."""

import hashlib
import re

import pytest
from synthetic_save import (
    OLD_MTIME_NS,
    backups_of,
    build,
    corrupt_tmp,
    disk_full_on_tmp,
    put,
    refuse_replace,
    stale_slot,
    strays,
)

from bayle.saves import backups as save_backups
from bayle.saves import fix as F
from bayle.saves import layout as L

SLOT0_BODY = L.HEADER + 0x10


@pytest.fixture
def stale(tmp_path):
    """A save whose slot 1 MD5 is stale (slot 1 is flagged active), and the bytes repair must produce."""
    stale_bytes = stale_slot(build({0: b"hello"}, active=(0,)), 0)
    save = put(tmp_path / "ER0000.sl2", stale_bytes)
    fixed = bytearray(stale_bytes)
    fixed[L.HEADER : L.HEADER + 0x10] = hashlib.md5(stale_bytes[SLOT0_BODY : L.HEADER + F.SLOT_STRIDE]).digest()
    return save, stale_bytes, bytes(fixed)


def test_success_rewrites_the_slot_md5_and_backs_up_the_old_save(stale, tmp_path):
    save, old, new = stale
    lines = []
    out = F.repair_checksums(save, log=lines.append)
    assert save.read_bytes() == new
    (bak,) = backups_of(save)
    assert out == {"slots": [0], "ud10": False, "backup": bak}
    assert re.fullmatch(r"ER0000\.sl2\.\d{8}-\d{6}\.bak", bak.name)
    assert bak.read_bytes() == old
    assert bak.stat().st_mtime_ns == OLD_MTIME_NS
    note = F.read_manifest(bak)
    assert note["action"] == "Before fixing checksums" and note["changes"] == ["slot 1: checksum recomputed"]
    assert note["save"] == str(save)
    assert lines == ["  slot 1: checksum recomputed", f"  backup: {bak}"]
    assert strays(tmp_path) == []


def test_matching_checksums_write_nothing_and_take_no_backup(tmp_path):
    good = build({0: b"hello"}, active=(0,))
    save = put(tmp_path / "ER0000.sl2", good)
    assert F.repair_checksums(save) == {"slots": [], "ud10": False, "backup": None}
    assert save.read_bytes() == good and backups_of(save) == []


def test_a_failed_check_leaves_the_save_untouched_and_takes_no_backup(stale, tmp_path, monkeypatch):
    # today and after the switch: the check comes before the backup
    save, old, _ = stale
    corrupt_tmp(monkeypatch, save, SLOT0_BODY + 9)
    with pytest.raises(F.FixError, match="slot 1 checksum did not verify"):
        F.repair_checksums(save)
    assert save.read_bytes() == old and backups_of(save) == [] and strays(tmp_path) == []


def test_a_busy_backup_stops_the_write(stale, tmp_path, monkeypatch):
    save, old, _ = stale

    def busy(*_a, **_k):
        raise save_backups.BackupsBusy("busy")

    monkeypatch.setattr(F, "backup", busy)
    with pytest.raises(save_backups.BackupsBusy):
        F.repair_checksums(save)
    assert save.read_bytes() == old and strays(tmp_path) == []


def test_a_replace_refused_once_is_retried_and_written(stale, tmp_path, monkeypatch):
    save, _, new = stale
    refuse_replace(monkeypatch, save, times=1)
    out = F.repair_checksums(save)
    assert save.read_bytes() == new and out["backup"] == backups_of(save)[0]


def test_a_replace_refused_for_good_keeps_the_old_save_and_its_backup(stale, tmp_path, monkeypatch):
    save, old, _ = stale
    refuse_replace(monkeypatch, save)
    with pytest.raises(PermissionError):
        F.repair_checksums(save)
    (bak,) = backups_of(save)
    assert save.read_bytes() == old and bak.read_bytes() == old and strays(tmp_path) == []


def test_disk_full_leaves_the_save_untouched(stale, tmp_path, monkeypatch):
    save, old, _ = stale
    disk_full_on_tmp(monkeypatch, save)
    with pytest.raises(OSError, match="No space"):
        F.repair_checksums(save)
    assert save.read_bytes() == old and backups_of(save) == []


def test_disk_full_leaves_no_temp_file(stale, tmp_path, monkeypatch):
    save, _, _ = stale
    disk_full_on_tmp(monkeypatch, save)
    with pytest.raises(OSError):
        F.repair_checksums(save)
    assert strays(tmp_path) == []
