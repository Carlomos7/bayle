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


# ----------------------------------------------------------------------------- gap 3: texts from a JSON file
def texts_setup(world, texts: dict[str, str]):
    from roundtable_souls.overhauls.config import BasicText

    folder = revive_shaped(world)
    (folder / "settings/en.json").write_text('{"99002000": "Session settings"}', encoding="utf-8")
    (folder / "settings/ru.json").write_text('{"99002000": "ru"}', encoding="utf-8")
    entry = BasicText(file="msg/{each}/menu_dlc02.msgbnd.dcx", table="eventtextfortalk.fmg", texts=texts)
    b = basic.propose(folder, game="eldenring").model_copy(update={"texts": [entry]})
    return folder, basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)


def test_texts_from_json_files_are_set_in_each_languages_binder_and_the_files_are_not_copied(world):
    from roundtable_souls.mods import overhaul_install

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
    from roundtable_souls.mods import overhaul_install

    folder, config = texts_setup(world, {"rusru": "settings/ru.json"})
    overhaul_install.install_setup(
        overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc), loc=world.loc
    )
    assert (world.base / "revive/mod/msg/rusru/menu_dlc02.msgbnd.dcx").is_file()
    assert not (world.base / "revive/mod/msg/engus/menu_dlc02.msgbnd.dcx").exists()
    report = (world.base / "revive/merge-report.txt").read_text(encoding="utf-8")
    assert "msg/engus/menu_dlc02.msgbnd.dcx: the mod has no texts for this language" in report


def test_malformed_texts_stop_the_install_and_write_nothing(world):
    from roundtable_souls.mods import overhaul_install

    folder, config = texts_setup(world, {"*": "settings/en.json"})
    (folder / "settings/en.json").write_text('{"not a number": "x"}', encoding="utf-8")
    before = world.profile.read_bytes()
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    with pytest.raises(Exception, match="not a JSON object of text IDs"):
        overhaul_install.install_setup(p, loc=world.loc)
    assert world.profile.read_bytes() == before and not (world.base / "revive").exists()


def test_a_texts_file_the_mod_does_not_have_is_refused_and_the_form_keeps_the_texts(world):
    from roundtable_souls.overhauls.config import BasicText
    from roundtable_souls.services import mod_configs

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

    from test_overhaul_install import set_up

    from roundtable_souls import overhauls
    from roundtable_souls.mods import overhaul_install
    from roundtable_souls.overhauls import writer

    _folder, toml, _out = set_up(world)
    other = world.base / "other.me3"
    other.write_bytes(world.profile.read_bytes())
    config = overhauls.read(toml)
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
    from roundtable_souls.mods import overhaul_install, undo
    from roundtable_souls.platform import logging as run_logging
    from roundtable_souls.services import mods as mod_service

    other = two_profiles(world)
    monkeypatch.setattr(overhaul_install, "users_of", lambda p, c, e: [Path(p), other])
    before = {p: p.read_bytes() for p in (world.profile, other)}
    got: list[dict] = []
    monkeypatch.setattr(run_logging, "set_undo", lambda d: got.append(d))
    done = mod_service.reapply_overhaul_setup(world.profile, loc=world.loc)
    assert done == ["my.me3", "other.me3"] and len(got) == 1 and got[0]["type"] == "overhaul-reapply"
    assert all(b"Boot" in p.read_bytes() for p in before)
    assert undo.available(got[0])
    undo.run(got[0], lambda s: None, loc=world.loc)
    assert {p: p.read_bytes() for p in before} == before


def test_a_disabled_overhaul_stays_disabled_when_the_setup_is_applied(world):
    from test_overhaul_install import set_up

    from roundtable_souls import overhauls
    from roundtable_souls.overhauls import writer
    from roundtable_souls.services import mods as mod_service

    _folder, toml, _out = set_up(world)
    text = world.text().replace('id = "mixed-mod"', 'id = "mixed-mod"\nenabled = false')
    text = text.replace("MixedMod.dll'", "MixedMod.dll'\nenabled = false")
    world.profile.write_text(text, encoding="utf-8")
    config = overhauls.read(toml)
    writer.save_local(config, expect=writer.sha256_of(toml), path=toml)
    mod_service.reapply_overhaul_setup(world.profile, loc=world.loc)
    after = world.data()
    package = next(p for p in after["packages"] if p.get("id") == "mixed-mod")
    native = next(n for n in after["natives"] if "MixedMod" in n["path"])
    assert package.get("enabled") is False and native.get("enabled") is False


# ----------------------------------------------------------------------------- gap 4: a matched setup is pre-filled
def test_a_download_matching_a_saved_setup_shows_its_dll_options_and_files_and_installs_the_changes(world):
    from types import SimpleNamespace

    from PySide6.QtCore import QCoreApplication
    from test_overhaul_install import set_up

    from roundtable_souls import overhauls
    from roundtable_souls.services import mods as mod_service
    from roundtable_souls.ui.pages.mods.install import InstallDraft
    from roundtable_souls.ui.pages.mods.install_adapter import InstallAdapter

    app = QCoreApplication.instance() or QCoreApplication([])
    folder, toml, _out = set_up(world)
    config = overhauls.read(toml)
    natives = [config.basic.natives[0].model_copy(update={"initializer": "Boot"})]
    config = config.model_copy(update={"basic": config.basic.model_copy(update={"natives": natives})})
    toml.write_text(__import__("roundtable_souls.overhauls.writer", fromlist=["x"]).render(config), encoding="utf-8")
    plan = mod_service.plan_mod_install(world.profile, folder, loc=world.loc)
    assert plan.get("overhaul")
    host = SimpleNamespace(
        profile=world.profile,
        locations=world.loc,
        run_in_background=lambda work, done: done(work()),
        run_job=lambda *a, **k: None,
    )
    adapter = InstallAdapter(host, SimpleNamespace())
    draft = adapter._draft = InstallDraft(plan, world.profile, overhaul_on=True)
    assert draft.overhaul_mode == "matched"
    adapter._planned = adapter._key()
    adapter._refresh()
    view = draft.view()
    assert view["natives"][0]["initializer"] == "Boot"  # pre-filled from the saved setup
    assert {"MixedMod.ini"} <= {r["file"] for r in view["files"]}
    assert not adapter._via_setup
    adapter.setNative("MixedMod.dll", "early", "true")
    adapter._timer.stop()
    adapter._refresh()
    assert adapter._via_setup and adapter._preview.found.config.basic.natives[0].load_early is True
    del app


def test_a_dll_with_the_name_of_one_already_in_the_profile_is_said_in_the_review(world):
    from roundtable_souls.mods import overhaul_install

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
