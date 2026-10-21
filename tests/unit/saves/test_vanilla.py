"""Removing mod items from a synthetic character. The scan of the game's item data is replaced by fakes (what each
entry, row and orphan is is set by the test), the parser returns the layout the test writes, and the backup is faked.
Nothing from the developer's saves or the game's item data is read."""

import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from roundtable_souls.saves import analyze as A
from roundtable_souls.saves import fix as F
from roundtable_souls.saves import layout as L
from roundtable_souls.saves import vanilla as V

GAME_IDS = {A.UNARMED_WEAPON, 100, 10000}  # what the fake catalog calls the game's own items
SAVE_SIZE = L.HEADER + F.SLOT_STRIDE + 0x400  # enough for slot 0's signed body and the rows the test writes
INV = 0x1000  # slot 0's held inventory: a count, then the entries (12 bytes each)
ROWS = {0: 0x2000, 1: 0x2020, 2: 0x2040, 3: 0x2060, 4: 0x2100}  # gaItem rows, by index


class FakeCatalog:
    names = None

    @classmethod
    def for_save(cls, parsed, items):
        return cls()

    def is_game_item(self, item_id):
        return item_id in GAME_IDS


def rows():
    return [
        {"gaitem_handle": 0x100, "item_id": 0x00F00001, "aow": 0, "pos": ROWS[0]},  # a mod weapon
        {"gaitem_handle": 0x200, "item_id": 0x10000005, "aow": 0, "pos": ROWS[1]},  # a mod armour piece, worn
        {"gaitem_handle": 0x300, "item_id": 100, "aow": 0x400, "pos": ROWS[2]},  # a game weapon with a mod ash
        {"gaitem_handle": 0x400, "item_id": 0x80000009, "aow": 0, "pos": ROWS[3]},  # the mod ash of war
        {"gaitem_handle": 0x500, "item_id": 0x00A00000, "aow": 0, "pos": ROWS[4]},  # nothing refers to it
    ]


def held_entries():
    return [
        {  # the mod weapon, in the held inventory
            "handle": 0x100,
            "item_id": 0x00F00001,
            "row": 0,
            "worn": False,
            "box": "inventory",
            "list": "common",
            "pos": 0,
            "name": "Foo Blade",
            "qty": 1,
            "source": "mod",
            "quick": [],
            "pouch": [],
        },
        {  # the mod armour piece is worn: it is kept, with the worn reason
            "handle": 0x200,
            "item_id": 0x10000005,
            "row": 1,
            "worn": True,
            "box": "inventory",
            "list": "common",
            "pos": 2,
            "name": "Foo Mail",
            "qty": 1,
            "source": "mod",
            "quick": [],
            "pouch": [],
        },
        {  # a mod good that has no row of its own
            "handle": 0x600,
            "item_id": 0x40000001,
            "row": None,
            "worn": False,
            "box": "inventory",
            "list": "common",
            "pos": 1,
            "name": "Mod Good",
            "qty": 3,
            "source": "",
            "quick": [],
            "pouch": [],
        },
    ]


def scan(slot, catalog):
    return {
        "held": held_entries(),
        "orphans": [{"handle": 0x500, "row": 4, "name": "Junk"}, {"handle": 0x400, "row": 3, "name": "Ash"}],
    }


@pytest.fixture
def analysis(monkeypatch):
    monkeypatch.setattr(A, "Catalog", FakeCatalog)
    monkeypatch.setattr(A, "scan_mod_items", scan)
    monkeypatch.setattr(A, "item_label", lambda item_id, names: (f"item {item_id}", "mod pack"))


def parsed_save(post: bool = False, *, still_held=False, still_foreign_row=False, still_foreign_orphan=False):
    """What the parser reads: before the restore, or after it (the zeroed entries and neutral rows)."""
    if post:  # the mod weapon and the mod good are zeroed; the worn armour piece stays
        common = [(0x100 if still_held else 0, 1, 0), (0, 0, 0), (0x200, 1, 0)]
    else:
        common = [(0x100, 1, 0), (0x600, 3, 0), (0x200, 1, 0)]
    gaitems = rows()
    if post:
        gaitems[0]["item_id"] = 0x00F00001 if still_foreign_row else A.UNARMED_WEAPON
        gaitems[4]["item_id"] = 0x00A00000 if still_foreign_orphan else A.UNARMED_WEAPON
    slot = {
        "pgd": {"name": "Alice", "level": 9},
        "inv_pos": INV,
        "storage_pos": 0x5000,
        "quick_pos": 0x6000,
        "pouch_pos": 0x6100,
        "equipped_items_pos": 0x6200,
        "ga_items": gaitems,
        "inventory": {"common": common, "key": []},
        "storage": {"common": [], "key": []},
    }
    return {
        "slots": [slot] + [{"pgd": {"name": ""}, "ga_items": []} for _ in range(9)],
        "ud10": {"active": [True] + [False] * 9},
        "slot_md5_ok": [True] * 10,
        "ud10_md5_ok": True,
    }


@pytest.fixture
def save_file(tmp_path, monkeypatch):
    """A save with the held entries and rows written where the layout says, so the restore edits real bytes."""
    path = tmp_path / "ER0000.sl2"
    data = bytearray(SAVE_SIZE)
    struct.pack_into("<I", data, INV, 3)  # three held entries: the mod weapon, the mod good, the worn armour
    struct.pack_into("<I", data, INV + 0x4, 0x100)
    struct.pack_into("<I", data, INV + 0x4 + 12, 0x600)
    struct.pack_into("<I", data, INV + 0x4 + 24, 0x200)
    data[ROWS[0] : ROWS[0] + 21] = bytes(range(1, 22))
    data[ROWS[4] : ROWS[4] + 21] = bytes(range(30, 51))
    path.write_bytes(bytes(data))

    state = {"post": {}}
    monkeypatch.setattr(L, "parse", lambda p: parsed_save(post=(".roundtable" in Path(p).name), **state["post"]))
    taken = []
    monkeypatch.setattr(F, "backup", lambda save, manifest=None: taken.append(manifest) or Path(str(save) + ".bak"))
    return SimpleNamespace(path=path, state=state, taken=taken)


# ----------------------------------------------------------------------------- helpers
def test_row_sizes_follow_the_item_kind():
    assert V.row_size(0) == 8  # an empty row
    assert V.row_size(0x00F00001) == 21  # weapon
    assert V.row_size(0x10000005) == 16  # armour
    assert V.row_size(0x80000009) == 8  # ash of war, goods


def test_the_neutral_rows_keep_their_length_and_handle_slot():
    assert len(V._neutral_row(0x00F00001)) == 21 - 4
    assert V._neutral_row(0x10000005) == struct.pack("<I", 0x10000000 | 10000) + V.NAKED_ROW_TAIL
    assert V._neutral_row(0x80000009) == b""  # those rows are emptied, not replaced


def test_inventory_offsets_for_the_held_and_chest_lists():
    slot = {"inv_pos": 0x1000, "storage_pos": 0x9000}
    held = V._inventory_offsets(slot, "inventory")
    assert held["common_count"] == 0x1000 and held["common"] == 0x1004
    assert held["key_count"] == 0x1004 + V.INV_COMMON_LEN * V.INV_ENTRY
    chest = V._inventory_offsets(slot, "storage")
    assert chest["common_count"] == 0x9000


# ----------------------------------------------------------------------------- plan
def test_the_plan_strips_what_is_free_and_keeps_what_is_worn_or_still_used(analysis):
    plan = V.plan_restore(parsed_save(), None)
    assert len(plan) == 1
    entry = plan[0]
    assert entry["slot"] == 0 and entry["name"] == "Alice"
    assert [e["name"] for e in entry["strip"]] == ["Foo Blade", "Mod Good"]
    assert [o["name"] for o in entry["orphans"]] == ["Junk"]  # the ash row is still kept by the game weapon
    reasons = sorted(b["why"] for b in entry["blocked"])
    assert reasons == ["ash", "worn"]
    assert V.restore_needed(plan)


def test_a_clean_save_has_no_plan(analysis):
    clean = parsed_save()
    clean["slots"][0]["ga_items"] = [{"gaitem_handle": 0x100, "item_id": 100, "aow": 0, "pos": 0x2000}]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(A, "scan_mod_items", lambda slot, catalog: {"held": [], "orphans": []})
        plan = V.plan_restore(clean, None)
    assert plan == [] and not V.restore_needed(plan)


def test_the_lines_for_the_confirm_dialog_name_each_part(analysis):
    plan = V.plan_restore(parsed_save(), None)
    lines = V.describe(plan)
    assert lines[0] == "Alice: remove 2 item(s): Foo Blade, Mod Good x3"
    assert lines[1] == "Alice: clear 1 leftover item row(s) nothing holds"
    assert any(line.startswith("Alice: KEPT (worn) Foo Mail") and "take it off in-game first" in line for line in lines)
    assert any("on a game weapon" in line and "remove it in-game first" in line for line in lines)


def test_a_selection_narrows_the_plan_per_slot(analysis):
    plan = V.plan_restore(parsed_save(), None)
    assert V.select_plan(plan, None) == plan
    assert V.select_plan(plan, {1: {"items": None}}) == []  # slot 1 is not in the selection: left alone
    narrowed = V.select_plan(plan, {0: {"items": {0x600}, "orphans": False}})
    assert [e["handle"] for e in narrowed[0]["strip"]] == [0x600]
    assert narrowed[0]["orphans"] == []


# ----------------------------------------------------------------------------- apply
def test_applying_writes_the_neutral_bytes_and_re_signs_the_slot(analysis, save_file, monkeypatch):
    lines = []
    result = V.apply_restore(save_file.path, log=lines.append, items=None)

    data = save_file.path.read_bytes()
    assert struct.unpack_from("<I", data, INV + 4)[0] == 0  # the mod weapon's entry is cleared
    assert data[INV + 4 : INV + 16] == bytes(12)
    assert data[INV + 16 : INV + 28] == bytes(12)  # the mod good's entry too
    assert struct.unpack_from("<I", data, INV)[0] == 1  # the count went down by both (three were held)
    assert data[ROWS[0] + 4 : ROWS[0] + 21] == V._neutral_row(0x00F00001)  # the weapon row is now "Unarmed"
    assert data[ROWS[4] + 4 : ROWS[4] + 21] == V._neutral_row(0x00A00000)  # the leftover row too
    assert result["done"] == [{"slot": 0, "name": "Alice", "removed": 2, "orphans": 1}]
    assert result["backup"] == Path(str(save_file.path) + ".bak")
    assert any("removed Foo Blade" in line for line in lines)
    assert any("kept Foo Mail (worn)" in line for line in lines)
    assert save_file.taken[0]["action"] == "Before removing mod items"
    slot_at = L.HEADER
    assert (
        data[slot_at : slot_at + 16] == __import__("hashlib").md5(data[slot_at + 16 : slot_at + F.SLOT_STRIDE]).digest()
    )


def test_a_save_with_nothing_to_do_is_left_alone(analysis, save_file, monkeypatch):
    monkeypatch.setattr(A, "scan_mod_items", lambda slot, catalog: {"held": [], "orphans": []})
    before = save_file.path.read_bytes()
    result = V.apply_restore(save_file.path, items=None)
    assert result["done"] == [] and result["backup"] is None  # the ash kept on a game weapon is only reported
    assert [b["why"] for b in result["blocked"]] == ["ash"]
    assert save_file.path.read_bytes() == before


def test_a_restore_that_leaves_an_entry_behind_is_not_written(analysis, save_file):
    save_file.state["post"] = {"still_held": True}
    before = save_file.path.read_bytes()
    with pytest.raises(F.FixError, match="still in the inventory"):
        V.apply_restore(save_file.path, items=None)
    assert save_file.path.read_bytes() == before


def test_a_restore_that_leaves_a_foreign_row_is_not_written(analysis, save_file):
    save_file.state["post"] = {"still_foreign_row": True}
    with pytest.raises(F.FixError, match="still foreign"):
        V.apply_restore(save_file.path, items=None)


def test_a_restore_that_leaves_a_foreign_orphan_is_not_written(analysis, save_file):
    save_file.state["post"] = {"still_foreign_orphan": True}
    with pytest.raises(F.FixError, match="leftover row Junk still foreign"):
        V.apply_restore(save_file.path, items=None)


def test_a_selection_removes_only_the_chosen_entries(analysis, save_file):
    result = V.apply_restore(save_file.path, items=None, selection={0: {"items": {0x600}, "orphans": False}})
    assert result["done"] == [{"slot": 0, "name": "Alice", "removed": 1, "orphans": 0}]
    data = save_file.path.read_bytes()
    assert struct.unpack_from("<I", data, INV + 4)[0] == 0x100  # the mod weapon is not in the selection
