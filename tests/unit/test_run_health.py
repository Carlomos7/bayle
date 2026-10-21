"""What a run tells the player: the game's exe changed since the last Play, and declared mod logs gained failure lines."""

import struct
from types import SimpleNamespace

import pytest

from roundtable_souls.game import catalog
from roundtable_souls.game import exe as game_exe
from roundtable_souls.overhauls.config import Health
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import run_health


def fake_exe(path, stamp=1788261400, image=0x5000000):
    """The smallest PE header that has a link time and an image size."""
    head = bytearray(0x200)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x80)
    head[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<I", head, 0x80 + 8, stamp)
    struct.pack_into("<H", head, 0x80 + 20, 0xF0)
    struct.pack_into("<I", head, 0x80 + 24 + 56, image)
    path.write_bytes(bytes(head))


def loc_for(folder):
    return SimpleNamespace(game=catalog.ELDEN_RING, game_dir=lambda: folder, game_exe_name=lambda: "eldenring.exe")


def test_build_stamp_reads_the_header_only(tmp_path):
    exe = tmp_path / "eldenring.exe"
    fake_exe(exe)
    assert game_exe.build_stamp(exe) == f"1788261400:{0x5000000}"
    assert game_exe.build_stamp(tmp_path / "missing.exe") is None
    exe.write_bytes(b"not an exe")
    assert game_exe.build_stamp(exe) is None


def test_game_update_notice(tmp_path):
    exe = tmp_path / "eldenring.exe"
    fake_exe(exe)
    loc = loc_for(tmp_path)
    assert run_health.game_update_notice(loc) is None  # the first run ever: nothing to compare with
    assert run_health.game_update_notice(loc) is None  # unchanged
    exe.touch()  # a Steam verify changes the time, not the build
    assert run_health.game_update_notice(loc) is None
    fake_exe(exe, stamp=1789655015)
    assert "updated since your last run" in (run_health.game_update_notice(loc) or "")
    assert run_health.game_update_notice(loc) is None  # said once
    assert run_health.game_update_notice(loc_for(tmp_path / "nowhere")) is None  # unreadable: nothing recorded


ENTRY = Health(log="Mod.log", fail=["initialization failed"], ok="initialized$")


def watched(tmp_path, entry=ENTRY):
    return [("Mod", tmp_path / entry.log, entry, run_health._size(tmp_path / entry.log))]


def test_only_lines_written_since_launch_are_read(tmp_path, monkeypatch):
    lines = []
    monkeypatch.setattr(run_logging, "log", lines.append)
    log = tmp_path / "Mod.log"
    log.write_text("old initialization failed\n", encoding="utf-8")
    w = watched(tmp_path)
    with log.open("a", encoding="utf-8") as f:
        f.write("started\nRevive initialization failed: Missing engine signature\n")
    assert run_health.report(w) == ["Mod: Revive initialization failed: Missing engine signature"]
    assert lines == ["warning: Mod: Revive initialization failed: Missing engine signature"]


def test_nothing_new_nothing_declared_or_no_log(tmp_path):
    log = tmp_path / "Mod.log"
    log.write_text("old initialization failed\n", encoding="utf-8")
    assert run_health.report(watched(tmp_path)) == []  # unchanged
    assert run_health.report(watched(tmp_path / "nowhere")) == []  # log missing
    assert run_health.report([]) == []  # nothing declared


def test_success_line_clears_earlier_failures_and_its_absence_is_reported(tmp_path):
    assert run_health.findings("Mod", "initialization failed\nall initialized\n", ENTRY) == []
    assert run_health.findings("Mod", "initialized\ninitialization failed\n", ENTRY) == ["Mod: initialization failed"]
    assert "never said it started" in run_health.findings("Mod", "loading\n", ENTRY)[0]


def test_a_log_started_over_is_read_whole(tmp_path):
    log = tmp_path / "Mod.log"
    log.write_text("x" * 500, encoding="utf-8")
    w = watched(tmp_path)
    log.write_text("initialization failed\n", encoding="utf-8")
    assert len(run_health.report(w)) == 1


def test_a_huge_log_is_read_from_its_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(run_health, "TAIL_BYTES", 1000)
    log = tmp_path / "Mod.log"
    w = [("Mod", log, ENTRY, None)]
    log.write_text("initialization failed\n" + "filler\n" * 1000 + "initialization failed again\n", encoding="utf-8")
    assert run_health.report(w) == ["Mod: initialization failed again"]


def test_health_patterns_must_compile():
    with pytest.raises(ValueError, match="regular expression"):
        Health(log="a.log", fail=["("])
