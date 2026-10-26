"""Edge cases of a basic overhaul setup, install and build (overhauls.basic, mods.overhaul_install, mods.engine):
deep paths, read-only files, drives, a missing game folder, placed files, text id clashes, updates. Temporary folders
and synthetic files only."""

import shutil
import stat
import sys
from pathlib import Path

import pytest
from fakegame import bnd, dcx, fmg
from test_overhaul_install import World, files, set_up

from bayle.adapters.filesystem import build as B
from bayle.adapters.overhauls import basic, recipes
from bayle.modules.games.locate import Locations, Overrides
from bayle.modules.mods import overhaul_install
from bayle.modules.mods.overhaul_install import OverhaulError

# Copied from the desktop app's test_overhaul_gaps (it also holds Qt-only tests, so it lives there).
TALK = "script/talk/m00.talkesdbnd.dcx"


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


def texts_setup(world, texts: dict[str, str]):
    from bayle.modules.overhauls.config import BasicText

    folder = revive_shaped(world)
    (folder / "settings/en.json").write_text('{"99002000": "Session settings"}', encoding="utf-8")
    (folder / "settings/ru.json").write_text('{"99002000": "ru"}', encoding="utf-8")
    entry = BasicText(file="msg/{each}/menu_dlc02.msgbnd.dcx", table="eventtextfortalk.fmg", texts=texts)
    b = basic.propose(folder, game="eldenring").model_copy(update={"texts": [entry]})
    return folder, basic.make(id="revive", label="Revive", game="eldenring", basic=b, folder=folder)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def setup_of(world, folder: Path, id: str = "revive"):
    config = basic.make(id=id, label=id.title(), game="eldenring", basic=basic.propose(folder), folder=folder)
    return config, overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)


def read_only(folder: Path) -> None:
    for p in folder.rglob("*"):
        if p.is_file():
            p.chmod(stat.S_IREAD)


# ----------------------------------------------------------------------------- 1: paths over 260 characters
def moved_deep(world, pad: int) -> None:
    """Move the world's profiles folder under `pad` characters of extra folders."""
    deep = world.tmp / "deep"
    while len(str(deep)) < len(str(world.tmp)) + pad:
        deep = deep / "a-folder-of-some-length"
    new = deep / "profiles"
    if new == world.profiles:
        return
    new.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(world.profiles, new)
    world.profiles, world.base = new, new / "eldenring-mods"
    world.profile = world.base / "my.me3"
    world.loc = Locations(world.loc.game, Overrides(profiles_dir=str(new)))


@pytest.mark.skipif(sys.platform != "win32", reason="the 260-character limit is Windows'")
def test_the_deepest_profile_folder_the_preview_allows_installs_and_removes_with_no_path_error(world):
    folder = revive_shaped(world)
    pad = 0
    while True:  # deeper and deeper until the preview refuses
        moved_deep(world, pad + 5)
        _config, p = setup_of(world, folder)
        if not p.ok:
            break
        pad += 5
        assert pad < 300
    assert any("too long a path for Windows" in r for r in p.refusals)  # plain words, and nothing is written
    with pytest.raises(OverhaulError, match="too long a path"):
        overhaul_install.install_setup(p, loc=world.loc)
    assert not (world.base / "revive").exists()
    moved_deep(world, pad)  # back to the deepest it allowed: it must really work on Windows' own limit
    _config, p = setup_of(world, folder)
    assert p.ok, p.refusals
    overhaul_install.install_setup(p, loc=world.loc)
    assert (world.base / "revive/mod/regulation.bin").is_file()
    overhaul_install.remove(overhaul_install.preview_remove(world.profile, loc=world.loc))
    assert not (world.base / "revive").exists()


# ----------------------------------------------------------------------------- 2: read-only files in the download
def test_a_download_of_read_only_files_installs_updates_and_removes(world, tmp_path):
    folder = revive_shaped(world)
    read_only(folder)
    _config, p = setup_of(world, folder)
    assert p.ok, p.refusals
    overhaul_install.install_setup(p, loc=world.loc)
    assert (world.base / "revive/RevivePrototype.dll").is_file()
    newer = tmp_path / "again" / "Revive Shaped"
    shutil.copytree(folder, newer)  # keeps the read-only attribute
    (newer / "RevivePrototype.dll").chmod(stat.S_IWRITE)
    (newer / "RevivePrototype.dll").write_bytes(b"newer")
    (newer / "RevivePrototype.dll").chmod(stat.S_IREAD)
    _config, p2 = setup_of(world, newer)
    assert p2.ok and p2.update, p2.refusals
    overhaul_install.install_setup(p2, loc=world.loc)
    assert (world.base / "revive/RevivePrototype.dll").read_bytes() == b"newer"
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    assert r.ok, r.refusals
    overhaul_install.remove(r)
    assert not (world.base / "revive").exists()


def test_read_only_files_in_the_overhaul_folder_do_not_stop_the_next_build(world):
    folder = revive_shaped(world)
    _config, p = setup_of(world, folder)
    overhaul_install.install_setup(p, loc=world.loc)
    read_only(world.base / "revive")  # an editor or the game left them so
    (folder / "audio/hit.wav").write_bytes(b"w2")
    _config, p2 = setup_of(world, folder)
    overhaul_install.install_setup(p2, loc=world.loc)
    assert (world.base / "revive/audio/hit.wav").read_bytes() == b"w2"
    assert not list(world.base.glob(".revive.*"))  # no half-removed leftovers


# ----------------------------------------------------------------------------- 3: another drive
def test_same_drive_is_false_for_a_missing_folder_and_true_for_siblings(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert B._same_drive(tmp_path / "a", tmp_path / "b")
    assert not B._same_drive(tmp_path / "a", tmp_path / "missing")


def test_install_update_and_remove_work_when_every_drive_check_says_different(world, monkeypatch):
    """The download is only read (copied); everything else is staged beside its target."""
    monkeypatch.setattr(B, "_same_drive", lambda a, b: False)
    folder = revive_shaped(world)
    _config, p = setup_of(world, folder)
    overhaul_install.install_setup(p, loc=world.loc)
    _config, p2 = setup_of(world, folder)
    assert p2.update
    overhaul_install.install_setup(p2, loc=world.loc)
    overhaul_install.remove(overhaul_install.preview_remove(world.profile, loc=world.loc))
    assert not (world.base / "revive").exists()


def test_the_download_is_never_moved_or_changed(world):
    folder = revive_shaped(world)
    before = files(folder)
    _config, p = setup_of(world, folder)
    overhaul_install.install_setup(p, loc=world.loc)
    assert files(folder) == before


# ----------------------------------------------------------------------------- 4: no game folder
def test_no_game_folder_refuses_in_the_preview_and_writes_nothing(world, monkeypatch):
    from bayle.adapters.games import discovery

    folder = revive_shaped(world)
    monkeypatch.setattr(discovery, "installed_dir", lambda _game: None)
    before = files(world.base)
    profile = world.profile.read_bytes()
    _config, p = setup_of(world, folder)
    assert not p.ok and any("game folder was not found" in r for r in p.refusals)
    with pytest.raises(OverhaulError, match="game folder was not found"):
        overhaul_install.install_setup(p, loc=world.loc)
    assert files(world.base) == before and world.profile.read_bytes() == profile
    assert not list(world.base.glob(".*installing*"))


# ----------------------------------------------------------------------------- 5: gap 2, a placed file nothing ships
def test_a_placed_file_no_package_ships_is_used_whole_without_a_clash(world):
    folder = revive_shaped(world)
    _config, p = setup_of(world, folder)
    assert p.ok
    overhaul_install.install_setup(p, loc=world.loc)
    placed = world.base / f"revive/mod/{TALK}"
    assert placed.read_bytes() == (folder / "settings/m00.talkesdbnd.dcx").read_bytes()
    report = (world.base / "revive/merge-report.txt").read_text(encoding="utf-8")
    assert "No clashes." in report and "m00.talkesdbnd" not in report


def test_a_placed_file_an_earlier_package_ships_is_built_from_both(world):
    earlier = world.base / "mod/body" / TALK
    earlier.parent.mkdir(parents=True, exist_ok=True)
    earlier.write_bytes(dcx(bnd({"talk.esd": b"x", "other.esd": b"o"})))
    folder = revive_shaped(world)
    _config, p = setup_of(world, folder)
    overhaul_install.install_setup(p, loc=world.loc)
    report = (world.base / "revive/merge-report.txt").read_text(encoding="utf-8")
    assert "m00.talkesdbnd.dcx (NPC and grace menus): the mod lacks 1 inner file" in report  # merged on the earlier one


# ----------------------------------------------------------------------------- 6: gap 3, a text id set twice
def test_two_packages_setting_the_same_text_id_are_reported_as_a_clash(world):
    theirs = world.base / "mod/body/msg/engus/menu_dlc02.msgbnd.dcx"
    theirs.parent.mkdir(parents=True)
    table = fmg({1000: "Rest", 99002000: "Theirs"})
    theirs.write_bytes(dcx(bnd({"EventTextForTalk.fmg": table, "Other.fmg": fmg({5: "x"})})))
    folder, config = texts_setup(world, {"*": "settings/en.json"})
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    overhaul_install.install_setup(p, loc=world.loc)
    report = (world.base / "revive/merge-report.txt").read_text(encoding="utf-8")
    line = next(x for x in report.splitlines() if "99002000" in x)
    assert line.startswith("clash:") and "menu_dlc02.msgbnd.dcx" in line and "is used" in line


# ----------------------------------------------------------------------------- 7: the update flow
def test_a_newer_download_keeps_the_players_settings_file_and_the_saved_setup(world, tmp_path):
    folder, toml, _out = set_up(world)
    own = world.base / "mixed-mod"
    (own / "MixedMod.ini").write_text("[a]\nb=player\n")  # the player's own setting
    setup = toml.read_bytes()
    newer = tmp_path / "Downloads" / "Mixed Mod 2"
    shutil.copytree(folder, newer)
    (newer / "MixedMod.dll").write_bytes(b"d2")
    (newer / "MixedMod.ini").write_text("[a]\nb=1\nc=new\n")
    config = recipes.read(toml)
    p = overhaul_install.preview_setup(world.profile, newer, config, loc=world.loc)
    assert p.ok and p.update, p.refusals
    overhaul_install.install_setup(p, loc=world.loc)
    assert (own / "MixedMod.dll").read_bytes() == b"d2"
    text = (own / "MixedMod.ini").read_text()
    assert "b=player" in text and "c=new" in text  # kept, new keys added
    assert recipes.read(toml) == config and toml.read_bytes() == setup


def test_a_download_missing_a_file_the_setup_names_is_refused_and_the_old_build_stays(world, tmp_path):
    folder, toml, _out = set_up(world)
    own = world.base / "mixed-mod"
    before, profile = files(own), world.profile.read_bytes()
    config = recipes.read(toml)
    newer = tmp_path / "Downloads" / "Mixed Mod 3"
    shutil.copytree(folder, newer)
    (newer / "MixedMod.dll").unlink()  # the DLL the setup loads is gone
    with pytest.raises(OverhaulError, match="is not in the mod's folder"):
        overhaul_install.preview_setup(world.profile, newer, config, loc=world.loc)
    # the saved config used directly (no form): the download no longer fits it
    try:
        p = overhaul_install.preview_install(world.profile, newer, loc=world.loc, configs=[config])
    except OverhaulError:
        pass
    else:
        assert not p.ok
        with pytest.raises(OverhaulError):
            overhaul_install.install(p, loc=world.loc)
    assert files(own) == before and world.profile.read_bytes() == profile
    assert not list(world.base.glob(".*installing*")) and toml.is_file()
