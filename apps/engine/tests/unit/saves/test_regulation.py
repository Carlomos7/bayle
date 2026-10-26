"""The regulation block repair on synthetic saves: a PC save is a temporary file of the right size, its block is
built from a fake regulation, and the save backup is faked. No real save or regulation.bin is read."""

import hashlib
import sys

import pytest

from bayle.modules.saves import regulation as reg_mod
from bayle.modules.saves.regulation import (
    BLOCK,
    FILE_SIZE,
    HEALTHY_HEADER,
    UD11_OFF,
    UD11_SIZE,
    block_status,
    is_pc_save,
    load_regulation,
    plausible_regulation,
    rebuild_block,
    repair,
)

# 2 MiB of regulation bytes with no trailing zero, so a block read back is the same bytes
REG = bytes(range(256)) * 0x2000


def pc_save(block: bytes) -> bytes:
    """A save of the right size: the magic, then the given regulation block where it lives."""
    data = bytearray(FILE_SIZE)
    data[:4] = b"BND4"
    data[UD11_OFF : UD11_OFF + UD11_SIZE] = block
    return bytes(data)


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(reg_mod, "log", out.append)
    return out


@pytest.fixture
def backups(monkeypatch):
    taken = []

    def fake_backup(save):
        taken.append(save)
        return save.with_suffix(".bak")

    monkeypatch.setattr(reg_mod, "backup", fake_backup)
    return taken


def healthy_save() -> bytes:
    return pc_save(rebuild_block(REG, HEALTHY_HEADER))


def broken_save() -> bytes:
    return pc_save(b"\x37" * UD11_SIZE)  # garbage: its checksum matches nothing


def test_only_a_save_of_the_right_size_with_the_magic_is_a_pc_save():
    assert is_pc_save(healthy_save())
    assert not is_pc_save(healthy_save()[:-1])
    assert not is_pc_save(b"XXXX" + healthy_save()[4:])


def test_a_plausible_regulation_is_between_the_bounds():
    assert plausible_regulation(REG)
    assert not plausible_regulation(b"x" * 0x100000)  # not longer than 1 MiB
    assert not plausible_regulation(b"x" * BLOCK)  # no room for the block's own padding


def test_a_regulation_bin_is_read_as_is_with_the_standard_header(tmp_path):
    path = tmp_path / "regulation.bin"
    path.write_bytes(REG)
    assert load_regulation(path) == (REG, HEALTHY_HEADER)


def test_a_healthy_save_gives_back_its_regulation_and_header(tmp_path):
    path = tmp_path / "ER0000.sl2"
    path.write_bytes(healthy_save())
    reg, header = load_regulation(path)
    assert reg == REG
    assert header == HEALTHY_HEADER


def test_block_status_tells_healthy_from_broken():
    healthy, used, header = block_status(bytearray(healthy_save()))
    assert healthy and header == HEALTHY_HEADER and used == len(REG)

    healthy, _, header = block_status(bytearray(broken_save()))
    assert not healthy and header != HEALTHY_HEADER


def test_a_block_with_a_wrong_checksum_is_not_healthy():
    data = bytearray(healthy_save())
    data[UD11_OFF + 0x30] ^= 0xFF  # a byte changed under the checksum
    assert not block_status(data)[0]


def test_a_rebuilt_block_is_signed_and_the_right_size():
    block = rebuild_block(REG, HEALTHY_HEADER)
    assert len(block) == UD11_SIZE
    assert block[:16] == hashlib.md5(block[16:]).digest()


def test_backup_is_the_save_fix_backup_with_its_note(monkeypatch, tmp_path):
    from bayle.modules.saves import fix as save_fix

    seen = []
    monkeypatch.setattr(save_fix, "backup", lambda save, manifest: seen.append((save, manifest)) or "done")
    assert reg_mod.backup(tmp_path / "ER0000.sl2") == "done"
    save, manifest = seen[0]
    assert save == tmp_path / "ER0000.sl2"
    assert manifest["action"] == "Before repairing for save editors"


def test_a_file_that_is_not_a_pc_save_is_skipped(tmp_path, lines, backups):
    path = tmp_path / "other.sl2"
    path.write_bytes(b"not a save")
    assert repair(path, REG, HEALTHY_HEADER) is False
    assert lines == ["  skip: not a PC Elden Ring save (magic/size mismatch)"]
    assert backups == []


def test_a_healthy_block_is_left_alone_unless_forced(tmp_path, lines, backups):
    path = tmp_path / "ER0000.sl2"
    path.write_bytes(healthy_save())
    assert repair(path, REG, HEALTHY_HEADER) is False
    assert lines[-1] == "  nothing to do"
    assert backups == []
    assert repair(path, REG, HEALTHY_HEADER, force=True) is True
    assert backups == [path]


def test_a_dry_run_reports_and_writes_nothing(tmp_path, lines, backups):
    path = tmp_path / "ER0000.sl2"
    original = broken_save()
    path.write_bytes(original)
    assert repair(path, REG, HEALTHY_HEADER, dry_run=True) is True
    assert lines[-1] == "  would repair (dry run)"
    assert path.read_bytes() == original and backups == []


def test_a_broken_block_is_backed_up_then_rebuilt_in_place(tmp_path, lines, backups):
    path = tmp_path / "ER0000.sl2"
    path.write_bytes(broken_save())
    assert repair(path, REG, HEALTHY_HEADER) is True
    assert backups == [path]
    assert block_status(bytearray(path.read_bytes()))[0]
    assert lines[-1] == f"  wrote:  {path}"


def test_an_output_path_leaves_the_original_and_takes_no_backup(tmp_path, lines, backups):
    path, out = tmp_path / "ER0000.sl2", tmp_path / "fixed.sl2"
    original = broken_save()
    path.write_bytes(original)
    assert repair(path, REG, HEALTHY_HEADER, out_path=out) is True
    assert backups == []
    assert path.read_bytes() == original
    assert block_status(bytearray(out.read_bytes()))[0]


def run_main(monkeypatch, argv, *, game_running=False, regulation=None, saves=()):
    """The command line with a fake install: its saves and regulation.bin come from the test."""
    from bayle.adapters.system import logging as run_logging
    from bayle.modules.games import locate

    class FakeLocations:
        def __init__(self, game):
            self.game = game

        def game_running(self):
            return game_running

        def save_files(self):
            return list(saves)

        def regulation_bin(self):
            return regulation

    monkeypatch.setattr(locate, "Locations", FakeLocations)
    monkeypatch.setattr(run_logging, "start_log", lambda *args: None)
    monkeypatch.setattr(sys, "argv", ["repair_regulation", *argv])
    reg_mod.main()


def test_the_command_line_dry_runs_the_given_save(monkeypatch, tmp_path, lines, backups):
    path, source = tmp_path / "ER0000.sl2", tmp_path / "regulation.bin"
    path.write_bytes(broken_save())
    source.write_bytes(REG)
    run_main(monkeypatch, [str(path), "--regulation", str(source), "--dry-run"])
    assert lines[-1] == "done: 1 would be repaired"
    assert backups == []


def test_the_command_line_refuses_a_running_game(monkeypatch, tmp_path):
    source = tmp_path / "regulation.bin"
    source.write_bytes(REG)
    with pytest.raises(SystemExit) as stop:
        run_main(monkeypatch, [str(tmp_path / "x.sl2"), "--regulation", str(source)], game_running=True)
    assert stop.value.code == 2


def test_the_command_line_needs_a_regulation_it_can_find(monkeypatch, tmp_path):
    path = tmp_path / "ER0000.sl2"
    path.write_bytes(healthy_save())
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [str(path)], regulation=None)


def test_the_command_line_rejects_a_misplaced_regulation(monkeypatch, tmp_path):
    source = tmp_path / "regulation.bin"
    source.write_bytes(b"x" * 1000)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [str(tmp_path / "x.sl2"), "--regulation", str(source)])


def test_the_command_line_refuses_out_with_several_saves(monkeypatch, tmp_path):
    source = tmp_path / "regulation.bin"
    source.write_bytes(REG)
    saves = [str(tmp_path / "a.sl2"), str(tmp_path / "b.sl2")]
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [*saves, "-o", str(tmp_path / "c.sl2"), "--regulation", str(source)])
