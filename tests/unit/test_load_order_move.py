"""Moving an entry in the load order (the Mods page's drag, technical specification §8.10 "Drag rules"): the block
moves in the file with its own comments; a move me3 would undo (a load_after / load_before decides the place) is
refused with the dependency named; nothing goes below the mod that must stay last, which never moves; switched-off
entries keep their place and can be moved; the write goes through the profile writer (a Version is kept)."""

from pathlib import Path

from roundtable_souls.mods import history, order
from roundtable_souls.services import profile_mods
from roundtable_souls.services.mods import profile_entries
from support import er

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "# Flora: the grass\n[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    "[[packages]]\nid = \"birds\"\npath = 'mod/birds'\nenabled = false\n\n"
    "# Cloud keeps its comment\n[[packages]]\nid = \"cloud\"\npath = 'mod/cloud'\n\n"
    "[[natives]]\npath = 'natives/a.dll'\n\n"
    "[[natives]]\npath = 'natives/b.dll'\n"
)


def profile(tmp_path, text=PROFILE) -> Path:
    p = tmp_path / "my.me3"
    p.write_text(text, encoding="utf-8")
    for d in ("mod/flora", "mod/birds", "mod/cloud", "natives"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    return p


def names(p: Path, kind: str = "package") -> list[str]:
    text = p.read_text(encoding="utf-8")
    by_index = {e["index"]: e["name"] for e in profile_entries(p)}
    return [by_index[r["index"]] for r in order.display_order(p, text, kind)]


def index_of(p: Path, name: str) -> int:
    return next(e["index"] for e in profile_entries(p) if e["name"] == name)


def test_a_moved_block_takes_its_comments_with_it(tmp_path):
    p = profile(tmp_path)
    move = order.move(p, p.read_text(encoding="utf-8"), "package", index_of(p, "cloud"), 0)
    assert move.text is not None and move.problem == ""
    p.write_text(move.text, encoding="utf-8")
    assert names(p) == ["cloud", "flora", "birds"]
    text = p.read_text(encoding="utf-8")
    assert text.index("# Cloud keeps its comment") < text.index('id = "cloud"') < text.index("# Flora: the grass")
    assert text.count("[[packages]]") == 3 and text.count("[[natives]]") == 2


def test_a_switched_off_entry_keeps_its_place_and_can_move(tmp_path):
    p = profile(tmp_path)
    assert names(p) == ["flora", "birds", "cloud"]  # birds is off: still shown in its place
    move = order.move(p, p.read_text(encoding="utf-8"), "package", index_of(p, "birds"), 2)
    p.write_text(move.text or "", encoding="utf-8")
    assert names(p) == ["flora", "cloud", "birds"]


def test_moving_to_the_end_and_natives(tmp_path):
    p = profile(tmp_path)
    move = order.move(p, p.read_text(encoding="utf-8"), "native", index_of(p, "a.dll"), 1)
    p.write_text(move.text or "", encoding="utf-8")
    assert names(p, "native") == ["b.dll", "a.dll"]
    assert p.read_text(encoding="utf-8").rstrip().endswith("path = 'natives/a.dll'")


def test_a_move_a_dependency_would_undo_is_refused_and_names_it(tmp_path):
    text = PROFILE.replace(
        "[[packages]]\nid = \"cloud\"\npath = 'mod/cloud'\n",
        '[[packages]]\nid = "cloud"\npath = \'mod/cloud\'\nload_after = [{ id = "flora", optional = false }]\n',
    )
    p = profile(tmp_path, text)
    move = order.move(p, text, "package", index_of(p, "cloud"), 0)
    assert move.text is None
    assert move.problem == "cloud must load after flora (set in its options)" and move.decided_by == "cloud"
    move = order.move(p, text, "package", index_of(p, "flora"), 2)  # the other way round: flora below cloud
    assert move.text is None and move.problem == "cloud must load after flora (set in its options)"
    assert move.decided_by == "cloud"


def test_nothing_goes_below_the_mod_that_must_stay_last_and_it_never_moves(tmp_path):
    p = profile(tmp_path)
    text = p.read_text(encoding="utf-8")
    tgt = {"folder": tmp_path / "mod" / "cloud", "own": [], "name": "cloud"}
    refused = order.move(p, text, "package", index_of(p, "cloud"), 0, tgt)
    assert refused.text is None and refused.problem == "cloud stays last: it cannot be moved"
    below = order.move(p, text, "package", index_of(p, "flora"), 2, tgt)
    assert below.text is None and below.problem == "cloud stays last; nothing can load after it"
    fine = order.move(p, text, "package", index_of(p, "flora"), 1, tgt)
    assert fine.text is not None


def test_a_drop_where_it_already_is_changes_nothing(tmp_path):
    p = profile(tmp_path)
    move = order.move(p, p.read_text(encoding="utf-8"), "package", index_of(p, "flora"), 0)
    assert move.text is None and move.problem == ""


def test_the_move_is_written_through_the_profile_writer(tmp_path):
    p = profile(tmp_path)
    before = p.read_bytes()
    plan = profile_mods.move_entry(p, "package", index_of(p, "cloud"), 0, loc=er())
    assert plan.text is not None and names(p) == ["cloud", "flora", "birds"]
    kept = history.versions(p)
    assert kept and kept[0]["path"].read_bytes() == before  # a Version of the profile as it was
    refused = profile_mods.move_entry(p, "package", index_of(p, "cloud"), 0, loc=er())
    assert refused.text is None  # already there: nothing written
