"""The Mods page's adoption service: the library's own adopt work and the settings are faked, so only the service's
decisions (what is offered, what is dismissed, what is logged and left for undo) are checked."""

from pathlib import Path
from types import SimpleNamespace

from roundtable_souls.mods import adopt as library_adopt
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import adopt


def setup_of_profiles(folder, profiles):
    return SimpleNamespace(folder=folder, profiles=[Path(p) for p in profiles])


def test_find_setups_is_the_library_listing(monkeypatch):
    listed = ["setup"]
    monkeypatch.setattr(library_adopt, "setups", lambda loc: listed if loc == "LOC" else [])
    assert adopt.find_setups("LOC") is listed


def test_setup_of_offers_a_setup_until_it_is_dismissed(monkeypatch, tmp_path):
    folder = tmp_path / "setups" / "mine"
    setup = setup_of_profiles(folder, [tmp_path / "profiles" / "a.ini"])
    monkeypatch.setattr(adopt, "find_setups", lambda loc: [setup])
    monkeypatch.setattr(adopt, "load_settings", lambda: SimpleNamespace(adopt_dismissed=[]))
    assert adopt.setup_of("LOC", tmp_path / "profiles" / "a.ini") == (setup, True)

    monkeypatch.setattr(adopt, "load_settings", lambda: SimpleNamespace(adopt_dismissed=[str(folder)]))
    assert adopt.setup_of("LOC", tmp_path / "profiles" / "a.ini") == (setup, False)


def test_setup_of_a_profile_not_in_any_setup_is_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(adopt, "find_setups", lambda loc: [setup_of_profiles(tmp_path, [tmp_path / "x.ini"])])
    monkeypatch.setattr(adopt, "load_settings", lambda: SimpleNamespace(adopt_dismissed=[]))
    assert adopt.setup_of("LOC", tmp_path / "other.ini") == (None, False)


def test_dismiss_adds_the_setup_folder_to_the_settings(monkeypatch, tmp_path):
    changes = []
    monkeypatch.setattr(adopt, "change_settings", changes.append)
    adopt.dismiss(setup_of_profiles(tmp_path / "mine", []))
    update = changes[0]
    assert update(SimpleNamespace(adopt_dismissed=["old"])) == {"adopt_dismissed": ["old", str(tmp_path / "mine")]}


def test_preview_passes_the_choices_to_the_library(monkeypatch):
    seen = {}

    def fake_preview(setup, *, loc, move_unused):
        seen.update(setup=setup, loc=loc, move_unused=move_unused)
        return "preview"

    monkeypatch.setattr(library_adopt, "preview", fake_preview)
    assert adopt.preview_adopt("S", loc="LOC", move_unused=["u"]) == "preview"
    assert seen == {"setup": "S", "loc": "LOC", "move_unused": ["u"]}


def test_adopt_logs_leaves_the_undo_record_and_reports_notes(monkeypatch, tmp_path):
    lines, undo = [], []
    setup = SimpleNamespace(folder=tmp_path / "Mine")
    preview = SimpleNamespace(setup=setup)
    out = {"profiles": ["p1"], "operation": "op-7", "notes": ["one file was skipped"]}
    monkeypatch.setattr(library_adopt, "adopt", lambda pv, *, loc, log: (log("step"), out)[1])
    monkeypatch.setattr(run_logging, "log", lines.append)
    monkeypatch.setattr(run_logging, "set_undo", undo.append)

    assert adopt.adopt(preview, loc="LOC") is out
    assert undo == [{"type": "library-adopt", "profile": "p1", "name": "Mine", "operation": "op-7"}]
    assert lines == ["step", "warning: one file was skipped", "done: Mine is in the library"]
