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
