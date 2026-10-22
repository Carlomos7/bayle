"""B1: inner files are matched the way the game finds them, by archive kind (game.knowledge.binder_identity): by ID
in part archives, by name in positional ones, by name with a pairing check where the two agree; a kind not in the
table is decided from the game's copy. Plus the omission notice. Synthetic archives only."""

from fakegame import BND_HEADER

from bayle import formats
from bayle.merging import merger, record


def _archive(entries: list[tuple[str, int, bytes]]) -> bytes:
    rows = [formats.bnd4.Entry(f"N:\\GR\\data\\{name}", i, data) for name, i, data in entries]
    return formats.bnd4.write_bnd4(formats.bnd4.Bnd4(BND_HEADER, 0x2E, 0x74, True, 4, rows))


def _rows(data: bytes) -> list[tuple[str, int, bytes]]:
    return [(e.name.rsplit("\\", 1)[-1], e.id, e.data) for e in formats.bnd4.read_bnd4(data).entries]


GAME_PART = _archive([("BD_F_0000_L.tpf", 100, b"tex"), ("BD_F_0000_L.flver", 200, b"model")])
PART = "parts/bd_f_0000_l.partsbnd.dcx"


def test_part_archives_are_matched_by_id_so_a_renamed_mod_changes_rather_than_replaces():
    renamed = _archive([("BD_F_0000.tpf", 100, b"tex"), ("BD_F_0000.flver", 200, b"solo model")])
    r = merger.merge(GAME_PART, [("solo", renamed)], name=PART)
    # the unchanged slot stays the game's; the changed one is the mod's (the game finds both by ID)
    assert _rows(r.data) == [("BD_F_0000_L.tpf", 100, b"tex"), ("BD_F_0000.flver", 200, b"solo model")]
    assert list(r.changed) == ["n:/gr/data/bd_f_0000_l.flver"]  # named by the game's name for that slot
    assert not r.removed and not r.omissions and not r.clashes


def test_a_renamed_mod_and_a_normally_named_one_meet_on_the_same_slot():
    renamed = _archive([("BD_F_0000.tpf", 100, b"solo tex"), ("BD_F_0000.flver", 200, b"model")])
    named = _archive([("BD_F_0000_L.tpf", 100, b"other tex"), ("BD_F_0000_L.flver", 200, b"model")])
    r = merger.merge(GAME_PART, [("solo", renamed), ("other", named)], name=PART)
    assert r.clashes == {"n:/gr/data/bd_f_0000_l.tpf": ["solo", "other"]}
    ids = [i for _, i, _ in _rows(r.data)]
    assert ids == [100, 200]  # one inner file per slot: no duplicate IDs


def test_the_same_files_by_name_in_a_positional_archive():
    game = _archive([("a.esd", 0, b"a"), ("b.esd", 1, b"b")])
    mod = _archive([("a.esd", 0, b"a"), ("n.esd", 1, b"new"), ("b.esd", 2, b"b")])  # an added file shifts the IDs
    r = merger.merge(game, [("mod", mod)], name="script/talk/m00.talkesdbnd.dcx")
    assert list(r.changed) == ["n:/gr/data/n.esd"] and not r.removed and not r.omissions


def test_a_kind_not_in_the_table_is_decided_from_the_games_copy():
    slots = _archive([("x.tpf", 100, b"t"), ("x.flver", 200, b"m")])
    mod = _archive([("y.tpf", 100, b"t"), ("y.flver", 200, b"m2")])
    assert list(merger.merge(slots, [("mod", mod)], name="x.weirdbnd.dcx").changed) == ["n:/gr/data/x.flver"]
    grouped = _archive([("a.fxr", 0, b"a"), ("b.fxr", 1, b"b"), ("t.tpf", 100000, b"t"), ("u.tpf", 100001, b"u")])
    mod = _archive([("a.fxr", 0, b"a"), ("c.fxr", 1, b"c"), ("b.fxr", 2, b"b"), ("t.tpf", 100000, b"t"),
                    ("u.tpf", 100001, b"u")])  # fmt: skip
    r = merger.merge(grouped, [("mod", mod)], name="x.weirdbnd.dcx")
    assert list(r.changed) == ["n:/gr/data/c.fxr"] and not r.removed  # per-type base plus position: by name


def test_a_copy_that_repeats_an_id_is_matched_by_name_and_noted():
    mod = _archive([("BD_F_0000_L.tpf", 100, b"tex"), ("BD_F_0000_L.flver", 200, b"m"), ("extra.hkx", 200, b"x")])
    r = merger.merge(GAME_PART, [("mod", mod)], name=PART)
    assert "matched by name" in r.notes["/"][0] and "mod's copy" in r.notes["/"][0]
    assert sorted(r.changed) == ["n:/gr/data/bd_f_0000_l.flver", "n:/gr/data/extra.hkx"]


GAME_ANIM = _archive(
    [("a000_000001.hkx", 1_000_000_001, b"1"), ("a000_000002.hkx", 1_000_000_002, b"2"), ("x.hkx", 1_000_000, b"s")]
)
ANIM = "chr/c0000_a00_hi.anibnd.dcx"


def test_a_mod_lacking_the_games_animations_gets_a_notice():
    old = _archive([("a000_000001.hkx", 1_000_000_001, b"mine"), ("x.hkx", 1_000_000, b"s")])
    other = _archive([("a000_000001.hkx", 1_000_000_001, b"1"), ("x.hkx", 1_000_000, b"s")])
    r = merger.merge(GAME_ANIM, [("Sekiro", old), ("Other", other)], name=ANIM)
    assert r.omissions == {"": {"Sekiro": 1, "Other": 1}}
    assert r.omission_notices(ANIM) == [
        (ANIM, "Sekiro lacks 1 animation the current game uses (they won't play)"),
        (ANIM, "Other lacks 1 animation the current game uses (they won't play)"),
    ]
    generic = merger.merge(GAME_PART, [("m", _archive([("BD_F_0000_L.tpf", 100, b"t")]))], name=PART)
    assert generic.omission_notices(PART) == [
        (PART, "m lacks 1 inner file the current game has (left out of the result)")
    ]


def test_where_names_and_ids_agree_a_mod_whose_pairs_differ_is_warned_about():
    odd = _archive([("a000_000001.hkx", 5, b"1"), ("a000_000002.hkx", 1_000_000_002, b"2"), ("y.hkx", 1_000_000, b"s")])
    r = merger.merge(GAME_ANIM, [("odd", odd)], name=ANIM)
    (warning,) = r.warnings["/"]
    assert warning.startswith("odd's copy has 2 inner files whose name and ID don't match the game's")
    assert "n:/gr/data/a000_000001.hkx has ID 5, the game's 1000000001" in warning
    assert "ID 1000000 is n:/gr/data/y.hkx, the game's n:/gr/data/x.hkx" in warning


def test_the_merger_revision_changed_so_builds_rebuild_once():
    assert record.MERGER_REVISION == 6
