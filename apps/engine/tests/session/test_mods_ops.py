"""The Mods page's snapshot and read operations through the route functions, on a session whose Mods service is the
real one: no Qt, no window. Every profile is invented in the test's own folder."""

import pytest

from bayle.adapters.system.app_paths import data_dir
from bayle.modules.mods import shared_mods_page as library_service
from support import mods_profile, mods_session, refused, tree_state

make = mods_session


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


def test_the_snapshot_gives_the_facts_of_the_profile(profile):
    state = make().snapshot("mods", profile=str(profile))
    assert state.has_profile and state.profile == str(profile) and state.running is False
    facts = state.facts
    assert [e["name"] for e in facts.entries] == ["flora", "cloud", "a.dll"]
    assert [facts.entries[i]["name"] for i in facts.display["package"]] == ["flora", "cloud"]
    assert state.scan is not None and state.tool is None and state.rebuild_undo is None
    assert state.overhaul is None and state.seamless == "" and state.rename_code == ""
    assert state.folders == {0: "flora", 1: "cloud", 2: "natives"}


def test_reading_the_page_writes_nothing(profile):
    s = make()
    before = tree_state(profile.parent, data_dir())
    s.snapshot("mods", profile=str(profile))
    s.snapshot("mods", profile=str(profile), kind="me3", source="", no_profiles=True)
    s.run("mods.library_hint", {"profile": str(profile)})
    s.run("mods.drag", {"profile": str(profile), "index": 1})
    assert tree_state(profile.parent, data_dir()) == before


def test_no_profile_a_missing_one_or_no_game_gives_an_empty_state(tmp_path):
    s = make()
    none = s.snapshot("mods")
    assert (none.profile, none.has_profile, none.facts, none.no_profiles) == ("", False, None, False)
    assert s.snapshot("mods", no_profiles=True).no_profiles
    assert not s.snapshot("mods", profile=str(tmp_path / "x.me3")).has_profile
    other = tmp_path / "notes.txt"
    other.write_text("x", encoding="utf-8")
    assert not s.snapshot("mods", profile=str(other)).has_profile  # only a .me3 is a profile
    assert not mods_session(lambda: None).snapshot("mods", profile=str(other)).has_profile


def test_a_closed_notice_stays_closed_for_the_profile_in_the_session(profile):
    s = make()
    assert s.snapshot("mods", profile=str(profile)).closed == ()
    s.run("mods.close_notice", {"profile": str(profile), "key": "dll-folders"})
    assert s.snapshot("mods", profile=str(profile)).closed == ((str(profile), "dll-folders"),)
    assert make().snapshot("mods", profile=str(profile)).closed == ()  # per session


def test_the_library_hint_waits_for_enough_wasted_space(profile, monkeypatch):
    from bayle.modules.mods import shared_mods

    s, ref = make(), {"profile": str(profile)}
    monkeypatch.setattr(library_service, "duplicates", lambda loc: (1, 10))
    assert s.run("mods.library_hint", ref).enough is False
    monkeypatch.setattr(library_service, "duplicates", lambda loc: (3, shared_mods.HINT_BYTES + 1))
    hint = s.run("mods.library_hint", ref)
    assert (hint.mods, hint.enough, hint.closed) == (3, True, False)
    s.run("mods.close_notice", {**ref, "key": "library-hint"})
    assert s.run("mods.library_hint", ref).closed is True


def test_the_drag_table_ships_a_reason_for_every_drop_spot(profile):
    table = make().run("mods.drag", {"profile": str(profile), "index": 1})
    assert table.kind == "package"
    assert table.reasons == {0: "cloud must load after flora (set in its options)", 1: ""}
    assert refused(make(), "mods.drag", {"profile": str(profile), "index": 99}).code == "not_found"


def test_a_profile_the_engine_does_not_have_is_not_found_whatever_the_read(tmp_path):
    s, ghost = make(), str(tmp_path / "ghost.me3")
    for name, body in (
        ("mods.drag", {"index": 0}),
        ("mods.options", {"index": 0}),
        ("mods.rename_start", {"index": 0}),
        ("mods.versions", {}),
        ("mods.text", {}),
        ("mods.settings", {}),
        ("mods.unlisted", {"kind": "package"}),
        ("mods.check_trim_backups", {}),
    ):
        assert refused(s, name, {"profile": ghost, **body}).code == "not_found", name
    notes = tmp_path / "notes.txt"
    notes.write_text("secret", encoding="utf-8")
    assert refused(s, "mods.text", {"profile": str(notes)}).code == "not_found"  # not a .me3: never read
