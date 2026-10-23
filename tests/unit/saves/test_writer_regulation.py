"""How saves.regulation.repair puts a rebuilt regulation block into a save through durable_write: the bytes, the backup
(taken only once the written copy verified), and what each failure leaves behind (the save untouched, no stray temp
file)."""

import re

import pytest
from synthetic_save import (
    OLD_MTIME_NS,
    backups_of,
    broken_block,
    build,
    corrupt_tmp,
    disk_full_on_tmp,
    healthy_block,
    made_up_regulation,
    put,
    refuse_replace,
    strays,
    with_block,
)

from bayle.saves import backups as save_backups
from bayle.saves import fix as F
from bayle.saves import regulation as R

REG = made_up_regulation()
HEADER = R.HEALTHY_HEADER


@pytest.fixture
def world(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(R, "log", lines.append)
    base = build({0: b"slot"})
    broken = with_block(base, broken_block())
    fixed = with_block(base, healthy_block(REG))
    assert not R.block_status(broken)[0] and R.block_status(fixed)[0]
    return put(tmp_path / "ER0000.sl2", broken), broken, fixed, lines


def test_success_rebuilds_the_block_and_backs_up_the_old_save(world, tmp_path):
    save, broken, fixed, lines = world
    assert R.repair(save, REG, HEADER) is True
    assert save.read_bytes() == fixed and R.block_status(save.read_bytes())[0]
    (bak,) = backups_of(save)
    assert re.fullmatch(r"ER0000\.sl2\.\d{8}-\d{6}\.bak", bak.name)
    assert bak.read_bytes() == broken and bak.stat().st_mtime_ns == OLD_MTIME_NS
    note = F.read_manifest(bak)
    assert note["action"] == "Before repairing for save editors"
    assert note["changes"] == ["regulation block rebuilt from regulation.bin"]
    assert lines[0].endswith("BROKEN") and lines[1:] == [f"  backup: {bak}", f"  wrote:  {save}"]
    assert strays(tmp_path) == []


def test_a_healthy_block_is_left_alone_unless_forced(world, tmp_path):
    save, _, fixed, lines = world
    put(save, fixed)
    assert R.repair(save, REG, HEADER) is False
    assert save.read_bytes() == fixed and backups_of(save) == [] and lines[-1] == "  nothing to do"
    assert R.repair(save, REG, HEADER, force=True) is True
    assert save.read_bytes() == fixed and len(backups_of(save)) == 1


def test_dry_run_writes_nothing_and_takes_no_backup(world, tmp_path):
    save, broken, _, lines = world
    assert R.repair(save, REG, HEADER, dry_run=True) is True
    assert save.read_bytes() == broken and backups_of(save) == [] and lines[-1] == "  would repair (dry run)"


def test_something_that_is_not_a_pc_save_is_skipped(world, tmp_path):
    save, *_ = world
    put(save, b"BND4" + bytes(100))
    assert R.repair(save, REG, HEADER) is False
    assert save.read_bytes() == b"BND4" + bytes(100) and backups_of(save) == []


def test_out_path_writes_elsewhere_with_no_backup_and_leaves_the_save(world, tmp_path):
    save, broken, fixed, lines = world
    out = tmp_path / "out" / "repaired.sl2"
    out.parent.mkdir()
    assert R.repair(save, REG, HEADER, out_path=out) is True
    assert out.read_bytes() == fixed and save.read_bytes() == broken
    assert backups_of(save) == [] and lines[-1] == f"  wrote:  {out}"
    assert strays(tmp_path) == []


def test_a_busy_backup_stops_the_write(world, tmp_path, monkeypatch):
    save, broken, *_ = world

    def busy(*_a, **_k):
        raise save_backups.BackupsBusy("busy")

    monkeypatch.setattr(F, "backup", busy)
    with pytest.raises(save_backups.BackupsBusy):
        R.repair(save, REG, HEADER)
    assert save.read_bytes() == broken and strays(tmp_path) == []


def test_a_failed_check_leaves_the_save_untouched(world, tmp_path, monkeypatch):
    # the error type is the switch's choice: any exception will do here
    save, broken, *_ = world
    corrupt_tmp(monkeypatch, save, R.UD11_OFF + 0x100, inplace=True)
    with pytest.raises(Exception):  # noqa: B017
        R.repair(save, REG, HEADER)
    assert save.read_bytes() == broken and strays(tmp_path) == []


def test_a_replace_refused_once_still_writes(world, tmp_path, monkeypatch):
    # today there is no replace at all; after the switch the retry covers it
    save, _, fixed, _ = world
    refuse_replace(monkeypatch, save, times=1)
    assert R.repair(save, REG, HEADER) is True
    assert save.read_bytes() == fixed


def test_a_replace_refused_for_good_keeps_the_old_save_and_its_backup(world, tmp_path, monkeypatch):
    save, broken, *_ = world
    refuse_replace(monkeypatch, save)
    with pytest.raises(PermissionError):
        R.repair(save, REG, HEADER)
    (bak,) = backups_of(save)
    assert save.read_bytes() == broken and bak.read_bytes() == broken and strays(tmp_path) == []


def test_disk_full_leaves_the_save_untouched(world, tmp_path, monkeypatch):
    save, broken, *_ = world
    disk_full_on_tmp(monkeypatch, save, inplace=True)
    with pytest.raises(OSError, match="No space"):
        R.repair(save, REG, HEADER)
    assert save.read_bytes() == broken and strays(tmp_path) == []
