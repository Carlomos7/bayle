"""Move all leaves one Undo that reverses every move, last moved first."""

from pathlib import Path

from roundtable_souls.services import layout
from roundtable_souls.services import mods as mod_service


def test_move_all_records_one_multi_undo_last_first(monkeypatch):
    seen = []
    monkeypatch.setattr(
        mod_service,
        "move_into_launcher_folder",
        lambda loc, p: {"undo": {"type": "move-in", "profile": str(p), "name": p.stem, "operation": p.stem}},
    )
    monkeypatch.setattr(layout.run_logging, "set_undo", seen.append)
    assert layout.move_all(None, [Path("a.me3"), Path("b.me3")]) == 2
    assert len(seen) == 1 and seen[0]["type"] == "multi"
    assert [u["name"] for u in seen[0]["undos"]] == ["b", "a"]
