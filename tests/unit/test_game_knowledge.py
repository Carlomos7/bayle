"""game.exe and game.knowledge: the exe's version picks the lists derived from it (data/games/*-exe-lists.json); the
binder-kind table says how the game finds an inner file. Synthetic executables only."""

import struct

from roundtable_souls.game import exe as game_exe
from roundtable_souls.game import knowledge


def _pe(version: tuple[int, int, int, int] | None) -> bytes:
    """A minimal Windows executable: headers, one .rsrc section holding a VS_FIXEDFILEINFO (or nothing)."""
    pe_at, optional = 0x40, 0xF0
    rsrc_at = 0x200
    rsrc = b"\0" * 16
    if version is not None:
        a, b, c, d = version
        rsrc += b"\xbd\x04\xef\xfe" + struct.pack("<IIII", 0x10000, (a << 16) | b, (c << 16) | d, 0)
    rsrc += b"\0" * 16
    head = bytearray(rsrc_at)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, pe_at)
    head[pe_at : pe_at + 4] = b"PE\0\0"
    struct.pack_into("<HH", head, pe_at + 4, 0x8664, 2)
    struct.pack_into("<H", head, pe_at + 20, optional)
    table = pe_at + 24 + optional
    head[table : table + 8] = b".text\0\0\0"
    head[table + 40 : table + 48] = b".rsrc\0\0\0"
    struct.pack_into("<II", head, table + 40 + 16, len(rsrc), rsrc_at)
    return bytes(head) + rsrc


def test_the_file_version_is_read_from_the_version_resource(tmp_path):
    exe = tmp_path / "eldenring.exe"
    exe.write_bytes(_pe((2, 7, 1, 0)))
    assert game_exe.file_version(exe) == "2.7.1.0"
    exe.write_bytes(_pe(None))
    assert game_exe.file_version(exe) is None
    exe.write_bytes(b"not a program")
    assert game_exe.file_version(exe) is None
    assert game_exe.file_version(tmp_path / "missing.exe") is None


def test_the_installed_builds_lists_are_used_and_others_say_how_sure_they_are(tmp_path, monkeypatch):
    exe = tmp_path / "eldenring.exe"
    exe.write_bytes(_pe((2, 7, 1, 0)))
    known = knowledge._exe_lists("eldenring").versions["2.7.1.0"]
    monkeypatch.setattr(game_exe, "sha256", lambda _p: known.exe_sha256)
    got = knowledge.exe_lists(exe)
    assert got.version == "2.7.1.0" and got.caveat == "" and got.lists.game == "1.17.1"
    monkeypatch.setattr(game_exe, "sha256", lambda _p: "0" * 64)
    assert "unverified build of 1.17.1" in knowledge.exe_lists(exe).caveat
    exe.write_bytes(_pe((2, 9, 0, 0)))
    later = knowledge.exe_lists(exe)
    assert later.version == "2.7.1.0" and "(2.9.0.0)" in later.caveat and "may be out of date" in later.caveat
    assert "could not be read" in knowledge.exe_lists(None).caveat


def test_the_shipped_lists_hold_what_the_checks_need():
    lists = knowledge._exe_lists("eldenring").versions["2.7.1.0"]
    assert len(lists.hks_env_ids) == 200 and len(lists.hks_act_ids) == 94
    assert len(lists.talk_command_ids) == 112 and len(lists.talk_function_ids) == 108
    assert {"env", "isenv", "act", "hkbFireEvent", "pcall", "math"} <= set(lists.hks_natives)
    assert set(lists.sources) >= {"hks_env_ids", "hks_act_ids", "talk_command_ids", "talk_function_ids", "emevd"}


def test_binder_kinds_come_from_the_table():
    assert knowledge.binder_kind("parts/bd_m_1000.partsbnd.dcx") == "partsbnd"
    assert knowledge.binder_kind("N:\\GR\\data\\chr\\c0000_a00_hi.anibnd") == "anibnd"
    assert knowledge.binder_kind("regulation.bin") == "bin" and knowledge.binder_kind("noext") == ""
    assert knowledge.binder_identity("partsbnd") == "id"
    assert knowledge.binder_identity("talkesdbnd") == "name"
    assert knowledge.binder_identity("anibnd") == "both"
    assert knowledge.binder_identity("unheardofbnd") is None
    omission = knowledge.binder_omission("anibnd")
    assert omission is not None and omission.many == "animations" and omission.effect == "they won't play"
