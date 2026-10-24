"""Every profile owns its mods in a folder of its own (mods.library.ProfileFolder), and the one-time move out of the
shared rs-<game> library (mods.migrate) moves players' files: these are the safety tests. Temporary folders only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.merging import build as B
from bayle.mods import install, library, migrate, operations, remove, undo
from bayle.mods import profile_settings as ps
from bayle.platform import trash
from support import er

NEW = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def text(*entries: str) -> bytes:
    return (NEW + "".join(entries)).encode()


def pkg(path: str, id_: str = "") -> str:
    return f"\n[[packages]]\n{f'id = {chr(34)}{id_}{chr(34)}{chr(10)}' if id_ else ''}path = '{path}'\n"


def tree(folder: Path) -> dict[str, bytes]:
    """Every file below folder but the launcher's journals and locks."""
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file()
        and not any(x.startswith((".roundtable-ops", ".rs-profile")) for x in p.relative_to(folder).parts)
        and not p.name.endswith(".lock")
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    """rs-eldenring with profiles a and b sharing the package flora; a also has a native and a build of its own."""
    home = tmp_path / "profiles"
    root = home / "rs-eldenring"
    for rel, data in {
        "packages/flora/parts/f.dcx": b"flora",
        "packages/flora/regulation.bin": b"reg",
        "packages/hair/chr/h.dcx": b"hair",
        "natives/ng/ng.dll": b"dll",
        "natives/ng/ng.ini": b"[x]",
        "builds/combined-parameters/a/build.json": b"{}",
        ".roundtable/backups/a.me3.bak": b"a bak",
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    a, b = root / "profiles" / "a.me3", root / "profiles" / "b.me3"
    a.parent.mkdir(parents=True)
    a.write_bytes(
        text(
            pkg("../packages/flora", "flora"),
            pkg("../builds/combined-parameters/a"),
            "\n[[natives]]\npath = '../natives/ng/ng.dll'\n",
        )
    )
    b.write_bytes(text(pkg("../packages/flora", "flora"), pkg("../packages/hair", "hair")))
    a.with_name("a.offline.me3").write_bytes(b"offline")
    (root / ".roundtable" / "settings.json").write_text(
        '{"version": 1, "schema": 1, "profiles": {"a.me3": {"after_overlay": ["flora"]}}}', encoding="utf-8"
    )
    # what 4.0.x's first layout made: rs-eldenring/<name>/ with mod/
    c = root / "c" / "c.me3"
    (c.parent / "mod" / "zed").mkdir(parents=True)
    (c.parent / "mod" / "zed" / "z.dcx").write_bytes(b"zed")
    c.write_bytes(text(pkg("mod/zed", "zed")))
    # what 4.2.0 made: roundtable/eldenring/profiles/<name>/ with a .roundtable state folder and a Shared mod link
    old = home / "roundtable" / "eldenring"
    d = old / "profiles" / "d" / "d.me3"
    (d.parent / "packages" / "zed2").mkdir(parents=True)
    (d.parent / "packages" / "zed2" / "z2.dcx").write_bytes(b"zed2")
    (d.parent / ".roundtable").mkdir()
    (d.parent / ".roundtable" / "settings.json").write_text(
        '{"version": 1, "schema": 1, "profiles": {"d.me3": {"after_overlay": ["q"]}}}', encoding="utf-8"
    )
    (old / "library" / "lib-mod" / "v1").mkdir(parents=True)
    (old / "library" / "lib-mod" / "v1" / "f.dcx").write_bytes(b"shared")
    (old / "library" / "lib-mod" / "mod.json").write_bytes(b"{}")
    d.write_bytes(text(pkg("packages/zed2", "zed2"), pkg("../../library/lib-mod/v1", "lib")))
    # a profile that is not the library's: never touched
    (home / "eldenring-mods").mkdir()
    (home / "eldenring-mods" / "mine.me3").write_bytes(text(pkg("mod/x", "x")))
    (home / "eldenring-mods" / "mod" / "x").mkdir(parents=True)
    (home / "eldenring-mods" / "mod" / "x" / "x.dcx").write_bytes(b"x")
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    return loc, home, root


def new_root(home: Path) -> Path:
    return home / "b-eldenring"


def test_migration_gives_each_profile_its_folder_and_copies_what_two_share(world):
    loc, home, root = world
    out = migrate.migrate(loc)
    assert out is not None
    P = new_root(home)
    a, b, c, d = P / "a" / "a.me3", P / "b" / "b.me3", P / "c" / "c.me3", P / "d" / "d.me3"
    assert a.is_file() and b.is_file() and c.is_file() and d.is_file()
    # flora is used by both: both have a full copy, the library's original is gone
    for p in (P / "a", P / "b"):
        assert (p / "packages" / "flora" / "parts" / "f.dcx").read_bytes() == b"flora"
        assert (p / "packages" / "flora" / "regulation.bin").read_bytes() == b"reg"
    assert (P / "b" / "packages" / "hair" / "chr" / "h.dcx").read_bytes() == b"hair"
    assert not (P / "a" / "packages" / "hair").exists()  # only what a lists
    assert (P / "a" / "natives" / "ng" / "ng.dll").read_bytes() == b"dll"
    assert (P / "a" / "builds" / "combined-parameters" / "build.json").read_bytes() == b"{}"
    assert (P / "c" / "packages" / "zed" / "z.dcx").read_bytes() == b"zed"  # mod/ became packages/
    # the paths now start at the profile's own folder
    assert "path = 'packages/flora'" in a.read_text() and "path = 'natives/ng/ng.dll'" in a.read_text()
    assert "path = 'builds/combined-parameters'" in a.read_text()
    assert "path = 'packages/hair'" in b.read_text() and "path = 'packages/zed'" in c.read_text()
    # its records came along
    assert ps.load(a)["after_overlay"] == ["flora"]
    assert library.profile_backup(a).read_bytes() == b"a bak"
    assert (P / "a" / "a.offline.me3").read_bytes() == b"offline"
    # 4.2.0's profile: its state folder is renamed whole, its Shared mod folder moved and the link follows
    assert ps.load(d)["after_overlay"] == ["q"] and (P / "d" / ".bayle" / "settings.json").is_file()
    assert not (P / "d" / ".roundtable").exists() and (P / "d" / "packages" / "zed2" / "z2.dcx").is_file()
    assert (P / ".shared" / "lib-mod" / "v1" / "f.dcx").read_bytes() == b"shared"
    assert "path = '../.shared/lib-mod/v1'" in d.read_text()
    assert not root.exists() and not (home / "roundtable").exists()  # nothing was left in the old folders
    mine = home / "eldenring-mods"
    assert (mine / "mine.me3").is_file() and (mine / "mod" / "x" / "x.dcx").is_file()
    from bayle.platform import me3_paths

    found = [p for p in me3_paths.find_profiles(home, "eldenring", "eldenring") if not p.name.endswith(".offline.me3")]
    assert found == sorted([a, b, c, d, mine / "mine.me3"], key=lambda p: (p.name.lower(), str(p).lower()))


def test_the_second_run_does_nothing(world):
    loc, home, _root = world
    migrate.migrate(loc)
    after = tree(home)
    assert migrate.migrate(loc) is None
    assert tree(home) == after


def test_undo_restores_the_old_layout(world):
    loc, home, root = world
    before = tree(home)
    out = migrate.migrate(loc)
    assert out is not None and tree(home) != before
    rec = {"type": "profile-folders", "profile": out["profile"], "name": "eldenring", "operation": out["operation"]}
    assert undo.available(rec)
    assert undo.run(rec, lambda s: None, loc=loc).startswith("took back")
    assert tree(home) == before
    assert not (new_root(home) / "a").exists() and not (new_root(home) / "b").exists()
    assert not undo.available(rec)


def test_undo_refuses_when_a_migrated_profile_changed(world):
    loc, home, _root = world
    out = migrate.migrate(loc)
    assert out is not None
    a = new_root(home) / "a" / "a.me3"
    a.write_bytes(a.read_bytes() + b"# mine\n")
    now = tree(home)
    with pytest.raises(migrate.MigrateError):
        migrate.undo_migration(Path(out["operation"]))
    assert tree(home) == now


def test_a_clash_takes_the_next_name(world):
    loc, home, _root = world
    P = new_root(home)
    (P / "a").mkdir(parents=True)
    (P / "a" / "keep.txt").write_bytes(b"theirs")
    out = migrate.migrate(loc)
    assert out is not None and any("a-2" in n for n in out["notes"])
    assert (P / "a-2" / "a-2.me3").is_file() and (P / "b" / "b.me3").is_file()
    assert (P / "a" / "keep.txt").read_bytes() == b"theirs"
    assert not (P / "a" / "a.me3").exists()


def test_two_games_may_use_the_same_profile_name(world):
    loc, home, _root = world
    other = home / "rs-nightreign" / "profiles" / "a.me3"
    other.parent.mkdir(parents=True)
    other.write_bytes(NEW.replace("eldenring", "nightreign").encode())
    nr = Locations(catalog.NIGHTREIGN, Overrides(profiles_dir=str(home)))
    assert migrate.migrate(loc) is not None and migrate.migrate(nr) is not None
    assert (home / "b-eldenring" / "a" / "a.me3").is_file()
    assert (home / "b-nightreign" / "a" / "a.me3").is_file()


def test_an_interrupted_migration_is_undone_and_can_run_again(world, monkeypatch):
    loc, home, root = world
    before = tree(home)
    real, calls = B._move, {"n": 0}

    def dying(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B, "_move", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            migrate.migrate(loc)
    assert tree(home) != before  # half way
    migrate.finish_pending(new_root(home))
    assert tree(home) == before
    assert not list(new_root(home).glob(".rs-profile-folders-*"))
    assert migrate.migrate(loc) is not None and (new_root(home) / "b" / "packages" / "flora").is_dir()
    assert not root.exists()


def test_a_copy_that_does_not_match_is_never_committed(world, monkeypatch):
    loc, home, _root = world
    before = tree(home)
    real = shutil.copytree

    def bad(src, dst, *a, **k):
        out = real(src, dst, *a, **k)
        for f in Path(dst).rglob("*.dcx"):
            f.write_bytes(b"damaged")
        return out

    monkeypatch.setattr(shutil, "copytree", bad)
    with pytest.raises(migrate.MigrateError):
        migrate.migrate(loc)
    assert tree(home) == before and not list(new_root(home).glob(".rs-profile-folders-*"))


def test_nothing_moves_while_the_game_runs(world, monkeypatch):
    loc, home, _root = world
    before = tree(home)
    monkeypatch.setattr(Locations, "game_running", lambda self: True)
    assert migrate.migrate(loc) is None and tree(home) == before


# ----------------------------------------------------------------------------- install, remove, rename, duplicate
def mod_source(tmp_path: Path, version: str) -> Path:
    src = tmp_path / f"src-{version}" / "Grass"
    (src / "parts").mkdir(parents=True, exist_ok=True)
    (src / "parts" / "g.partsbnd.dcx").write_bytes(f"grass {version}".encode())
    return src


def test_install_and_remove_stay_inside_the_profiles_folder(tmp_path):
    profile = tmp_path / "profiles" / "main" / "main.me3"
    profile.parent.mkdir(parents=True)
    profile.write_bytes(NEW.encode())
    plan = install.plan_install(profile, mod_source(tmp_path, "1"), name="Grass", loc=er())
    assert Path(plan["dest"]).parent == profile.parent / "packages"
    out = install.install(profile, plan, loc=er())
    dest = Path(out["dest"])
    assert dest.parent == profile.parent / "packages" and (dest / "parts" / "g.partsbnd.dcx").is_file()
    assert "path = 'packages/" in profile.read_text()
    res = remove.uninstall(profile, 0, delete_folder=True, loc=er())
    assert res["removed_folder"] and not dest.exists()
    assert operations.problem(profile) is None


def test_the_launchers_files_for_a_profile_are_inside_its_folder(tmp_path):
    own = tmp_path / "profiles" / "main" / "main.me3"
    pf = library.ProfileFolder.of(own)
    assert pf.root == own.parent and pf.packages == own.parent / "packages" and pf.natives == own.parent / "natives"
    assert pf.build("combined-parameters").root == own.parent / "builds" / "combined-parameters"
    assert pf.sources("x").record == own.parent / "builds" / "x" / "sources" / "roundtable.json"
    assert library.state_of(own).root == own.parent / ".bayle"
    loose = tmp_path / "profiles" / "eldenring-mods" / "mine.me3"  # kept in a shared folder: its own builds apart
    assert library.ProfileFolder.of(loose).root == loose.parent / ".bayle" / "profiles" / "mine"
    assert not (tmp_path / "profiles" / "main").exists()  # nothing is made until asked


def test_a_folder_holding_several_profiles_is_nobodys_own(tmp_path):
    folder = tmp_path / "Mine"
    folder.mkdir()
    mine = folder / "Mine.me3"
    mine.write_bytes(NEW.encode())
    assert library.own_folder(mine) and library.named_folder(mine)
    (folder / "Mine.offline.me3").write_bytes(b"x")  # an offline copy and me3's default are not profiles
    (folder / "eldenring-default.me3").write_bytes(b"x")
    assert library.own_folder(mine)
    (folder / "other.me3").write_bytes(NEW.encode())
    assert not library.own_folder(mine) and library.named_folder(mine)
    assert not library.own_folder(folder / "other.me3")
    assert library.ProfileFolder.of(mine).root != folder  # its builds are kept apart, not in the shared folder
    renamed = tmp_path / "Wrong" / "right.me3"
    renamed.parent.mkdir()
    renamed.write_bytes(NEW.encode())
    assert not library.own_folder(renamed) and not library.named_folder(renamed)


def test_a_second_run_after_the_move_finds_nothing_and_old_state_is_still_read(tmp_path):
    folder = tmp_path / "x"
    (folder / ".roundtable").mkdir(parents=True)
    profile = folder / "x.me3"
    profile.write_bytes(NEW.encode())
    assert library.state_of(profile).root == folder / ".roundtable"  # an older version's state folder is read
    (folder / ".bayle").mkdir()
    assert library.state_of(profile).root == folder / ".bayle"


def test_custom_folder_names_are_followed(tmp_path, monkeypatch):
    from bayle.config import settings

    monkeypatch.setattr(
        settings,
        "load_settings",
        lambda: settings.LauncherSettings(
            game_folder_pattern="my-{game}", packages_folder="mods", shared_folder="Shared"
        ),
    )
    home = tmp_path / "profiles"
    assert library.game_root(home, "eldenring") == home / "my-eldenring"
    assert library.shared_root(home, "eldenring") == home / "my-eldenring" / "Shared"
    pf = library.ProfileFolder.of(home / "my-eldenring" / "p" / "p.me3")
    assert pf.packages == home / "my-eldenring" / "p" / "mods" and pf.natives.name == "natives"
    other = tmp_path / "elsewhere"
    monkeypatch.setattr(settings, "load_settings", lambda: settings.LauncherSettings(profiles_root=str(other)))
    assert library.game_root(home, "eldenring") == other / "b-eldenring"
    assert library.is_game_folder(other / "b-eldenring") and not library.is_game_folder(other / "mods")


def test_migration_follows_a_custom_game_folder_and_dot_folders_are_never_profiles(world, monkeypatch):
    from bayle.config import settings
    from bayle.platform import me3_paths

    monkeypatch.setattr(
        settings,
        "load_settings",
        lambda: settings.LauncherSettings(
            game_folder_pattern="my-{game}", shared_folder="Shared", packages_folder="mods"
        ),
    )
    loc, home, root = world
    assert migrate.migrate(loc) is not None
    P = home / "my-eldenring"
    assert (P / "a" / "a.me3").is_file() and (P / "a" / "mods" / "flora" / "parts" / "f.dcx").is_file()
    assert "path = 'mods/flora'" in (P / "a" / "a.me3").read_text()
    assert (P / "Shared" / "lib-mod" / "v1" / "f.dcx").is_file()
    (P / ".hidden").mkdir()
    (P / ".hidden" / ".hidden.me3").write_bytes(NEW.encode())
    found = me3_paths.find_profiles(home, "eldenring", "eldenring", [P])
    assert not any(".hidden" in str(f) for f in found) and (P / "a" / "a.me3") in found
