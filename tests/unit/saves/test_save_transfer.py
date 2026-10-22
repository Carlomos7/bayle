"""Moving characters and whole files between saves. The save parser is replaced by a small one that reads the
synthetic bytes these tests write (a name, level and Steam ID per slot, the active flags and the account ID), so the
real layout parser and the game's own saves are never read. Every file lives in the test's temporary folder."""

import hashlib
import struct
from pathlib import Path

import pytest

from bayle.game import catalog as games
from bayle.saves import fix as save_fix
from bayle.saves import layout as L
from bayle.saves import library
from bayle.saves import transfer as T

UD10 = L.HEADER + 10 * save_fix.SLOT_STRIDE  # where the profile summary (USER_DATA_10) starts
ACTIVE = UD10 + 0x10  # ten active flags, then the profile summary entries
ACCOUNT = UD10 + 0x20  # the account's Steam ID
SIZE = UD10 + 0x60010 + 0x100  # enough for every slot and the signed profile summary


def slot_body(i: int) -> int:
    return T._slot_body(i)


def make_save(path: Path, slots: dict[int, tuple[str, int, int]], active: set[int], account: int) -> Path:
    """A synthetic save: slot i (0-based) holds (name, level, Steam ID); the rest of each slot is zeros."""
    data = bytearray(SIZE)
    for i, (name, level, steam) in slots.items():
        b = slot_body(i)
        data[b : b + 16] = name.encode().ljust(16, b"\0")
        struct.pack_into("<I", data, b + 0x10, level)
        struct.pack_into("<Q", data, b + 0x18, steam)
        data[b + 0x100] = 0x40 + i  # a marker the copy must carry over
    for i in range(10):
        data[ACTIVE + i] = 1 if i in active else 0
        data[ACTIVE + 10 + i * library.SUMMARY_STRIDE] = 0x80 + i
        save_fix._sign_slot(data, i)
    struct.pack_into("<Q", data, ACCOUNT, account)
    save_fix._sign_ud10(data, UD10)
    path.write_bytes(bytes(data))
    return path


def parse_synthetic(path):
    """L.parse for the synthetic layout: the same keys the transfer code reads."""
    data = Path(path).read_bytes()
    if len(data) != SIZE:
        raise L.ParseError("not a synthetic save")
    slots, ok = [], []
    for i in range(10):
        b = slot_body(i)
        ok.append(hashlib.md5(data[b : b + L.SLOT_SIZE]).digest() == data[b - 0x10 : b])
        slots.append(
            {
                "steam_id_pos": b + 0x18,
                "steam_id": struct.unpack_from("<Q", data, b + 0x18)[0],
                "pgd": {
                    "name": data[b : b + 16].rstrip(b"\0").decode(),
                    "level": struct.unpack_from("<I", data, b + 0x10)[0],
                },
            }
        )
    active = [bool(data[ACTIVE + i]) for i in range(10)]
    return {
        "slots": slots,
        "slot_md5_ok": ok,
        "unreadable": [],
        "ud10": {
            "active": list(active),
            "active_raw": list(active),
            "active_pos": ACTIVE,
            "steam_id": struct.unpack_from("<Q", data, ACCOUNT)[0],
        },
        "ud10_pos": UD10,
        "ud10_md5_ok": hashlib.md5(data[UD10 + 0x10 : UD10 + 0x60010]).digest() == data[UD10 : UD10 + 0x10],
    }


def characters_of(path, game=None):
    parsed = parse_synthetic(path)
    return [
        {"slot": i + 1, "name": s["pgd"]["name"], "level": s["pgd"]["level"], "seconds": 1000 + i}
        for i, s in enumerate(parsed["slots"])
        if parsed["ud10"]["active"][i]
    ]


@pytest.fixture
def synthetic(monkeypatch):
    """The parser and the character list are the synthetic ones; the backup is faked (no backups folder)."""
    monkeypatch.setattr(L, "parse", parse_synthetic)
    monkeypatch.setattr(library, "characters", characters_of)
    taken = []

    def fake_backup(save, manifest=None):
        taken.append((Path(save), manifest))
        return Path(str(save) + ".bak")

    monkeypatch.setattr(save_fix, "backup", fake_backup)
    return taken


# ----------------------------------------------------------------------------- compare
def test_compare_sorts_each_slot_into_one_change(monkeypatch):
    listings = {
        "a.sl2": [
            {"slot": 1, "name": "Ann", "level": 10, "seconds": 100},
            {"slot": 2, "name": "Bo", "level": 20, "seconds": 500},
            {"slot": 3, "name": "Cy", "level": 5, "seconds": 50},
            {"slot": 4, "name": "Di", "level": 9, "seconds": 90},
        ],
        "b.sl2": [
            {"slot": 1, "name": "Ann", "level": 10, "seconds": 100},
            {"slot": 2, "name": "Bo", "level": 19, "seconds": 400},
            {"slot": 4, "name": "Eve", "level": 9, "seconds": 90},
            {"slot": 5, "name": "Fi", "level": 6, "seconds": 90},
        ],
    }
    monkeypatch.setattr(library, "characters", lambda path, game=None: listings[path.name])
    rows = T.compare(Path("a.sl2"), Path("b.sl2"), games.ELDEN_RING)
    assert [(r["slot"], r["change"]) for r in rows] == [
        (1, "same"),
        (2, "ahead in a"),
        (3, "a only"),
        (4, "different"),
        (5, "b only"),
    ]
    assert rows[2]["b"] is None and rows[4]["a"] is None


def test_compare_calls_the_b_side_ahead_when_its_time_is_more(monkeypatch):
    listings = {
        "a.sl2": [{"slot": 1, "name": "Ann", "level": 6, "seconds": 50}],
        "b.sl2": [{"slot": 1, "name": "Ann", "level": 6, "seconds": 90}],
    }
    monkeypatch.setattr(library, "characters", lambda path, game=None: listings[path.name])
    assert T.compare(Path("a.sl2"), Path("b.sl2"), games.ELDEN_RING)[0]["change"] == "ahead in b"


def test_hours_round_to_a_tenth_under_ten_and_to_whole_hours_above():
    assert T.hours(3600 * 2.5) == "2.5 h"
    assert T.hours(3600 * 12.4) == "12 h"


# ----------------------------------------------------------------------------- whole files
@pytest.fixture
def whole_file(monkeypatch):
    calls = {"check": [], "add": [], "signed": False}
    monkeypatch.setattr(library, "check_whole", lambda data, game: calls["check"].append(data))
    monkeypatch.setattr(library, "signed_for_account", lambda data, target, game: (data, calls["signed"]))
    monkeypatch.setattr(library, "default_name", lambda target, game: "Default name")

    def fake_add(folder, target, name, game, action):
        calls["add"].append((name, action))
        return ("kept", name)

    monkeypatch.setattr(library, "add", fake_add)
    monkeypatch.setattr(save_fix, "backup", lambda save, manifest: ("bak", manifest["action"]))
    return calls


def test_a_file_cannot_be_copied_over_itself(tmp_path, whole_file):
    save = tmp_path / "ER0000.sl2"
    save.write_bytes(b"x")
    with pytest.raises(T.TransferError, match="same file"):
        T.copy_file(save, save, games.ELDEN_RING)


def test_copying_into_a_new_file_keeps_nothing(tmp_path, whole_file):
    source, target = tmp_path / "src.sl2", tmp_path / "new.sl2"
    source.write_bytes(b"save bytes")
    assert T.copy_file(source, target, games.ELDEN_RING) == {"kept": None, "backup": None, "signed": False}
    assert target.read_bytes() == b"save bytes"
    assert whole_file["add"] == []
    assert not (tmp_path / "new.sl2.roundtable.tmp").exists()


def test_copying_over_a_file_keeps_it_then_backs_it_up(tmp_path, whole_file):
    whole_file["signed"] = True
    source, target = tmp_path / "src.sl2", tmp_path / "old.sl2"
    source.write_bytes(b"new save")
    target.write_bytes(b"old save")
    result = T.copy_file(source, target, games.ELDEN_RING, keep_as="Keep me")
    assert result == {
        "kept": ("kept", "Keep me"),
        "backup": ("bak", "Before copying src.sl2 over it"),
        "signed": True,
    }
    assert whole_file["add"] == [("Keep me", "replaced")]
    assert target.read_bytes() == b"new save"


def test_the_default_name_is_used_when_none_is_given(tmp_path, whole_file):
    source, target = tmp_path / "src.sl2", tmp_path / "old.sl2"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    T.copy_file(source, target, games.ELDEN_RING)
    assert whole_file["add"] == [("Default name", "replaced")]


def test_a_file_that_fails_the_whole_file_check_is_not_copied(tmp_path, whole_file, monkeypatch):
    def refuse(data, game):
        raise T.TransferError("not a save")

    monkeypatch.setattr(library, "check_whole", refuse)
    source, target = tmp_path / "src.sl2", tmp_path / "old.sl2"
    source.write_bytes(b"junk")
    target.write_bytes(b"old save")
    with pytest.raises(T.TransferError, match="not a save"):
        T.copy_file(source, target, games.ELDEN_RING)
    assert target.read_bytes() == b"old save"


# ----------------------------------------------------------------------------- one character
def test_a_character_plan_says_what_it_replaces_and_which_slots_are_free(tmp_path, synthetic):
    source = make_save(tmp_path / "src.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    target = make_save(tmp_path / "dst.sl2", {1: ("Bob", 3, 222)}, {1}, account=222)
    plan = T.plan_character_copy(source, 1, target, 2)
    assert plan["character"]["name"] == "Alice"
    assert plan["replaces"]["name"] == "Bob"
    assert plan["steam_id_changes"] is True
    assert (plan["source_steam_id"], plan["target_steam_id"]) == (111, 222)
    assert plan["free_slots"] == [1, 3, 4, 5, 6, 7, 8, 9, 10]


def test_copying_within_one_file_to_another_slot_keeps_the_account(tmp_path, synthetic):
    save = make_save(tmp_path / "ER0000.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    plan = T.plan_character_copy(save, 1, save, 2)
    assert plan["steam_id_changes"] is False
    assert plan["replaces"] is None


@pytest.mark.parametrize(("src", "dst"), [(0, 1), (1, 0), (11, 1)])
def test_slots_run_from_one_to_ten(tmp_path, synthetic, src, dst):
    save = make_save(tmp_path / "ER0000.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    with pytest.raises(T.TransferError, match="Slots run from 1 to 10"):
        T.plan_character_copy(save, src, save, dst)


def test_a_file_that_does_not_parse_is_refused(tmp_path, synthetic):
    bad = tmp_path / "bad.sl2"
    bad.write_bytes(b"not a save")
    good = make_save(tmp_path / "good.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    with pytest.raises(T.TransferError, match="Could not read the saves"):
        T.plan_character_copy(bad, 1, good, 1)


def test_an_empty_source_slot_is_refused(tmp_path, synthetic):
    source = make_save(tmp_path / "src.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    target = make_save(tmp_path / "dst.sl2", {}, set(), account=222)
    with pytest.raises(T.TransferError, match="has no character"):
        T.plan_character_copy(source, 2, target, 1)


def test_an_unreadable_source_slot_is_refused(tmp_path, synthetic, monkeypatch):
    source = make_save(tmp_path / "src.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    target = make_save(tmp_path / "dst.sl2", {}, set(), account=222)

    def unreadable(path):
        parsed = parse_synthetic(path)
        parsed["unreadable"] = [0]
        return parsed

    monkeypatch.setattr(L, "parse", unreadable)
    with pytest.raises(T.TransferError, match="cannot read"):
        T.plan_character_copy(source, 1, target, 1)


def test_a_character_cannot_be_copied_onto_itself(tmp_path, synthetic):
    save = make_save(tmp_path / "ER0000.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    with pytest.raises(T.TransferError, match="onto itself"):
        T.plan_character_copy(save, 1, save, 1)


def test_copy_character_moves_the_character_in_and_signs_it(tmp_path, synthetic):
    source = make_save(tmp_path / "src.sl2", {0: ("Alice", 7, 111)}, {0}, account=111)
    target = make_save(tmp_path / "dst.sl2", {1: ("Bob", 3, 222)}, {1}, account=222)
    result = T.copy_character(source, 1, target, 2)

    parsed = parse_synthetic(target)
    assert parsed["slots"][1]["pgd"] == {"name": "Alice", "level": 7}
    assert parsed["slots"][1]["steam_id"] == 222  # the target's account, not the source's
    assert parsed["ud10"]["active"][1] is True
    assert all(parsed["slot_md5_ok"]) and parsed["ud10_md5_ok"]
    assert parsed["slots"][1]["pgd"]["name"] == "Alice"
    assert result["replaces"]["name"] == "Bob"
    assert result["backup"] == Path(str(target) + ".bak")
    action = synthetic[0][1]["action"]
    assert action == "Before copying a character in"
    assert any("Bob" in line for line in synthetic[0][1]["changes"])
    assert not (tmp_path / "dst.sl2.roundtable.tmp").exists()
