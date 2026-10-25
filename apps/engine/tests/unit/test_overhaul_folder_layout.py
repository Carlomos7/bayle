"""An overhaul's own folder sits at the root of a profile's folder (beside packages/ and natives/) and is part of the
profile's layout: duplicate, delete, migration, custom folder names, Shared mods, export and move in treat it so.
Temporary folders only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bayle.adapters.filesystem import trash
from bayle.adapters.persistence import settings_file
from bayle.modules.games import catalog
from bayle.modules.games.locate import Locations, Overrides
from bayle.modules.mods import library, migrate, move_in, profile_edit, profile_rename, profile_transfer, shared_mods
from bayle.modules.settings import models as settings

HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


def entries(folder: Path, packages: str = "packages") -> str:
    absolute = (folder / "Revive" / "extra").as_posix()
    return (
        f"\n[[packages]]\nid = \"revive\"\npath = 'Revive/mod'\n"
        f"\n[[packages]]\nid = \"abs\"\npath = '{absolute}'\n"
        f"\n[[packages]]\nid = \"plain\"\npath = '{packages}/plain'\n"
        "\n[[natives]]\npath = 'Revive/dlls/r.dll'\n"
    )


def make(folder: Path, name: str = "p", packages: str = "packages") -> Path:
    """<folder>/<name>.me3 with an installed overhaul folder (manifest, DLL, package) and one ordinary mod."""
    for rel, data in {
        "Revive/overhaul.json": b'{"version": "1"}',
        "Revive/mod/m.dcx": b"m",
        "Revive/extra/e.dcx": b"e",
        "Revive/dlls/r.dll": b"dll",
        f"{packages}/plain/p.dcx": b"plain",
    }.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_bytes(data)
    profile = folder / f"{name}.me3"
    profile.write_text(HEAD + entries(folder, packages), encoding="utf-8")
    return profile


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    return tmp_path / "profiles"


def loc_of(home: Path) -> Locations:
    return Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))


def test_the_layout_helper_finds_the_overhaul_folder_only(home):
    p = make(home / "b-eldenring" / "p")
    targets = [profile_edit.resolve(p, e["path"]) for e in profile_edit.entries(p)]
    assert library.root_folders(p, targets) == [p.parent / "Revive"]
    assert library.copied_folders(p) == ["packages", "mod", "natives", "Revive"]


def test_duplicate_copies_the_overhaul_folder_and_its_entries_follow(home):
    p = make(home / "b-eldenring" / "p")
    out = profile_rename.duplicate(p, loc=loc_of(home), name="q")
    copy = Path(out["profile"])
    assert (copy.parent / "Revive" / "overhaul.json").read_bytes() == b'{"version": "1"}'
    assert (copy.parent / "Revive" / "dlls" / "r.dll").read_bytes() == b"dll"
    body = copy.read_text(encoding="utf-8")
    assert "Revive/mod" in body and str(p.parent.as_posix()) not in body  # relative stays, absolute follows the copy
    assert "path = 'Revive/extra'" in body  # the absolute one turned relative, into the copy
    assert (p.parent / "Revive" / "mod" / "m.dcx").is_file() and "p/Revive/extra" in p.read_text(encoding="utf-8")


def test_delete_keeps_the_profile_folder_with_its_overhaul(home):
    p = make(home / "b-eldenring" / "p")
    before = {x.relative_to(p.parent).as_posix() for x in (p.parent / "Revive").rglob("*")}
    gone = profile_edit.delete_profile(p)
    assert not p.exists() and gone.is_file()
    assert {x.relative_to(p.parent).as_posix() for x in (p.parent / "Revive").rglob("*")} == before
    shutil.copy2(gone, p)  # put back from Deleted profiles: its entries resolve again
    assert all(profile_edit.resolve(p, e["path"]).exists() for e in profile_edit.entries(p))


def test_migration_takes_the_overhaul_folder_along(home):
    old = home / "rs-eldenring" / "c"
    make(old, "c")
    out = migrate.migrate(loc_of(home))
    assert out is not None
    new = home / "b-eldenring" / "c"
    assert (new / "Revive" / "overhaul.json").is_file() and (new / "Revive" / "dlls" / "r.dll").is_file()
    assert not (home / "rs-eldenring").exists()
    entries_now = profile_edit.entries(new / "c.me3")
    assert entries_now and all(profile_edit.resolve(new / "c.me3", e["path"]).exists() for e in entries_now)
    assert str(old.as_posix()) not in (new / "c.me3").read_text(encoding="utf-8")


def test_custom_folder_names_still_see_the_overhaul_folder_as_inside(home, monkeypatch):
    monkeypatch.setattr(
        settings_file,
        "load_settings",
        lambda: settings.LauncherSettings(
            game_folder_pattern="my-{game}", packages_folder="Mods", natives_folder="Dlls"
        ),
    )
    p = make(home / "my-eldenring" / "p", packages="Mods")
    text = profile_edit.read_text(p)
    assert profile_edit.roots(p, text) == (p.parent / "Mods", p.parent / "Dlls")
    rows = {it.entry["path"]: it.inside for it in profile_transfer.items(p, full=False)}
    assert rows["Revive/mod"] and rows["Revive/dlls/r.dll"] and rows["Mods/plain"]
    out = profile_rename.duplicate(p, loc=loc_of(home), name="q")
    assert (Path(out["profile"]).parent / "Mods" / "plain" / "p.dcx").is_file()  # the renamed folder is copied too
    assert (Path(out["profile"]).parent / "Revive" / "overhaul.json").is_file()


def test_shared_mods_do_not_refuse_a_profile_with_an_overhaul_folder(home):
    p = make(home / "b-eldenring" / "p")
    with shared_mods._Job(loc_of(home), [p], "x", "x"):
        pass  # no "keeps its mods outside" refusal: the check is where the profile is, not what its entries point at


def test_move_in_copies_what_a_sibling_profile_also_uses(home):
    plain = home / "eldenring-mods"
    a = make(plain, "a")
    (plain / "b.me3").write_text(HEAD + "\n[[packages]]\nid = \"r\"\npath = 'Revive/mod'\n", encoding="utf-8")
    plan = move_in.plan(a, loc_of(home))
    assert plan.ok and any(u.src.name == "mod" and u.src.parent.name == "Revive" for u in plan.copied)
    move_in.apply(plan, loc=loc_of(home))
    assert (plain / "Revive" / "mod" / "m.dcx").is_file()  # b still has it


def launcher_installed(profile: Path) -> None:
    """The records a launcher install leaves: the overhaul's manifest and builds/<id>/ naming the original by path."""
    import json

    root = profile.parent
    sha = "0" * 64
    manifest = {
        "installedBy": "x",
        "profile": str(profile),
        "maintenance": str(root / "builds" / "ex" / "sources"),
        "sources": [{"path": str(profile), "sha256": sha}, {"path": "D:/elsewhere/file", "sha256": sha}],
    }
    (root / "Revive" / "overhaul.json").write_text(json.dumps(manifest), encoding="utf-8")
    (root / "builds" / "ex" / "sources" / "merge").mkdir(parents=True)
    (root / "builds" / "ex" / "sources" / "merge" / "f.dcx").write_bytes(b"f")
    (root / "builds" / "ex" / "overhaul").mkdir(parents=True)
    (root / "builds" / "ex" / "overhaul" / "roundtable.json").write_text(
        json.dumps({"profile": str(profile), "n": 1}), encoding="utf-8"
    )


def test_duplicate_of_a_launcher_installed_overhaul_copies_builds_and_remaps_records(home):
    import json

    p = make(home / "b-eldenring" / "p")
    launcher_installed(p)
    out = profile_rename.duplicate(p, loc=loc_of(home), name="q")
    copy = Path(out["profile"])
    root = copy.parent
    assert (root / "builds" / "ex" / "sources" / "merge" / "f.dcx").is_file()
    manifest = json.loads((root / "Revive" / "overhaul.json").read_text(encoding="utf-8"))
    assert manifest["profile"] == str(copy) and manifest["maintenance"].startswith(str(root))
    assert manifest["sources"][0]["path"] == str(copy) and manifest["sources"][0]["sha256"] != "0" * 64
    assert manifest["sources"][1]["path"] == "D:/elsewhere/file"
    rec = json.loads((root / "builds" / "ex" / "overhaul" / "roundtable.json").read_text(encoding="utf-8"))
    assert rec["profile"] == str(copy)
    original = json.loads((p.parent / "Revive" / "overhaul.json").read_text(encoding="utf-8"))
    assert original["profile"] == str(p)  # the original is untouched


def test_duplicate_refuses_a_record_it_cannot_read_and_leaves_nothing(home):
    p = make(home / "b-eldenring" / "p")
    launcher_installed(p)
    (p.parent / "builds" / "ex" / "overhaul" / "roundtable.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(profile_rename.ProfileRenameError, match="roundtable.json"):
        profile_rename.duplicate(p, loc=loc_of(home), name="q")
    assert not (p.parent.parent / "q").exists() and not list(p.parent.parent.glob(".q.copy-*"))


def test_custom_names_are_reserved_and_split_by_the_settings_names(home, monkeypatch):
    from bayle.modules.mods import folder_split, naming

    monkeypatch.setattr(
        settings_file,
        "load_settings",
        lambda: settings.LauncherSettings(packages_folder="Mods", natives_folder="Dlls"),
    )
    assert {"mods", "dlls", "packages"} <= naming.reserved()
    assert naming.unique("mods", []) == "mods-2"
    assert folder_split.mods_folders() == ("mod", "Mods", "Dlls") and folder_split.renamed("mod") == "Mods"
