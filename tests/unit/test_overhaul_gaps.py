"""Setting a download up as an overhaul with the form (overhauls.basic): the gaps a live test found. Temporary
folders and synthetic files only."""

from pathlib import Path

import pytest

from roundtable_souls.overhauls import basic


def make_folder(root: Path, names: list[str]) -> Path:
    for n in names:
        (root / n).parent.mkdir(parents=True, exist_ok=True)
        (root / n).write_bytes(b"x")
    return root


def steps_of(folder: Path) -> list[dict]:
    config = basic.make(
        id="m", label="M", game="eldenring", basic=basic.propose(folder, game="eldenring"), folder=folder
    )
    return [s.model_dump(by_alias=True, exclude_unset=True) for s in config.builds[0].steps]


# ----------------------------------------------------------------------------- gap 1: a package folder named mod
def test_a_folder_holding_the_game_files_is_the_package_root(tmp_path):
    folder = make_folder(tmp_path / "payload", ["mod/chr/c0000.anibnd.dcx", "mod/regulation.bin", "M.dll", "M.ini"])
    steps = steps_of(folder)
    assert {"do": "merge", "file": "chr/c0000.anibnd.dcx", "patch": "mod/chr/c0000.anibnd.dcx"} in steps
    assert {"do": "params", "file": "regulation.bin", "patch": "mod/regulation.bin"} in steps
    assert {"do": "copy", "from": "M.dll", "to": "M.dll"} in steps


@pytest.mark.parametrize("name", ["mod", "Mod", "MOD", "payload/mod"])
def test_the_root_may_be_any_case_and_two_folders_deep(tmp_path, name):
    folder = make_folder(tmp_path / "dl", [f"{name}/chr/c0000.anibnd.dcx", "extras/readme.txt"])
    assert {"do": "merge", "file": "chr/c0000.anibnd.dcx", "patch": f"{name}/chr/c0000.anibnd.dcx"} in steps_of(folder)


def test_game_folders_at_the_top_next_to_a_mod_folder_are_refused_not_guessed(tmp_path):
    folder = make_folder(tmp_path / "dl", ["chr/a.anibnd.dcx", "mod/chr/b.anibnd.dcx"])
    with pytest.raises(ValueError, match="is in a folder named mod"):
        steps_of(folder)


def test_a_mod_folder_with_no_game_files_is_not_a_root(tmp_path):
    folder = make_folder(tmp_path / "dl", ["mod/notes.txt", "M.dll"])
    with pytest.raises(ValueError, match="is in a folder named mod"):
        steps_of(folder)


def test_a_folder_of_the_games_own_copies_deeper_down_is_not_the_root(tmp_path):
    folder = make_folder(tmp_path / "dl", ["mod/chr/a.anibnd.dcx", "settings/base/msg/engus/x.msgbnd.dcx"])
    assert {"do": "merge", "file": "chr/a.anibnd.dcx", "patch": "mod/chr/a.anibnd.dcx"} in steps_of(folder)


# ----------------------------------------------------------------------------- gap 2: a file placed at a game path
TALK = "script/talk/m00.talkesdbnd.dcx"


def placed_folder(root: Path) -> Path:
    return make_folder(
        root,
        [
            "mod/chr/a.anibnd.dcx",
            "settings/m00.talkesdbnd.dcx",
            f"settings/base/{TALK}",
            "settings/base/msg/engus/t.msgbnd.dcx",
            "M.dll",
        ],
    )


def test_a_loose_binder_named_like_a_copy_of_a_game_file_is_placed_there_and_the_copies_are_left_out(tmp_path):
    folder = placed_folder(tmp_path / "dl")
    b = basic.propose(folder, game="eldenring")
    assert b.place == {"settings/m00.talkesdbnd.dcx": TALK} and b.skip == ["settings/base"]
    steps = steps_of(folder)
    assert {"do": "merge", "file": TALK, "patch": "settings/m00.talkesdbnd.dcx"} in steps
    assert not any("base" in str(s) for s in steps)


def test_a_placed_binder_the_player_unticks_or_that_is_no_binder_is_copied_never_merged(tmp_path):
    folder = placed_folder(tmp_path / "dl")
    (folder / "settings/extra.bin").write_bytes(b"x")
    b = basic.propose(folder, game="eldenring")
    b = b.model_copy(
        update={
            "not_merged": ["settings/m00.talkesdbnd.dcx"],
            "place": {**b.place, "settings/extra.bin": "param/e.bin"},
        }
    )
    config = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder)
    copies = {s.from_: s.to for s in config.builds[0].steps if s.do == "copy"}
    assert copies["settings/m00.talkesdbnd.dcx"] == f"mod/{TALK}" and copies["settings/extra.bin"] == "mod/param/e.bin"


def test_a_placement_to_something_that_is_no_game_folder_or_twice_to_one_path_is_refused(tmp_path):
    folder = placed_folder(tmp_path / "dl")
    (folder / "settings/b.dcx").write_bytes(b"x")
    b = basic.propose(folder, game="eldenring")
    for place, why in (
        ({"settings/b.dcx": "nowhere/b.dcx"}, "not in one of the game's folders"),
        ({"settings/b.dcx": TALK, "settings/m00.talkesdbnd.dcx": TALK}, "both placed at"),
        ({"settings/gone.dcx": TALK}, "gone.dcx is not in the mod's folder"),  # the source moved or vanished
    ):
        with pytest.raises(ValueError, match=why):
            basic.make(id="m", label="M", game="eldenring", basic=b.model_copy(update={"place": place}), folder=folder)


def test_the_form_lists_placed_files_and_saving_it_keeps_them(tmp_path):
    from roundtable_souls.services import mod_configs

    folder = placed_folder(tmp_path / "dl")
    b = basic.propose(folder, game="eldenring")
    config = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder)
    choices = mod_configs.overhaul_choices({"config": config, "folder": folder})
    assert choices["place"] == [("settings/m00.talkesdbnd.dcx", TALK)]
    assert ("settings/m00.talkesdbnd.dcx", True) in choices["merged"]
    assert not any("base" in f for f, _on in choices["merged"] + choices["keep"])
    saved = mod_configs.with_basic(config, natives=[], keep=[], not_merged=[], place=dict(choices["place"]))
    assert saved.basic.place == b.place and saved.basic.skip == b.skip
