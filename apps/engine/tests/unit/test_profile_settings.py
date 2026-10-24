"""settings.json in .bayle beside a profile: the launcher's decisions about it, so they travel with the folder."""

import json
import shutil

from test_mod_merge import World

from bayle.config import settings_file
from bayle.mods import profile_settings
from bayle.mods import rebuild as merge


def test_settings_round_trip_and_keep_what_this_version_does_not_know(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text("")
    file = profile_settings.path(prof)
    file.parent.mkdir()
    file.write_text(
        json.dumps({"schema": 1, "future": {"x": 1}, "profiles": {"p.me3": {"later": 2}, "other.me3": {"y": 3}}})
    )
    profile_settings.update(prof, after_overlay=["a"])
    data = json.loads(file.read_text(encoding="utf-8"))
    assert data["future"] == {"x": 1} and data["profiles"]["other.me3"] == {"y": 3}
    assert data["profiles"]["p.me3"] == {"later": 2, "after_overlay": ["a"]}
    assert profile_settings.load(prof) == {"later": 2, "after_overlay": ["a"]}
    profile_settings.update(prof, after_overlay=None)
    assert profile_settings.load(prof) == {"later": 2}
    assert not file.with_name(file.name + ".tmp").exists()


def test_a_newer_schema_is_kept(tmp_path):
    prof = tmp_path / "p.me3"
    prof.write_text("")
    (tmp_path / "roundtable.json").write_text(json.dumps({"schema": 7, "profiles": {}}))
    profile_settings.update(prof, after_overlay=["a"])
    assert json.loads(profile_settings.path(prof).read_text())["schema"] == 7


def test_an_unreadable_file_is_left_alone_and_the_launchers_setting_is_used(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    file = w.base / "roundtable.json"
    file.write_text("{ not json", encoding="utf-8")
    note = merge.set_overlay_override(w.profile, w.winner)
    assert note and "launcher's own settings" in note
    assert file.read_text(encoding="utf-8") == "{ not json"
    assert profile_settings.problem(w.profile) and profile_settings.load(w.profile) == {}
    assert merge.overlay_mark(w.profile)["package"] == w.winner


def test_a_mark_from_before_3_10_moves_into_roundtable_json(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    settings_file.save_settings(parameter_overlays={merge._key(w.profile): {"package": str(w.winner), "rebuild": None}})
    mark = merge.overlay_mark(w.profile)
    assert mark["package"] == w.winner
    stored = profile_settings.load(w.profile)["overlay"]
    assert stored == {"package": "Merger/mod", "rebuild": None}  # relative: it travels with the folder
    merge.set_overlay_override(w.profile, None)
    assert profile_settings.load(w.profile)["overlay"] is None and merge.overlay_mark(w.profile) is None
    assert merge._key(w.profile) not in (settings_file.load_settings().parameter_overlays or {})


def test_a_copied_profile_folder_resolves_the_same_way(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)
    rebuild = w.base / "Merger" / "rebuild.json"
    rebuild.write_text("{}")
    merge.set_overlay_override(w.profile, w.winner, rebuild)
    copy = tmp_path / "elsewhere" / "er"
    shutil.copytree(w.base, copy)
    mark = merge.overlay_mark(copy / "p.me3")
    assert mark == {"package": copy / "Merger" / "mod", "rebuild": copy / "Merger" / "rebuild.json"}


def test_a_folder_that_cannot_be_written_falls_back_to_the_launchers_setting(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch)

    def refuse(*a, **k):
        raise PermissionError("read-only")

    monkeypatch.setattr(profile_settings, "update", refuse)
    note = merge.set_overlay_override(w.profile, w.winner)
    assert "read-only" in note
    assert merge.overlay_mark(w.profile)["package"] == w.winner


def test_the_file_of_launchers_before_3_23_is_copied_never_changed_and_the_newer_one_wins(tmp_path):
    """Safety (players' files): roundtable.json beside the profile is copied into .bayle/settings.json, left
    byte for byte as it was, and when an older launcher writes it again later, its newer content is what is read."""
    import os

    prof = tmp_path / "p.me3"
    prof.write_text("")
    legacy = tmp_path / "roundtable.json"
    legacy.write_text(json.dumps({"schema": 1, "keep": {"x": 1}, "profiles": {"p.me3": {"after_overlay": ["a"]}}}))
    before = legacy.read_bytes()
    assert profile_settings.load(prof) == {"after_overlay": ["a"]}
    new = json.loads(profile_settings.path(prof).read_text(encoding="utf-8"))
    assert new["version"] == 1 and new["keep"] == {"x": 1} and legacy.read_bytes() == before
    profile_settings.update(prof, after_overlay=["b"])
    assert profile_settings.load(prof) == {"after_overlay": ["b"]} and legacy.read_bytes() == before
    legacy.write_text(json.dumps({"schema": 1, "profiles": {"p.me3": {"after_overlay": ["older launcher"]}}}))
    later = profile_settings.path(prof).stat().st_mtime + 5
    os.utime(legacy, (later, later))
    assert profile_settings.load(prof) == {"after_overlay": ["older launcher"]}
