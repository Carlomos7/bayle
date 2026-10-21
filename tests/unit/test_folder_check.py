"""A profile's folder in the launcher's profiles folder: check(), Rename folder and Split into folders (mods.folder_check,
mods.folder_split) move players' files, so these are the safety tests. Temporary folders only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.merging import build as B
from roundtable_souls.mods import folder_check as fc
from roundtable_souls.mods import folder_split as fs
from roundtable_souls.mods import library, operations, undo
from roundtable_souls.platform import trash

NEW = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def text(*paths: str) -> bytes:
    return (NEW + "".join(f"\n[[packages]]\npath = '{p}'\n" for p in paths)).encode()


def tree(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and ".roundtable-ops" not in p.relative_to(folder).parts[0] and not p.name.endswith(".lock")
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "profiles"
    profiles = library.game_root(home, "eldenring") / "profiles"
    # "Mine" holds Mine.me3 (the keeper) and other.me3; "pack" holds a.me3 and b.me3; "wrong" holds just right.me3
    mine, pack, wrong = profiles / "Mine", profiles / "pack", profiles / "wrong"
    for rel, data in {
        "Mine/mod/flora/f.dcx": b"flora",
        "Mine/mod/hair/h.dcx": b"hair",
        "Mine/mod/solo/s.dcx": b"solo",
        "pack/mod/x/x.dcx": b"x",
        "pack/mod/y/y.dcx": b"y",
        "wrong/mod/z/z.dcx": b"z",
    }.items():
        (profiles / rel).parent.mkdir(parents=True, exist_ok=True)
        (profiles / rel).write_bytes(data)
    (mine / "Mine.me3").write_bytes(text("mod/flora", "mod/solo"))
    (mine / "other.me3").write_bytes(text("mod/flora", "mod/hair"))
    (pack / "a.me3").write_bytes(text("mod/x"))
    (pack / "b.me3").write_bytes(text("mod/x", "mod/y"))
    (wrong / "right.me3").write_bytes(text("mod/z"))
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    return loc, home, profiles


def test_check_tells_the_four_cases_apart(world):
    loc, home, profiles = world
    assert fc.check(profiles / "wrong" / "right.me3", loc).kind == fc.MISNAMED
    assert fc.check(profiles / "wrong" / "right.me3", loc).folder == "wrong"
    crowded = fc.check(profiles / "pack" / "a.me3", loc)
    assert crowded.kind == fc.CROWDED and crowded.count == 2
    (profiles / "ok").mkdir()
    (profiles / "ok" / "OK.me3").write_bytes(text())
    assert fc.check(profiles / "ok" / "OK.me3", loc).kind == fc.OK
    (home / "plain").mkdir()
    (home / "plain" / "p.me3").write_bytes(text())
    assert fc.check(home / "plain" / "p.me3", loc).kind == fc.OUTSIDE


def test_rename_folder_and_undo_are_byte_identical(world):
    loc, _home, profiles = world
    before = tree(profiles)
    out = fc.rename_folder(profiles / "wrong" / "right.me3", loc)
    new = profiles / "right" / "right.me3"
    assert Path(out["profile"]) == new and new.is_file() and not (profiles / "wrong").exists()
    assert (profiles / "right" / "mod" / "z" / "z.dcx").read_bytes() == b"z"
    assert fc.check(new, loc).kind == fc.OK
    rec = {"type": fc.KIND, "operation": out["operation"]}
    assert undo.available(rec)
    undo.run(rec, lambda s: None, loc=loc)
    assert tree(profiles) == before and (profiles / "wrong" / "right.me3").is_file()


def test_rename_folder_refuses_a_taken_name_a_running_game_and_a_good_folder(world, monkeypatch):
    loc, _home, profiles = world
    before = tree(profiles)
    (profiles / "right").mkdir()
    with pytest.raises(fc.FolderError, match="right is already there"):
        fc.rename_folder(profiles / "wrong" / "right.me3", loc)
    (profiles / "right").rmdir()
    with pytest.raises(fc.FolderError, match="does not need renaming"):
        fc.rename_folder(profiles / "pack" / "a.me3", loc)
    monkeypatch.setattr(Locations, "game_running", lambda self: True)
    with pytest.raises(fc.FolderError, match="Close the game"):
        fc.rename_folder(profiles / "wrong" / "right.me3", loc)
    assert tree(profiles) == before


def test_split_copies_shared_moves_private_and_rewrites_paths(world):
    loc, _home, profiles = world
    pre = fs.preview(profiles / "Mine" / "other.me3", loc)
    assert pre.ok and (pre.profiles, pre.copies, pre.moves) == (
        2,
        1,
        3,
    )  # flora copied; hair moved; flora and solo of the keeper go to packages/
    out = fs.split(profiles / "Mine" / "other.me3", loc)
    assert (out["profiles"], out["copies"], out["moves"]) == (2, 1, 3)
    other = profiles / "other"
    assert Path(out["profile"]) == other / "other.me3"
    assert (other / "packages" / "flora" / "f.dcx").read_bytes() == b"flora"  # copy
    assert (other / "packages" / "hair" / "h.dcx").read_bytes() == b"hair"  # moved
    assert not (profiles / "Mine" / "mod" / "hair").exists() and not (profiles / "Mine" / "packages" / "hair").exists()
    assert (profiles / "Mine" / "packages" / "flora" / "f.dcx").is_file()  # the keeper keeps the original, as packages/
    assert (profiles / "Mine" / "packages" / "solo" / "s.dcx").is_file()
    assert not (profiles / "Mine" / "other.me3").exists() and (profiles / "Mine" / "Mine.me3").is_file()
    body = (other / "other.me3").read_text()
    assert "path = 'packages/flora'" in body and "path = 'packages/hair'" in body
    assert fc.check(other / "other.me3", loc).kind == fc.OK
    assert fc.check(profiles / "Mine" / "Mine.me3", loc).kind == fc.OK


def test_split_follows_absolute_entry_paths_as_relative_ones(world):
    loc, _home, profiles = world
    mine = profiles / "Mine"
    (mine / "other.me3").write_bytes(text((mine / "mod" / "hair").as_posix(), (mine / "mod" / "flora").as_posix()))
    fs.split(mine / "other.me3", loc)
    body = (profiles / "other" / "other.me3").read_text()
    assert "path = 'packages/hair'" in body and "path = 'packages/flora'" in body and "Mine" not in body


def test_split_without_a_keeper_gives_every_profile_a_folder(world):
    loc, _home, profiles = world
    fs.split(profiles / "pack" / "a.me3", loc)
    # x is shared: a (first) gets a copy, b (last) takes the original; y is only b's
    assert (profiles / "a" / "packages" / "x" / "x.dcx").read_bytes() == b"x"
    assert (profiles / "b" / "packages" / "x" / "x.dcx").read_bytes() == b"x"
    assert (profiles / "b" / "packages" / "y" / "y.dcx").read_bytes() == b"y"
    assert not (profiles / "pack" / "a.me3").exists() and not (profiles / "pack" / "mod" / "x").exists()


def test_split_undo_is_byte_identical(world):
    loc, _home, profiles = world
    before = tree(profiles)
    for name in ("Mine", "pack"):
        first = sorted((profiles / name).glob("*.me3"))[0]
        out = fs.split(first, loc)
        assert tree(profiles) != before
        rec = {"type": fs.KIND, "operation": out["operation"]}
        assert undo.available(rec)
        undo.run(rec, lambda s: None, loc=loc)
    assert tree(profiles) == before


def test_split_undo_refuses_when_a_profile_changed(world):
    loc, _home, profiles = world
    out = fs.split(profiles / "pack" / "a.me3", loc)
    (profiles / "a" / "a.me3").write_bytes(b"changed")
    with pytest.raises(undo.UndoError, match="changed after the split"):
        undo.run({"type": fs.KIND, "operation": out["operation"]}, lambda s: None, loc=loc)
    assert (profiles / "a" / "a.me3").read_bytes() == b"changed"


def test_split_refuses_a_name_clash_and_a_running_game(world, monkeypatch):
    loc, _home, profiles = world
    before = tree(profiles)
    (profiles / "b").mkdir()
    with pytest.raises(fc.FolderError, match="A folder called b is already there"):
        fs.split(profiles / "pack" / "a.me3", loc)
    (profiles / "b").rmdir()
    monkeypatch.setattr(Locations, "game_running", lambda self: True)
    with pytest.raises(fc.FolderError, match="Close the game"):
        fs.split(profiles / "pack" / "a.me3", loc)
    assert tree(profiles) == before


def test_an_interrupted_split_is_undone_by_recovery(world, monkeypatch):
    loc, _home, profiles = world
    before = tree(profiles)
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
            fs.split(profiles / "pack" / "a.me3", loc)
    assert tree(profiles) != before
    operations.recover(profiles / "pack" / "b.me3")
    assert tree(profiles) == before
    assert fs.split(profiles / "pack" / "a.me3", loc)["profiles"] == 2  # and it can run again
