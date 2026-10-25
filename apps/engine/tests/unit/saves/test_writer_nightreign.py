"""How saves.nightreign.repair puts bytes on a live Nightreign save through durable_write: the bytes, the backup (taken
only once the written copy verified), and what each failure leaves behind (the save untouched, no stray temp file)."""

import re

import pytest
from synthetic_save import (
    OLD_MTIME_NS,
    backups_of,
    corrupt_tmp,
    disk_full_on_tmp,
    nightreign_good,
    nightreign_section_offset,
    nightreign_stale,
    put,
    refuse_replace,
    strays,
)

from bayle.adapters.saves import nightreign as nr
from bayle.modules.saves import backups as save_backups
from bayle.modules.saves import fix as F


@pytest.fixture
def stale(tmp_path):
    good = nightreign_good()
    old = nightreign_stale(good)
    return put(tmp_path / "NR0000.co2", old), old, good


def test_success_resigns_the_save_and_backs_up_the_old_one(stale, tmp_path):
    save, old, good = stale
    lines = []
    assert nr.repair(save, log=lines.append) is True
    assert save.read_bytes() == good
    (bak,) = backups_of(save)
    assert re.fullmatch(r"NR0000\.co2\.\d{8}-\d{6}\.bak", bak.name)
    assert bak.read_bytes() == old and bak.stat().st_mtime_ns == OLD_MTIME_NS
    note = F.read_manifest(bak)
    assert note["action"] == "Before repairing the Nightreign save" and note["changes"] == [
        "section checksums recomputed"
    ]
    assert lines == ["  checksum mismatch in section(s) 3", f"  backup: {bak}", f"  wrote:  {save}"]
    assert strays(tmp_path) == []


def test_a_garbled_regulation_is_restored_from_the_bak_beside_it(tmp_path):
    good = nightreign_good()
    garbled = nightreign_good(reg=b"XXXX" + bytes(12))
    save = put(tmp_path / "NR0000.co2", garbled)
    put(tmp_path / "NR0000.co2.bak", good)
    assert nr.repair(save) is True
    assert save.read_bytes() == good
    (bak,) = backups_of(save)
    assert bak.read_bytes() == garbled
    assert F.read_manifest(bak)["changes"] == [
        "regulation section restored from a healthy copy",
        "section checksums recomputed",
    ]
    assert strays(tmp_path) == []


def test_healthy_and_dry_run_write_nothing_and_take_no_backup(stale, tmp_path):
    save, old, _ = stale
    assert nr.repair(save, dry_run=True) is True
    assert save.read_bytes() == old and backups_of(save) == []
    healthy = put(tmp_path / "NR0001.co2", nightreign_good())
    assert nr.repair(healthy) is False
    assert backups_of(healthy) == []


def _break_tmp(monkeypatch, save, old):
    corrupt_tmp(monkeypatch, save, nightreign_section_offset(old, 0) + 20)


def test_a_failed_check_leaves_the_save_untouched(stale, tmp_path, monkeypatch):
    save, old, _ = stale
    _break_tmp(monkeypatch, save, old)
    with pytest.raises(nr.NightreignSaveError, match="checksums did not verify"):
        nr.repair(save)
    assert save.read_bytes() == old and strays(tmp_path) == []


def test_a_failed_check_takes_no_backup(stale, tmp_path, monkeypatch):
    save, old, _ = stale
    _break_tmp(monkeypatch, save, old)
    with pytest.raises(nr.NightreignSaveError):
        nr.repair(save)
    assert backups_of(save) == []


def test_a_busy_backup_stops_the_write(stale, tmp_path, monkeypatch):
    save, old, _ = stale

    def busy(*_a, **_k):
        raise save_backups.BackupsBusy("busy")

    monkeypatch.setattr(F, "backup", busy)
    with pytest.raises(save_backups.BackupsBusy):
        nr.repair(save)
    assert save.read_bytes() == old and strays(tmp_path) == []


def test_a_replace_refused_once_is_retried_and_written(stale, tmp_path, monkeypatch):
    save, _, good = stale
    refuse_replace(monkeypatch, save, times=1)
    assert nr.repair(save) is True
    assert save.read_bytes() == good


def test_a_replace_refused_for_good_keeps_the_old_save_and_its_backup(stale, tmp_path, monkeypatch):
    save, old, _ = stale
    refuse_replace(monkeypatch, save)
    with pytest.raises(PermissionError):
        nr.repair(save)
    (bak,) = backups_of(save)
    assert save.read_bytes() == old and bak.read_bytes() == old and strays(tmp_path) == []


def test_disk_full_leaves_the_save_untouched(stale, tmp_path, monkeypatch):
    save, old, _ = stale
    disk_full_on_tmp(monkeypatch, save)
    with pytest.raises(OSError, match="No space"):
        nr.repair(save)
    assert save.read_bytes() == old


def test_disk_full_leaves_no_temp_file(stale, tmp_path, monkeypatch):
    save, _, _ = stale
    disk_full_on_tmp(monkeypatch, save)
    with pytest.raises(OSError):
        nr.repair(save)
    assert strays(tmp_path) == []
