"""Renaming a profile (mods.profile_rename) moves players' files and re-keys the launcher's records: these are the
safety tests. Profiles in folders of their own (profiles/<name>/<name>.me3), in temporary folders only; the data folder is the conftest's."""

import os
import shutil
from pathlib import Path

import pytest

from roundtable_souls.config.settings import load_settings, save_settings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.merging import build as B
from roundtable_souls.mods import history, library, naming, operations, profile_rename
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.profile_rename import ProfileRenameError
from roundtable_souls.mods.rebuild import _key
from roundtable_souls.platform import trash

ME3 = (
    'profileVersion = "v1"\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n\r\n'
    "[[packages]]\r\nid = \"flora\"\r\npath = 'packages/flora'\r\n\r\n"
    "[[packages]]\r\npath = 'builds/combined-parameters'\r\n"
)
OTHER = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def tree(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and not p.name.endswith(".lock")
    }


def records(*profiles: Path) -> dict:
    """Everything outside the library the rename touches: the launcher's settings and the history folders."""
    s = load_settings()
    return {
        "setup": s.profile,
        "marks": dict(s.parameter_overlays),
        "history": {str(p): tree(history.folder(p)) if history.folder(p).is_dir() else None for p in profiles},
    }


@pytest.fixture
def world(tmp_path):
    home = tmp_path / "profiles"
    root = home / "roundtable" / "eldenring" / "profiles"
    a, b = root / "a" / "a.me3", root / "b" / "b.me3"
    lib = library.ProfileFolder.of(a)
    (lib.packages / "flora" / "parts").mkdir(parents=True)
    (lib.packages / "flora" / "parts" / "f.dcx").write_bytes(b"flora")
    (lib.builds / "combined-parameters").mkdir(parents=True)
    (lib.builds / "combined-parameters" / "build.json").write_bytes(b"{}")
    b.parent.mkdir(parents=True)
    a.write_bytes(ME3.encode())
    b.write_bytes(OTHER.encode())
    a.with_name("a.offline.me3").write_bytes(b"offline copy")
    library.ensure_state(library.state_of(a))
    ps.update(a, overlay={"package": "packages/flora", "rebuild": None}, after_overlay=["flora"])
    ps.update(b, after_overlay=["x"])
    library.profile_backup(a).write_bytes(b"a bak")
    history.snapshot(a, "first")
    save_settings(setup=str(a), parameter_overlays={_key(a): {"package": "p"}, _key(b): {"package": "q"}})
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    return loc, root, lib, a, b


def test_rename_then_undo_is_byte_exact(world):
    loc, root, lib, a, b = world
    before, had = tree(root), records(a)
    out = profile_rename.apply(profile_rename.preview(a, "My Run", loc=loc), loc=loc)
    new = root / "My Run" / "My Run.me3"
    assert out["profile"] == str(new) and new.is_file() and not a.exists() and not a.parent.exists()
    assert not a.with_name("a.offline.me3").exists()
    assert new.with_name("My Run.offline.me3").read_bytes() == b"offline copy"
    assert library.profile_backup(new).read_bytes() == b"a bak" and not library.profile_backup(a).exists()
    assert (new.parent / "builds" / "combined-parameters" / "build.json").is_file()  # the folder moved whole
    assert (new.parent / "packages" / "flora" / "parts" / "f.dcx").read_bytes() == b"flora"
    assert "builds/combined-parameters" in new.read_text()  # the relative entry still points inside it
    assert ps.load(new)["after_overlay"] == ["flora"] and ps.load(a) == {} and ps.load(b)["after_overlay"] == ["x"]
    s = load_settings()
    assert s.profile == str(new) and _key(new) in s.parameter_overlays and _key(a) not in s.parameter_overlays
    assert tree(history.folder(new)) == tree(history.folder(a))  # copied; the old copies stay
    assert profile_rename.undo_rename(Path(out["operation"])).startswith("took back")
    assert tree(root) == before
    now = records(a)
    assert now["setup"] == had["setup"] and now["marks"] == had["marks"] and now["history"] == had["history"]


def test_case_only_rename_and_undo(world):
    loc, root, lib, a, _b = world
    before = tree(root)
    out = profile_rename.apply(profile_rename.preview(a, "A", loc=loc), loc=loc)
    assert "A" in os.listdir(root) and "a" not in os.listdir(root) and "A.me3" in os.listdir(root / "A")
    profile_rename.undo_rename(Path(out["operation"]))
    assert tree(root) == before and "a" in os.listdir(root) and "a.me3" in os.listdir(root / "a")


def test_refusals_change_nothing(world, monkeypatch):
    loc, root, lib, a, _b = world
    before, had = tree(root), records(a)
    for name in ("B", "b", "", "a", "CON", "bad:name", "x.", "profiles", "x-default", "x.offline"):
        pre = profile_rename.preview(a, name, loc=loc)
        assert pre.refusals and not pre.ok, name
        with pytest.raises(ProfileRenameError):
            profile_rename.apply(pre, loc=loc)
    with monkeypatch.context() as m:
        m.setattr(naming, "MAX_PATH", 20)
        assert profile_rename.preview(a, "long name", loc=loc).refusals
    with monkeypatch.context() as m:
        m.setattr(Locations, "game_running", lambda self: True)
        assert profile_rename.preview(a, "fine", loc=loc).refusals == [profile_rename.GAME_OPEN]
    default = root / "eldenring-default.me3"
    default.write_bytes(OTHER.encode())
    assert profile_rename.preview(default, "mine", loc=loc).refusals
    default.unlink()
    assert tree(root) == before and records(a) == had
    pre = profile_rename.preview(a, "fine", loc=loc)  # then the profile changes before Rename is pressed
    a.write_bytes(a.read_bytes() + b"# edited\n")
    edited = tree(root)
    with pytest.raises(ProfileRenameError):
        profile_rename.apply(pre, loc=loc)
    assert tree(root) == edited and records(a)["setup"] == had["setup"]


def test_an_interrupted_rename_recovers(world, monkeypatch):
    loc, root, lib, a, _b = world
    before = tree(root)
    # dying in the middle of the commit: the whole operation is undone
    real, calls = B._move, {"n": 0}

    def dying(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B, "_move", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            profile_rename.apply(profile_rename.preview(a, "z", loc=loc), loc=loc)
    assert "did not finish" in (operations.problem(a) or "")
    assert operations.recover(a)
    assert tree(root) == before and operations.problem(a) is None and load_settings().profile == str(a)

    # dying after every step but before the launcher's records were re-keyed: recovery finishes that
    with monkeypatch.context() as m:
        m.setattr(profile_rename, "finish_state", lambda op: (_ for _ in ()).throw(Crash()))
        with pytest.raises(Crash):
            profile_rename.apply(profile_rename.preview(a, "z", loc=loc), loc=loc)
    new = root / "z" / "z.me3"
    assert new.is_file() and load_settings().profile == str(a)
    operations.recover(new)
    assert load_settings().profile == str(new) and _key(new) in load_settings().parameter_overlays
    assert history.folder(new).is_dir()
    operations.recover(new)  # idempotent
    assert load_settings().profile == str(new)


def test_an_older_launchers_rollback_cannot_delete_a_folder(world):
    """The steps are files written and folders moved: a rollback never deletes a folder."""
    loc, root, lib, a, _b = world
    out = profile_rename.apply(profile_rename.preview(a, "z", loc=loc), loc=loc)
    steps = B.Operation.load(Path(out["operation"])).steps
    assert {s["type"] for s in steps} <= {"file", "move"} and any(s["type"] == "move" for s in steps)
    B._undo(B.Operation.load(Path(out["operation"])))  # what an older launcher does with an active operation
    assert a.is_file() and (lib.builds / "combined-parameters" / "build.json").is_file()
    assert (lib.packages / "flora" / "parts" / "f.dcx").read_bytes() == b"flora"


def test_duplicate_and_its_undo(world, monkeypatch):
    loc, root, lib, a, b = world
    with pytest.raises(ProfileRenameError):  # a has its own build folder: not copied yet
        profile_rename.duplicate(a, loc=loc)
    (b.parent / "mod" / "hair").mkdir(parents=True)
    (b.parent / "mod" / "hair" / "h.dcx").write_bytes(b"hair")
    out = profile_rename.duplicate(b, loc=loc)
    copy = root / "b copy" / "b copy.me3"
    assert Path(out["profile"]) == copy and copy.read_bytes() == OTHER.encode()
    assert (copy.parent / "mod" / "hair" / "h.dcx").read_bytes() == b"hair"  # the mod folders are copied too
    assert (b.parent / "mod" / "hair" / "h.dcx").is_file()
    second = profile_rename.duplicate(b, loc=loc)
    assert second["name"] == "b copy 2"
    binned = []
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: binned.append(p) or shutil.rmtree(p))
    profile_rename.undo_duplicate(Path(out["operation"]))
    assert binned == [copy.parent] and (root / "b copy 2" / "b copy 2.me3").is_file() and b.is_file()
