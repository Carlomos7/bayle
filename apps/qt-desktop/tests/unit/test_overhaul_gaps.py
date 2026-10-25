"""Setting a download up as an overhaul with the form (overhauls.basic): the gaps a live test found. Temporary
folders and synthetic files only."""

from pathlib import Path

import pytest
from bayle.overhauls import basic


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
    ):
        with pytest.raises(ValueError, match=why):
            basic.make(id="m", label="M", game="eldenring", basic=b.model_copy(update={"place": place}), folder=folder)


def test_the_files_table_lists_every_file_and_stores_only_what_differs(tmp_path):
    from bayle.services import mod_configs

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
    from bayle.services import mod_configs

    from bayle_qt.pages.mod_configs.presenter import ModConfigsPresenter

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
    from bayle.mods import overhaul_install

    folder = revive_shaped(world)
    b = basic.propose(folder, game="eldenring").model_copy(update={"files": {"RevivePrototype.ini": "leave"}})
    config = basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert p.ok and any("RevivePrototype.ini is left out" in n for n in p.notes)


# ----------------------------------------------------------------------------- a Revive-shaped download, end to end
@pytest.fixture
def world(tmp_path, monkeypatch):
    from overhaul_world import World

    return World(tmp_path, monkeypatch)


def revive_shaped(world) -> Path:
    """Generated here, no real mod files: game files inside mod/, two DLLs and their settings, a binder meant for a
    game path beside a folder of the game's own base copies, assets for its DLLs."""
    from fakegame import bnd, dcx
    from overhaul_world import GAME_CLIPS

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
    from bayle.mods import move_in, overhaul_install

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
    from bayle.mods import overhaul_install
    from bayle.overhauls import recipes, writer
    from bayle.services import mods as mod_service
    from overhaul_world import set_up

    _folder, toml, _out = set_up(world)
    config = recipes.read(toml)
    natives = [config.basic.natives[0].model_copy(update={"initializer": "Boot", "load_early": True})]
    saved = config.model_copy(update={"basic": config.basic.model_copy(update={"natives": natives})})
    writer.save_local(saved, expect=writer.sha256_of(toml), path=toml)
    assert "initializer" not in world.text()  # saving the file alone leaves the profile's entries as they were
    other = world.base / "other.me3"
    other.write_bytes(world.profile.read_bytes())
    monkeypatch.setattr(overhaul_install, "users_of", lambda p, c, e: [Path(p), other])  # `other` has no copy of it
    assert mod_service.reapply_overhaul_setup(world.profile, "mixed-mod", loc=world.loc) == ["my.me3"]
    entry = world.data()["natives"][-1]
    assert entry["initializer"] == {"function": "Boot"} and entry["load_early"] is True


def test_applying_a_saved_setup_leaves_a_hand_edited_file_as_it_is(world):
    from bayle.services import mods as mod_service
    from overhaul_world import set_up

    _folder, toml, _out = set_up(world)
    toml.write_text("# my own note" + chr(10) + toml.read_text(encoding="utf-8"), encoding="utf-8")
    before = toml.read_bytes()
    assert mod_service.reapply_overhaul_setup(world.profile, "mixed-mod", loc=world.loc) == ["my.me3"]
    assert toml.read_bytes() == before


# ----------------------------------------------------------------------------- gap 3: texts from a JSON file
def texts_setup(world, texts: dict[str, str]):
    from bayle.overhauls.config import BasicText

    folder = revive_shaped(world)
    (folder / "settings/en.json").write_text('{"99002000": "Session settings"}', encoding="utf-8")
    (folder / "settings/ru.json").write_text('{"99002000": "ru"}', encoding="utf-8")
    entry = BasicText(file="msg/{each}/menu_dlc02.msgbnd.dcx", table="eventtextfortalk.fmg", texts=texts)
    b = basic.propose(folder, game="eldenring").model_copy(update={"texts": [entry]})
    return folder, basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)


def test_texts_from_json_files_are_set_in_each_languages_binder_and_the_files_are_not_copied(world):
    from bayle.mods import overhaul_install

    folder, config = texts_setup(world, {"rusru": "settings/ru.json", "*": "settings/en.json"})
    (step,) = [s for s in config.builds[0].steps if s.do == "text"]
    assert step.each is not None and step.each.game == "languages"
    assert not any(s.do == "copy" and s.from_.endswith((".json",)) for s in config.builds[0].steps)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert p.ok, p.refusals
    overhaul_install.install_setup(p, loc=world.loc)
    out = world.base / "revive/mod/msg"
    assert (out / "engus/menu_dlc02.msgbnd.dcx").is_file() and (out / "rusru/menu_dlc02.msgbnd.dcx").is_file()


def test_a_language_with_no_texts_is_left_alone_and_said(world):
    from bayle.mods import overhaul_install

    folder, config = texts_setup(world, {"rusru": "settings/ru.json"})
    overhaul_install.install_setup(
        overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc), loc=world.loc
    )
    assert (world.base / "revive/mod/msg/rusru/menu_dlc02.msgbnd.dcx").is_file()
    assert not (world.base / "revive/mod/msg/engus/menu_dlc02.msgbnd.dcx").exists()
    report = (world.base / "revive/merge-report.txt").read_text(encoding="utf-8")
    assert "msg/engus/menu_dlc02.msgbnd.dcx: the mod has no texts for this language" in report


def test_malformed_texts_stop_the_install_and_write_nothing(world):
    from bayle.mods import overhaul_install

    folder, config = texts_setup(world, {"*": "settings/en.json"})
    (folder / "settings/en.json").write_text('{"not a number": "x"}', encoding="utf-8")
    before = world.profile.read_bytes()
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    with pytest.raises(Exception, match="not a JSON object of text IDs"):
        overhaul_install.install_setup(p, loc=world.loc)
    assert world.profile.read_bytes() == before and not (world.base / "revive").exists()


def test_a_texts_file_that_is_too_big_stops_the_install(world, monkeypatch):
    from bayle.mods import engine, overhaul_install

    folder, config = texts_setup(world, {"*": "settings/en.json"})
    before = world.profile.read_bytes()
    monkeypatch.setattr(engine, "MAX_TEXTS_BYTES", 5)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    with pytest.raises(Exception, match="larger than"):
        overhaul_install.install_setup(p, loc=world.loc)
    assert world.profile.read_bytes() == before


def test_a_texts_file_the_mod_does_not_have_is_refused_and_the_form_keeps_the_texts(world):
    from bayle.overhauls.config import BasicText
    from bayle.services import mod_configs

    folder, config = texts_setup(world, {"*": "settings/en.json"})
    gone = BasicText(file="msg/engus/m.msgbnd.dcx", table="t.fmg", texts={"*": "settings/none.json"})
    with pytest.raises(ValueError, match="none.json is not in the mod's folder"):
        basic.make(
            id="revive",
            label="R",
            game="eldenring",
            folder=folder,
            basic=config.basic.model_copy(update={"texts": [gone]}),
        )
    saved = mod_configs.with_basic(config, natives=[], files={})
    assert saved.basic.texts == config.basic.texts


def two_profiles(world):
    """The set-up overhaul in my.me3 and in a second profile beside it (its own copy of the download), the saved
    config changed so applying it changes both."""
    import shutil

    from bayle.mods import overhaul_install
    from bayle.overhauls import recipes, writer
    from overhaul_world import set_up

    _folder, toml, _out = set_up(world)
    other = world.base / "other.me3"
    other.write_bytes(world.profile.read_bytes())
    config = recipes.read(toml)
    for p in (world.profile, other):  # `other` gets the launcher's files for it, as if it had been set up too
        src = overhaul_install.places(world.profile, config.id, world.loc)
        dst = overhaul_install.places(p, config.id, world.loc)
        if p != world.profile:
            shutil.copytree(src.library.root, dst.library.root, dirs_exist_ok=True)
    natives = [config.basic.natives[0].model_copy(update={"initializer": "Boot"})]
    saved = config.model_copy(update={"basic": config.basic.model_copy(update={"natives": natives})})
    writer.save_local(saved, expect=writer.sha256_of(toml), path=toml)
    return other


def test_one_undo_takes_back_every_profile_the_save_changed(world, monkeypatch):
    from bayle.mods import overhaul_install, undo
    from bayle.platform import logging as run_logging
    from bayle.services import mods as mod_service

    other = two_profiles(world)
    monkeypatch.setattr(overhaul_install, "users_of", lambda p, c, e: [Path(p), other])
    before = {p: p.read_bytes() for p in (world.profile, other)}
    got: list[dict] = []
    monkeypatch.setattr(run_logging, "set_undo", lambda d: got.append(d))
    done = mod_service.reapply_overhaul_setup(world.profile, "mixed-mod", loc=world.loc)
    assert done == ["my.me3", "other.me3"] and got[0]["type"] == "overhaul-reapply"
    assert got[0]["others"] == [] and len(got[-1]["others"]) == 1  # set after each profile: a crash keeps an Undo
    assert all(b"Boot" in p.read_bytes() for p in before)
    assert undo.available(got[-1])
    undo.run(got[-1], lambda s: None, loc=world.loc)
    assert {p: p.read_bytes() for p in before} == before


def test_a_disabled_overhaul_stays_disabled_when_the_setup_is_applied(world):
    from bayle.overhauls import recipes, writer
    from bayle.services import mods as mod_service
    from overhaul_world import set_up

    _folder, toml, _out = set_up(world)
    text = world.text().replace('id = "mixed-mod"', 'id = "mixed-mod"\nenabled = false')
    text = text.replace("MixedMod.dll'", "MixedMod.dll'\nenabled = false")
    world.profile.write_text(text, encoding="utf-8")
    config = recipes.read(toml)
    writer.save_local(config, expect=writer.sha256_of(toml), path=toml)
    mod_service.reapply_overhaul_setup(world.profile, "mixed-mod", loc=world.loc)
    after = world.data()
    package = next(p for p in after["packages"] if p.get("id") == "mixed-mod")
    native = next(n for n in after["natives"] if "MixedMod" in n["path"])
    assert package.get("enabled") is False and native.get("enabled") is False


# ----------------------------------------------------------------------------- gap 4: a matched setup is pre-filled
def open_install(world, monkeypatch, folder):
    """An open install in the engine, the way the dialog holds it: (the service, its OpenedInstall)."""
    from bayle.services import mods as mod_service
    from bayle.services.mod_install import ModInstallService
    from bayle.work.events import EventBus
    from bayle.work.jobs import JobManager

    monkeypatch.setattr(mod_service, "overhaul_preview_on", lambda loc: True)  # the Settings switch
    service = ModInstallService(JobManager(EventBus(), spawn=lambda run, name=None: run()), lambda: world.loc)
    return service, service.open(world.profile, folder)


def test_a_download_matching_a_saved_setup_shows_its_dll_options_and_files_and_installs_the_changes(world, monkeypatch):
    from bayle.overhauls import recipes
    from bayle.services.mod_configs import SetupValues
    from overhaul_world import set_up

    folder, toml, _out = set_up(world)
    config = recipes.read(toml)
    natives = [config.basic.natives[0].model_copy(update={"initializer": "Boot"})]
    config = config.model_copy(update={"basic": config.basic.model_copy(update={"natives": natives})})
    toml.write_text(__import__("bayle.overhauls.writer", fromlist=["x"]).render(config), encoding="utf-8")
    service, opened = open_install(world, monkeypatch, folder)
    assert opened.plan["option"] == "matched"
    got = service.check_overhaul(opened.install_id, "mixed-mod")
    assert got.mode == "matched" and got.editable
    assert got.natives[0]["initializer"] == "Boot"  # pre-filled from the saved setup
    assert {"MixedMod.ini"} <= {r["file"] for r in got.files}
    edited = SetupValues(
        [{**got.natives[0], "load_early": True}], {r["file"]: r["choices"][0] for r in got.files}, {}, None
    )
    again = service.check_overhaul(opened.install_id, "mixed-mod", edited)
    assert again.mode == "setup" and again.natives[0]["load_early"] is True  # installed as a setup, config saved


def test_a_dll_with_the_name_of_one_already_in_the_profile_is_said_in_the_review(world):
    from bayle.mods import overhaul_install

    folder = revive_shaped(world)
    world.profile.write_text(
        world.text() + "\n[[natives]]\npath = 'natives/Old/RevivePrototype.dll'\n", encoding="utf-8"
    )
    config = basic.make(
        id="revive", label="Revive", game="eldenring", basic=basic.propose(folder, game="eldenring"), folder=folder
    )
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert p.ok  # it is replaced by the overhaul's DLL, and the review says so
    assert any("natives/Old/RevivePrototype.dll" in n and "is replaced" in n for n in p.notes)


# ----------------------------------------------------------------------------- review follow-ups
def test_a_files_choice_encodes_and_decodes_the_same_way_everywhere():
    assert (
        basic.encode_action("place", "script/x.bin") == "place:script/x.bin" and basic.encode_action("leave") == "leave"
    )
    assert basic.decode_action("place:script/x.bin") == ("place", "script/x.bin")
    assert basic.decode_action("merge") == ("merge", "")
    assert basic.decode_action(basic.encode_action("place", "")) == ("place", "")


def test_applying_a_saved_setup_that_no_profile_took_is_an_error_not_a_success(world):
    from bayle.mods import overhaul_install
    from bayle.services import mods as mod_service
    from overhaul_world import set_up

    set_up(world)
    with pytest.raises(overhaul_install.OverhaulError, match="not found after saving"):
        mod_service.reapply_overhaul_setup(world.profile, "no-such-setup", loc=world.loc)
    bare = world.base / "bare.me3"
    bare.write_text('profileVersion = "v1"\n', encoding="utf-8")
    with pytest.raises(overhaul_install.OverhaulError, match="doesn't use"):
        mod_service.reapply_overhaul_setup(bare, "mixed-mod", loc=world.loc)
    import shutil

    shutil.rmtree(overhaul_install.places(world.profile, "mixed-mod", world.loc).sources)  # no copy of the download
    with pytest.raises(overhaul_install.OverhaulError, match="was not applied to any profile"):
        mod_service.reapply_overhaul_setup(world.profile, "mixed-mod", loc=world.loc)


def test_the_left_out_note_ignores_the_case_of_the_folder(world):
    from bayle.mods import overhaul_install
    from bayle.overhauls.config import BasicNative

    folder = revive_shaped(world)
    make_folder(folder, ["Cfg/B.dll", "Cfg/a.ini"])
    b = basic.propose(folder, game="eldenring").model_copy(
        update={"natives": [BasicNative(file="Cfg/B.dll")], "files": {"cfg/a.ini": "leave"}}
    )
    config = basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert any("cfg/a.ini is left out" in n for n in p.notes)


def test_the_files_table_is_read_off_the_ui_thread(world, monkeypatch):
    from bayle.platform import threads
    from overhaul_world import set_up

    folder, _toml, _out = set_up(world)
    service, opened = open_install(world, monkeypatch, folder)
    threads.enable()  # this thread is "the UI thread" from here on
    try:
        with pytest.raises(threads.UiThreadIO):
            service.check_overhaul(opened.install_id, "mixed-mod")  # reads the whole download: refused
        with threads.as_worker():
            assert service.check_overhaul(opened.install_id, "mixed-mod").files
    finally:
        threads.disable()


def test_the_review_lists_the_proposed_texts_and_refuses_until_a_table_is_chosen(world, monkeypatch):
    from bayle.services.mod_configs import SetupValues
    from test_overhaul_texts_propose import download

    folder = download(world.tmp / "dl" / "Texty", {"A.fmg": [1], "B.fmg": [2]}, {"50": "a"})
    (folder / "mod/chr").mkdir(parents=True)
    (folder / "mod/chr/a.anibnd.dcx").write_bytes(b"x")
    service, opened = open_install(world, monkeypatch, folder)
    got = service.check_overhaul(opened.install_id, "Texty")
    assert got.editable, got.refusals
    (row,) = got.texts
    assert row["table"] == "" and row["tables"] == ["A.fmg", "B.fmg"]
    assert any("Choose the table" in r for r in got.refusals)
    chosen = SetupValues(list(got.natives), {r["file"]: r["choices"][0] for r in got.files}, {row["file"]: "B.fmg"})
    after = service.check_overhaul(opened.install_id, "Texty", chosen)
    assert after.texts[0]["table"] == "B.fmg" and not any("Choose the table" in r for r in after.refusals)


def test_what_a_newer_download_dropped_is_said_in_the_review_notes(tmp_path):
    from bayle.services.mod_install import setup_notes

    folder = make_folder(tmp_path / "dl", ["mod/chr/a.anibnd.dcx", "M.dll"])
    b = basic.propose(folder, game="eldenring").model_copy(update={"files": {"old/gone.ini": "leave"}})
    config = basic.make(id="m", label="M", game="eldenring", basic=b.model_copy(update={"files": {}}), folder=folder)
    (note,) = setup_notes(config.model_copy(update={"basic": b}), folder)
    assert "old/gone.ini is not in the mod's folder any more" in note


def test_a_saved_setup_with_flat_paths_carries_over_to_a_download_with_a_package_root(tmp_path):
    from bayle.overhauls.config import Basic, BasicNative

    from bayle_qt.pages.mods.file_actions import shown_path

    folder = make_folder(tmp_path, ["A.dll", "B.dll", "mod/regulation.bin", "mod/chr/c0000.anibnd.dcx", "cfg/a.ini"])
    saved = Basic(
        natives=[
            BasicNative(file="b.DLL", initializer="Init", after_others=True),
            BasicNative(file="A.dll", load_early=True, after_others=False),
        ],
        files={"chr/c0000.anibnd.dcx": "leave", "gone.bin": "leave", "cfg/a.ini": "keep"},
    )
    out = basic.carry_over(basic.propose(folder), saved, folder)
    by = {n.file: n for n in out.natives}
    assert by["A.dll"].load_early and not by["A.dll"].after_others
    assert by["B.dll"].initializer == "Init"
    assert out.files == {"mod/chr/c0000.anibnd.dcx": "leave", "cfg/a.ini": "keep"}
    assert shown_path("msg/{each}/menu.msgbnd.dcx") == "msg/<language>/menu.msgbnd.dcx"
