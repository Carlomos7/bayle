"""The layout settings (config.settings): defaults, what is refused and why, and a bad value in the file."""

from __future__ import annotations

import pytest

from bayle.modules.settings.models import LauncherSettings, folder_name_problem, game_folder_problem, layout_problems


def test_defaults_are_the_layout():
    s = LauncherSettings()
    assert (s.profiles_root, s.game_folder_pattern) == (None, "b-{game}")
    assert (s.packages_folder, s.natives_folder, s.shared_folder) == ("packages", "natives", ".shared")
    assert layout_problems() == {}


@pytest.mark.parametrize("name", ["", " x", "x ", "a/b", "a\b", "x.", "..", "con", "NUL", "builds", ".bayle", "x.me3"])
def test_unusable_folder_names(name):
    assert folder_name_problem(name)


@pytest.mark.parametrize("name", ["mods", ".shared", "Shared Mods", "dll-mods"])
def test_usable_folder_names(name):
    assert folder_name_problem(name) is None


def test_the_game_pattern_needs_game_once():
    assert game_folder_problem("b-{game}") is None and game_folder_problem("{game}-profiles") is None
    for bad in ("b-game", "{game}{game}", "b-{x}", "{game", "b-{game}/x"):
        assert game_folder_problem(bad), bad


def test_problems_name_the_field_and_a_repeat():
    got = layout_problems(profiles_root="relative", pattern="x", packages="mods", natives="MODS")
    assert set(got) == {"profiles_root", "game_folder_pattern", "natives_folder"}


def test_a_bad_value_in_the_file_falls_back_to_the_default(tmp_path):
    s = LauncherSettings.model_validate(
        {"game_folder_pattern": "nope", "packages_folder": "con", "profiles_root": "x", "shared_folder": "..s"}
    )
    assert (s.game_folder_pattern, s.packages_folder, s.profiles_root, s.shared_folder) == (
        "b-{game}",
        "packages",
        None,
        ".shared",
    )
    ok = LauncherSettings.model_validate({"profiles_root": str(tmp_path), "packages_folder": "mods"})
    assert ok.packages_folder == "mods" and ok.profiles_root == str(tmp_path)
