"""Taking over an overhaul its own installer set up (mods.overhaul_takeover) and finding installer leftovers without
a config (mods.installer_leftovers): synthetic folders modelled on a real installer's layout, a fake Recycle Bin."""

import json
import shutil
import tomllib
from pathlib import Path

import pytest
from test_overhaul_install import PROFILE, World, files, legacy

from roundtable_souls.mods import overhaul_install, overhaul_takeover
from roundtable_souls.mods.overhaul_install import Leftover, OverhaulError


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def stray(world, profile_field=None, installed_by=None):
    """An installer no config describes: its folder and manifest, its setup copy and its backups."""
    d = world.base / "Stray"
    d.mkdir()
    (d / "mod").mkdir()
    manifest = {"profile": profile_field or str(world.profile), "maintenance": str(world.base / ".stray-setup")}
    if installed_by:
        manifest["installedBy"] = installed_by
    (d / "installation.json").write_text(json.dumps(manifest))
    (world.base / ".stray-setup").mkdir(exist_ok=True)
    (world.base / ".stray-setup/stray-maintenance.json").write_text("{}")
    b = world.base / "Stray Backups/20260101-000000-000000"
    b.mkdir(parents=True, exist_ok=True)
    (b / "restore.json").write_text(json.dumps({"files": [], "directories": []}))
    return d


def names(world):
    return [(x.path.name, x.backups) for x in overhaul_install.leftovers(world.profile, loc=world.loc)]


# ----------------------------------------------------------------------------- leftovers without a config
def test_leftovers_are_found_from_manifests_and_known_files_without_a_config(world):
    stray(world)
    assert names(world) == [(".stray-setup", False), ("Stray", False), ("Stray Backups", True)]


def test_a_folder_a_profile_still_uses_is_not_listed(world):
    stray(world)
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = \"stray\"\npath = 'Stray/mod'\n", encoding="utf-8")
    assert names(world) == []  # the setup is live: its copy and backups stay too


def test_launcher_made_or_foreign_manifests_are_not_leftovers(world):
    stray(world, installed_by="Roundtable Souls 4")
    assert ("Stray", False) not in names(world)
    shutil.rmtree(world.base / "Stray")
    stray(world, profile_field=str(world.tmp / "elsewhere" / "other.me3"))
    assert ("Stray", False) not in names(world)


# ----------------------------------------------------------------------------- take over
def test_take_over_removes_the_installers_entries_and_folders_and_undo_puts_them_back(world):
    legacy(world)
    mine = world.base / "mod/body/parts"
    mine.mkdir(parents=True, exist_ok=True)
    (mine / "keep.txt").write_text("mine")
    before = files(world.base)
    chosen = overhaul_takeover.choices(world.profile, loc=world.loc)
    assert [type(c).__name__ for c in chosen] == ["SideEffect", "Leftover"]  # start_online, the backups folder
    p = overhaul_takeover.preview(world.profile, loc=world.loc)  # nothing chosen: setup copy only
    assert files(world.base) == before  # a preview (or a cancel) writes nothing
    assert [t.name for t in p.trash] == [".example-overhaul-setup", "ExampleOverhaul"]
    assert any("setup copy" in line for line in p.lines)
    p = overhaul_takeover.preview(world.profile, loc=world.loc, chosen=chosen)
    assert [t.name for t in p.trash] == [".example-overhaul-setup", "Example Backups", "ExampleOverhaul"]
    out = overhaul_install.remove(p)
    data = world.data()
    assert data["start_online"] is True and "ExamplePrototype" not in world.text()
    assert [x["id"] for x in data["packages"]] == ["body", "anims"]
    assert not world.own.exists() and not (world.base / "Example Backups").exists()
    assert (mine / "keep.txt").read_text() == "mine" and (world.base / "natives/SeamlessCoop/ersc.dll").is_file()
    overhaul_install.undo_remove(out)
    assert files(world.base) == before


def test_a_profile_edited_after_the_installer_keeps_the_players_entries(world):
    legacy(world)
    world.profile.write_text(
        world.text() + "\n[[packages]]\nid = \"added-later\"\npath = 'mod/body'\n", encoding="utf-8"
    )
    overhaul_install.remove(overhaul_takeover.preview(world.profile, loc=world.loc))
    assert "added-later" in [x["id"] for x in world.data()["packages"]]
    assert "example-overhaul" not in world.text()


def test_with_another_profile_using_it_the_folders_stay(world):
    legacy(world)
    other = world.base / "second.me3"
    other.write_text(PROFILE + "\n[[packages]]\nid = \"example-overhaul\"\npath = 'ExampleOverhaul/mod'\n")
    p = overhaul_takeover.preview(world.profile, loc=world.loc)
    assert p.users == [other] and p.trash == []
    overhaul_install.remove(p)
    assert world.own.is_dir() and (world.base / ".example-overhaul-setup").is_dir()
    assert "example-overhaul" in other.read_text() and "example-overhaul" not in world.text()


def test_without_backups_take_over_still_works_and_offers_no_settings(world):
    legacy(world)
    shutil.rmtree(world.base / "Example Backups")
    assert overhaul_takeover.choices(world.profile, loc=world.loc) == []
    overhaul_install.remove(overhaul_takeover.preview(world.profile, loc=world.loc))
    assert world.data()["start_online"] is False and not world.own.exists()


def test_take_over_works_when_the_installers_folder_is_already_gone(world):
    legacy(world)
    shutil.rmtree(world.own)
    assert overhaul_install.installer_made(world.profile, loc=world.loc)
    p = overhaul_takeover.preview(world.profile, loc=world.loc)
    overhaul_install.remove(p)
    assert "ExamplePrototype" not in world.text() and not (world.base / ".example-overhaul-setup").exists()


def test_a_setup_the_launcher_made_is_removed_not_taken_over(world):
    world.install()
    assert not overhaul_install.installer_made(world.profile, loc=world.loc)
    with pytest.raises(OverhaulError, match="use Remove"):
        overhaul_takeover.preview(world.profile, loc=world.loc)


def test_the_service_flags_take_over_for_an_installer_setup(world):
    from roundtable_souls.services import mods as service

    legacy(world)
    assert service.profile_overhaul(world.profile, loc=world.loc)["takeover"] is True
    [(text)] = [
        service.choice_text(c)
        for c in service.take_over_choices(world.profile, loc=world.loc)
        if isinstance(c, Leftover)
    ]
    assert text.startswith("Example Backups (")


# ----------------------------------------------------------------------------- take over without a config
def live_stray(world, how="manifest"):
    """A profile as an installer no config describes left it: its package in its folder, a DLL beside the player's
    own, a changed setting; the pre-install profile in its manifest (how=manifest), in its oldest backup
    (backup) or nowhere (none)."""
    d = stray(world)
    base = tomllib.loads(PROFILE)
    manifest = json.loads((d / "installation.json").read_text())
    if how == "manifest":
        manifest["profiles"] = [{"path": str(world.profile), "baseProfile": base}]
    (d / "installation.json").write_text(json.dumps(manifest))
    if how == "backup":
        b = world.base / "Stray Backups/20260101-000000-000000"
        (b / "file-0").write_text(PROFILE)
        (b / "restore.json").write_text(
            json.dumps({"files": [{"path": str(world.profile), "original": "file-0"}], "directories": []})
        )
    world.profile.write_text(
        PROFILE.replace("start_online = true", "start_online = false")
        + "\n[[packages]]\nid = \"stray\"\npath = 'Stray/mod'\n"
        + "\n[[natives]]\npath = 'natives/StrayDll/stray.dll'\n"
        + "\n[[packages]]\nid = \"added-later\"\npath = 'mod/body'\n",
        encoding="utf-8",
    )
    return d


def test_the_installers_records_show_what_changed_and_only_the_ticked_go(world):
    from roundtable_souls.services import mods as service

    live_stray(world)
    assert service.profile_overhaul(world.profile, loc=world.loc) == {
        "label": "Stray",
        "short_label": "Stray",
        "legacy": True,
        "takeover": True,
        "removable": False,
    }
    chosen = overhaul_takeover.choices(world.profile, loc=world.loc)
    shown = [service.choice_text(c) for c in chosen]
    assert any(t.startswith("stray.dll (DLL)") for t in shown) and any(t.startswith("added-later") for t in shown)
    assert any(t.startswith("start_online") for t in shown) and any(t.startswith("Stray Backups") for t in shown)
    before = files(world.base)
    pick = [c for c in chosen if getattr(c, "name", "") == "stray.dll" or getattr(c, "setting", "") == "start_online"]
    p = overhaul_takeover.preview(world.profile, loc=world.loc, chosen=pick)
    assert files(world.base) == before and p.removed == ["stray", "stray.dll"]
    assert [t.name for t in p.trash] == [".stray-setup", "Stray"]
    out = overhaul_install.remove(p)
    data = world.data()
    assert data["start_online"] is True and not (world.base / "Stray").exists()
    assert [x["id"] for x in data["packages"]] == ["body", "anims", "added-later"]  # the player's later entry stays
    assert [Path(n["path"]).name for n in data["natives"]] == ["ersc.dll"]
    overhaul_install.undo_remove(out)
    assert files(world.base) == before


def test_the_oldest_backup_stands_in_when_the_manifest_keeps_no_profile(world):
    live_stray(world, "backup")
    chosen = overhaul_takeover.choices(world.profile, loc=world.loc)
    assert {getattr(c, "name", None) for c in chosen} >= {"stray.dll", "added-later"}


def test_with_no_records_only_what_points_into_the_installers_folder_goes(world):
    live_stray(world, "none")
    assert [type(c).__name__ for c in overhaul_takeover.choices(world.profile, loc=world.loc)] == ["Leftover"]
    p = overhaul_takeover.preview(world.profile, loc=world.loc)
    overhaul_install.remove(p)
    ids = [x["id"] for x in world.data()["packages"]]
    assert "stray" not in ids and "added-later" in ids and "natives/StrayDll/stray.dll" in world.text()


def test_another_profile_using_the_folder_keeps_it(world):
    live_stray(world)
    other = world.base / "second.me3"
    other.write_text(PROFILE + "\n[[packages]]\nid = \"stray\"\npath = 'Stray/mod'\n")
    p = overhaul_takeover.preview(world.profile, loc=world.loc)
    assert p.users == [other] and p.trash == []
    overhaul_install.remove(p)
    assert (world.base / "Stray").is_dir() and "stray" in other.read_text()


def test_a_copy_of_the_installers_folder_is_a_leftover_while_the_setup_is_live(world):
    live_stray(world)
    shutil.copytree(world.base / "Stray", world.base / "Stray-backup")
    assert names(world) == [("Stray-backup", False)]  # the live setup's own copy and backups stay
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = \"stray\"\npath = 'Stray-backup/mod'\n")
    assert ("Stray-backup", False) not in names(world)  # used by a profile


def test_the_ui_menu_entry_and_the_reinstall_question(world):
    from roundtable_souls.ui.pages.mods.presenter import ModsPresenter
    from roundtable_souls.ui.pages.mods.take_over import reinstall_words

    menu = ModsPresenter().overhaul_menu
    assert menu(True, {"label": "X", "takeover": True}, False).can_take_over
    assert not menu(True, {"label": "X", "takeover": False}, False).can_take_over
    assert not menu(True, None, False).can_take_over
    assert not menu(True, {"label": "X", "takeover": True, "removable": False}, False).can_remove
    assert "Install X" in reinstall_words("X").title


def test_entries_the_installer_copied_are_ticked_and_references_to_removed_entries_go(world):
    from dataclasses import replace

    live_stray(world)
    (world.base / "natives/StrayDll").mkdir(parents=True)
    (world.base / "natives/StrayDll/stray.dll").write_bytes(b"installer dll")
    (world.base / ".stray-setup/payload").mkdir()
    (world.base / ".stray-setup/payload/stray.dll").write_bytes(
        b"installer dll"
    )  # byte-identical: the installer made it
    (world.base / "mod/body/added.dll").write_bytes(b"mine")
    world.profile.write_text(
        world.text()
        + "\n[[natives]]\npath = 'mod/body/added.dll'\nload_after = [\n  { id = \"stray\", optional = true },\n"
        + '  { id = "stray.dll", optional = true },\n  { id = "ersc.dll", optional = true },\n]\n',
        encoding="utf-8",
    )
    chosen = overhaul_takeover.choices(world.profile, loc=world.loc)
    by_name = {c.name: c for c in chosen if hasattr(c, "kind")}
    assert by_name["stray.dll"].copied and not by_name["added-later"].copied and not by_name["added.dll"].copied
    assert "copied by the installer" in by_name["stray.dll"].label
    assert "not in the profile before the installer" in by_name["added-later"].label
    p = overhaul_takeover.preview(
        world.profile, loc=world.loc, chosen=[c for c in chosen if getattr(c, "copied", False)]
    )
    assert any("stop waiting" in line for line in p.lines)
    overhaul_install.remove(p)
    row = next(n for n in world.data()["natives"] if n["path"].endswith("added.dll"))
    assert [d["id"] for d in row["load_after"]] == ["ersc.dll"]  # the others' lists keep the entries still there
    assert replace(by_name["stray.dll"], copied=False) != by_name["stray.dll"]
