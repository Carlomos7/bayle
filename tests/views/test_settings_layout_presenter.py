"""The Settings > Locations layout words: field validation, the game-folder preview, the confirms and path cautions."""

from bayle.views import settings as sp


def test_names_are_validated_as_the_user_types():
    ok = {"pattern": "b-{game}", "packages": "packages", "natives": "natives", "shared": ".shared"}
    assert sp.name_errors(ok) == {}
    assert set(sp.name_errors({**ok, "packages": ""})) == {"packages"}
    assert set(sp.name_errors({**ok, "natives": "a/b"})) == {"natives"}
    assert set(sp.name_errors({**ok, "pattern": "plain"})) == {"pattern"}
    assert set(sp.name_errors({**ok, "shared": "packages"})) == {"shared"}  # two folders can't share a name


def test_the_game_folder_preview_fills_in_the_game_and_is_blank_for_a_bad_pattern():
    assert sp.game_preview("b-{game}", "eldenring") == "b-eldenring"
    assert sp.game_preview("x-{game}", "nightreign") == "x-nightreign"
    assert sp.game_preview("nothing") == ""


def test_path_cautions():
    gb = 1024**3
    assert sp.path_warnings(r"D:\Games\Bayle", gb, 10 * gb) == []
    assert len(sp.path_warnings(r"C:\Users\me\OneDrive\Bayle", gb, 10 * gb)) == 1
    assert "not enough free space" in sp.path_warnings(r"D:\x", 2 * gb, gb)[0]
    assert "very long" in sp.path_warnings("D:\\" + "a" * 250, gb, 10 * gb)[0]
    assert sp.path_warnings(r"D:\x", gb, None) == []


def test_the_confirms_say_what_moves_and_where_the_undo_is():
    title, changes, safety, apply = sp.relocate_confirm(r"D:\Bayle", 3, 2048, 10**12)
    assert title == r"Move your profiles and mods to D:\Bayle?"
    assert changes == ("3 profiles, 2.0 KB.",) and safety == "Undo in Activity." and apply == "Move"
    assert sp.relocate_confirm("D:/x", 1, 10, 10**12)[1] == ("1 profile, 10 B.",)
    title, changes, safety, apply = sp.rename_confirm({"Game folder": ("b-{game}", "x-{game}")})
    assert (
        changes == ("Game folder: b-{game} becomes x-{game}.",) and safety == "Undo in Activity." and apply == "Rename"
    )
    title, changes, _s, apply = sp.move_all_confirm(["a", "b"])
    assert changes == ("2 profiles move: a, b.",) and apply == "Move all"
    assert sp.move_all_confirm(["a"])[1] == ("1 profile moves: a.",)
