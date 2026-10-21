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


def test_the_files_table_lists_every_file_and_stores_only_what_differs(tmp_path):
    from roundtable_souls.services import mod_configs

    folder = placed_folder(tmp_path / "dl")
    b = basic.propose(folder, game="eldenring")
    config = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder)
    rows = {r["file"]: r for r in mod_configs.overhaul_choices({"config": config, "folder": folder})["files"]}
    assert (
        rows["settings/m00.talkesdbnd.dcx"]["action"] == "place"
        and rows["settings/m00.talkesdbnd.dcx"]["target"] == TALK
    )
    assert rows["settings/base/msg/engus/t.msgbnd.dcx"]["action"] == "leave"  # the older skip list is shown as a choice
    assert rows["mod/chr/a.anibnd.dcx"]["choices"] == ["merge", "whole", "leave"]
    values = {f: ("place:" + r["target"] if r["action"] == "place" else r["action"]) for f, r in rows.items()}
    values["mod/chr/a.anibnd.dcx"] = "whole"
    stored = mod_configs.files_to_store(list(rows.values()), values)
    assert stored["mod/chr/a.anibnd.dcx"] == "whole" and stored["settings/m00.talkesdbnd.dcx"] == f"place:{TALK}"
    assert "M.dll" not in stored  # the automatic choice is not stored
    saved = mod_configs.with_basic(config, natives=[], files=stored)
    assert not (saved.basic.keep or saved.basic.not_merged or saved.basic.place or saved.basic.skip)
    again = basic.make(id="m", label="M", game="eldenring", basic=saved.basic, folder=folder)
    assert {"do": "copy", "from": "mod/chr/a.anibnd.dcx", "to": "mod/chr/a.anibnd.dcx"} in [
        s.model_dump(by_alias=True, exclude_unset=True) for s in again.builds[0].steps
    ]


def test_a_files_choice_that_the_file_cannot_have_is_refused(tmp_path):
    folder = placed_folder(tmp_path / "dl")
    b = basic.propose(folder, game="eldenring")
    for files, why in (
        ({"mod/chr/a.anibnd.dcx": "keep"}, "can't be set to"),
        ({"mod/chr/a.anibnd.dcx": f"place:{TALK}"}, "in a game folder already"),
        ({"M.dll": "leave"}, "one of the DLLs"),
    ):
        with pytest.raises(ValueError, match=why):
            basic.make(id="m", label="M", game="eldenring", basic=b.model_copy(update={"files": files}), folder=folder)


def test_the_files_table_rows_are_choices_with_a_game_path_for_a_placed_file(tmp_path):
    from roundtable_souls.services import mod_configs
    from roundtable_souls.ui.pages.mod_configs.presenter import ModConfigsPresenter

    folder = placed_folder(tmp_path / "dl")
    config = basic.make(
        id="m", label="M", game="eldenring", basic=basic.propose(folder, game="eldenring"), folder=folder
    )
    choices = mod_configs.overhaul_choices({"config": config, "folder": folder})
    values = {"natives": choices["natives"], "files": {r["file"]: r["action"] for r in choices["files"]}}
    values["files"]["settings/m00.talkesdbnd.dcx"] = f"place:{TALK}"
    setup = {"config": config, "level": "basic", "verified": False}
    view = ModConfigsPresenter().overhaul(setup, choices, values, [], False)
    (files,) = [s for s in view["sections"] if s["title"] == "Files"]
    keys = [r["key"] for r in files["rows"]]
    assert "file:settings/m00.talkesdbnd.dcx" in keys and "target:settings/m00.talkesdbnd.dcx" in keys
    row = next(r for r in files["rows"] if r["key"] == "file:mod/chr/a.anibnd.dcx")
    assert row["kind"] == "choice" and [c["value"] for c in row["choices"]] == ["merge", "whole", "leave"]
    assert row["blurb"].startswith("By itself:")


def test_leaving_out_a_file_beside_a_dll_is_said_in_the_preview(world):
    from roundtable_souls.mods import overhaul_install

    folder = revive_shaped(world)
    b = basic.propose(folder, game="eldenring").model_copy(update={"files": {"RevivePrototype.ini": "leave"}})
    config = basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert p.ok and any("RevivePrototype.ini is left out" in n for n in p.notes)


# ----------------------------------------------------------------------------- a Revive-shaped download, end to end
@pytest.fixture
def world(tmp_path, monkeypatch):
    from test_overhaul_install import World

    return World(tmp_path, monkeypatch)


def revive_shaped(world) -> Path:
    """Generated here, no real mod files: game files inside mod/, two DLLs and their settings, a binder meant for a
    game path beside a folder of the game's own base copies, assets for its DLLs."""
    from fakegame import bnd, dcx
    from test_engine import GAME_CLIPS

    d = world.tmp / "Downloads" / "Revive Shaped Ä" / "payload"
    clips = dcx(bnd({**GAME_CLIPS, "mine.hkx": b"mine"}))
    for rel, data in {
        "mod/chr/c0000_a00_hi.anibnd.dcx": clips,
        "mod/regulation.bin": (world.game / "regulation.bin").read_bytes(),
        "RevivePrototype.dll": b"d",
        "RevivePrototype.ini": b"[a]\nb=1\n",
        "audio/hit.wav": b"w",
        "settings/m00.talkesdbnd.dcx": dcx(bnd({"talk.esd": b"x"})),
        "settings/base/script/talk/m00.talkesdbnd.dcx": dcx(bnd({"talk.esd": b"y"})),
    }.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_bytes(data)
    return d


def test_a_revive_shaped_download_installs_with_its_files_merged_placed_and_its_folder_in_the_layout(world):
    from roundtable_souls.mods import move_in, overhaul_install

    folder = revive_shaped(world)
    b = basic.propose(folder, game="eldenring")
    assert b.place and b.skip == ["settings/base"] and [n.file for n in b.natives] == ["RevivePrototype.dll"]
    config = basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)
    preview = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert preview.ok, preview.refusals
    overhaul_install.install_setup(preview, loc=world.loc)
    out = world.base / "revive"
    assert (out / "mod/chr/c0000_a00_hi.anibnd.dcx").is_file() and (out / "mod/regulation.bin").is_file()
    assert (out / f"mod/{TALK}").is_file()  # placed at its game path
    assert (out / "RevivePrototype.dll").is_file() and (out / "audio/hit.wav").is_file()
    assert not any("base" in p.as_posix() for p in out.rglob("*") if p.is_file())
    assert (out / "merge-report.txt").read_text(encoding="utf-8").startswith("Revive, built by")
    plan = move_in.plan(world.profile, world.loc)  # the overhaul's folder moves whole to the profile's root
    assert {u.dest_rel: u.src for u in plan.item.units}["revive"] == out


@pytest.mark.parametrize("name", ["packages", "natives", "builds", ".bayle"])
def test_an_overhaul_cannot_take_the_name_of_a_launcher_folder(tmp_path, name):
    folder = make_folder(tmp_path / "dl", ["mod/chr/a.anibnd.dcx"])
    with pytest.raises(ValueError, match="name the launcher uses"):
        basic.make(id=name, label="M", game="eldenring", basic=basic.propose(folder, game="eldenring"), folder=folder)


# ----------------------------------------------------------------------------- gap 5: saving applies the setup again
def test_saving_the_setup_applies_it_again_and_a_profile_that_refuses_is_skipped_and_said(world, monkeypatch):
    from test_overhaul_install import set_up

    from roundtable_souls import overhauls
    from roundtable_souls.mods import overhaul_install
    from roundtable_souls.overhauls import writer
    from roundtable_souls.services import mods as mod_service

    _folder, toml, _out = set_up(world)
    config = overhauls.read(toml)
    natives = [config.basic.natives[0].model_copy(update={"initializer": "Boot", "load_early": True})]
    saved = config.model_copy(update={"basic": config.basic.model_copy(update={"natives": natives})})
    writer.save_local(saved, expect=writer.sha256_of(toml), path=toml)
    assert "initializer" not in world.text()  # saving the file alone leaves the profile's entries as they were
    other = world.base / "other.me3"
    other.write_bytes(world.profile.read_bytes())
    monkeypatch.setattr(overhaul_install, "users_of", lambda p, c, e: [Path(p), other])  # `other` has no copy of it
    assert mod_service.reapply_overhaul_setup(world.profile, loc=world.loc) == ["my.me3"]
    entry = world.data()["natives"][-1]
    assert entry["initializer"] == {"function": "Boot"} and entry["load_early"] is True
