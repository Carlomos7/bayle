"""Move into Bayle's folder (mods.move_in) moves players' files: the safety tests. Temporary folders only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.merging import build as B
from roundtable_souls.mods import library, move_in, undo
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.platform import trash
from roundtable_souls.ui.pages.mods.presenter import ModsPresenter

NEW = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def text(*entries: str) -> bytes:
    return (NEW + "".join(entries)).encode()


def pkg(path: str) -> str:
    return f"\n[[packages]]\npath = '{path}'\n"


def tree(folder: Path) -> dict[str, bytes]:
    """Every file below folder but the launcher's journals and locks."""
    skip = (B.OPS, library.OPS)
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and not set(skip) & set(p.relative_to(folder).parts) and not p.name.endswith(".lock")
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    """eldenring-mods holds a (shared + private package, a native, an outside path) and b (shared only)."""
    home = tmp_path / "profiles"
    plain = home / "eldenring-mods"
    for rel, data in {
        "mod/shared/s.dcx": b"shared",
        "mod/private/p.dcx": b"private",
        "natives/n/n.dll": b"dll",
        ".roundtable/backups/a.me3.bak": b"bak",
    }.items():
        (plain / rel).parent.mkdir(parents=True, exist_ok=True)
        (plain / rel).write_bytes(data)
    outside = tmp_path / "elsewhere" / "far"
    outside.mkdir(parents=True)
    (outside / "f.dcx").write_bytes(b"far")
    a = plain / "a.me3"
    entries = (pkg("mod/shared"), pkg("mod/private"), "\n[[natives]]\npath = 'natives/n/n.dll'\n")
    a.write_bytes(text(*entries, pkg(outside.as_posix())))
    (plain / "b.me3").write_bytes(text(pkg("mod/shared")))
    (plain / "a.offline.me3").write_bytes(b"offline")
    (plain / ".roundtable" / "settings.json").write_text(
        '{"version": 1, "schema": 1, "profiles": {"a.me3": {"after_overlay": ["x"]}, "b.me3": {"after_overlay": ["y"]}}}',
        encoding="utf-8",
    )
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    return loc, home, plain, a


def target(home: Path, name: str = "a") -> Path:
    return library.game_root(home, "eldenring") / "profiles" / name


def test_a_shared_mod_is_copied_a_private_one_moved_and_paths_follow(world):
    loc, home, plain, a = world
    p = move_in.plan(a, loc)
    assert p.ok and move_in.counts(p) == (2, 1)
    out = move_in.apply(p, loc=loc)
    new = target(home) / "a.me3"
    assert Path(out["profile"]) == new
    layout = library.ProfileFolder(target(home))
    assert (layout.packages / "shared" / "s.dcx").read_bytes() == b"shared"
    assert (plain / "mod" / "shared" / "s.dcx").read_bytes() == b"shared"  # b still has it
    assert (layout.packages / "private" / "p.dcx").read_bytes() == b"private"
    assert not (plain / "mod" / "private").exists()
    assert (layout.natives / "n" / "n.dll").read_bytes() == b"dll"
    body = new.read_text()
    assert f"path = '{layout.packages.name}/shared'" in body and "natives/n/n.dll" in body
    assert "elsewhere" in body  # outside the folder: still points there
    assert p.stays and p.stays[0].endswith("far")
    assert not a.exists() and not (plain / "a.offline.me3").exists()
    assert (target(home) / "a.offline.me3").read_bytes() == b"offline"
    assert ps.load(new)["after_overlay"] == ["x"] and library.profile_backup(new).read_bytes() == b"bak"
    # b is untouched and still has its settings
    assert (plain / "b.me3").is_file() and ps.load(plain / "b.me3")["after_overlay"] == ["y"]


def test_an_own_folder_profile_moves_whole(world):
    loc, home, _plain, _a = world
    own = home / "solo"
    (own / "mod" / "m").mkdir(parents=True)
    (own / "mod" / "m" / "m.dcx").write_bytes(b"m")
    (own / "solo.me3").write_bytes(text(pkg("mod/m")))
    before = tree(own)
    out = move_in.apply(move_in.plan(own / "solo.me3", loc), loc=loc)
    assert not own.exists() and tree(target(home, "solo")) == before
    rec = {"type": move_in.KIND, "operation": out["operation"], "profile": out["profile"]}
    undo.run(rec, lambda s: None, loc=loc)
    assert tree(own) == before and not target(home, "solo").exists()


def test_refusals(world, monkeypatch):
    loc, home, plain, a = world
    target(home).mkdir(parents=True)
    assert "already exists" in " ".join(move_in.plan(a, loc).refusals)
    target(home).rmdir()
    with monkeypatch.context() as m:
        m.setattr(Locations, "game_running", lambda self: True)
        assert move_in.GAME_OPEN in move_in.plan(a, loc).refusals
    shutil.rmtree(plain / "mod" / "private")
    assert "not there" in " ".join(move_in.plan(a, loc).refusals)
    with pytest.raises(move_in.MoveInError):
        move_in.apply(move_in.plan(a, loc), loc=loc)
    inside = target(home, "x") / "x.me3"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(text())
    assert "already in Roundtable" in " ".join(move_in.plan(inside, loc).refusals)
    assert not move_in.outside(inside, loc) and move_in.outside(a, loc)


def test_a_sibling_that_cannot_be_read_makes_every_mod_a_copy(world):
    loc, _home, plain, a = world
    (plain / "b.me3").write_bytes(b"\xff\xfe not text")
    assert move_in.counts(move_in.plan(a, loc)) == (0, 3)


def test_a_crash_half_way_is_undone_by_recovery(world, monkeypatch):
    loc, home, _plain, a = world
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
            move_in.apply(move_in.plan(a, loc), loc=loc)
    assert tree(home) != before
    assert move_in.recover(loc)
    assert tree(home) == before
    assert not list((library.game_root(home, "eldenring") / "profiles").glob(".move-in-*"))


def test_a_copy_that_does_not_match_is_never_committed(world, monkeypatch):
    loc, home, _plain, a = world
    before = tree(home)
    real = shutil.copytree

    def bad(src, dst, *args, **kw):
        out = real(src, dst, *args, **kw)
        for f in Path(dst).rglob("*.dcx"):
            f.write_bytes(b"damaged")
        return out

    monkeypatch.setattr(shutil, "copytree", bad)
    with pytest.raises(move_in.MoveInError):
        move_in.apply(move_in.plan(a, loc), loc=loc)
    assert tree(home) == before


def test_undo_is_byte_identical_and_refuses_after_edits(world):
    loc, home, _plain, a = world
    before = tree(home)
    out = move_in.apply(move_in.plan(a, loc), loc=loc)
    rec = {"type": move_in.KIND, "operation": out["operation"], "profile": out["profile"]}
    assert undo.available(rec)
    new = Path(out["profile"])
    original = new.read_bytes()
    new.write_bytes(original + b"\n# edited")
    with pytest.raises(undo.UndoError, match="changed after"):
        undo.run(rec, lambda s: None, loc=loc)
    new.write_bytes(original)
    undo.run(rec, lambda s: None, loc=loc)
    assert tree(home) == before


def test_the_confirm_words():
    title, changes, safety, apply = ModsPresenter().move_in_confirm("a", "eldenring-mods", 2, 1)
    assert title == "Move a into Bayle's folder?"
    assert changes == ("2 mods move, 1 are copied because other profiles in eldenring-mods use them.",)
    assert (safety, apply) == ("Undo in Activity.", "Move")
    assert ModsPresenter().move_in_confirm("a", "f", 3, 0)[1] == ("3 mods move.",)
