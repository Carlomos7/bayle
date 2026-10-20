"""Adopting a setup into the library (mods.adopt) moves players' files: these are the safety tests. Synthetic setups in
temporary folders only; the data folder is the conftest's."""

import os
from pathlib import Path

import pytest

from roundtable_souls.config.settings import load_settings, save_settings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.merging import build as B
from roundtable_souls.mods import adopt, configs, library, naming, operations
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.profile_edit import ModError

A_ME3 = (
    'profileVersion = "v1"\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n\r\n'
    "# the flowers\r\n[[packages]]\r\nid = \"flora\"\r\npath = 'mod/flora'\r\n\r\n"
    '[[packages]]\r\nid = "grass"\r\npath = \'mod/grass\'\r\nload_after = [{ id = "flora", optional = true }]\r\n\r\n'
    "[[packages]]\r\npath = 'mod/Plain Pack'\r\n\r\n"
    "[[natives]]\r\npath = 'natives/Foo/foo.dll'\r\nload_early = true\r\n\r\n"
    "[[natives]]\r\npath = 'natives/loose.dll'\r\n\r\n"
    "[[packages]]\r\nid = \"far\"\r\npath = '../../elsewhere/far'\r\n"
)
B_ME3 = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n# only grass\n[[packages]]\nid = "grass"\n'
    "path = 'mod/grass'\n"
)


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def tree(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and ".roundtable" not in p.relative_to(folder).as_posix() and not p.name.endswith(".lock")
    }


@pytest.fixture
def world(tmp_path):
    """profiles/eldenring-mods holds two profiles and their mods; elsewhere/far is outside; the launcher's records
    point into the setup."""
    root = tmp_path / "profiles"
    s = root / "eldenring-mods"
    for rel, data in {
        "mod/flora/parts/a.dcx": b"flora",
        "mod/grass/parts/g.dcx": b"grass",
        "mod/Plain Pack/chr/c.dcx": b"plain",
        "mod/unused-thing/parts/u.dcx": b"unused",
        "natives/Foo/foo.dll": b"foo",
        "natives/Foo/foo.ini": b"[a]\nb=1\n",
        "natives/loose.dll": b"loose",
    }.items():
        (s / rel).parent.mkdir(parents=True, exist_ok=True)
        (s / rel).write_bytes(data)
    far = tmp_path / "elsewhere" / "far"
    (far / "parts").mkdir(parents=True)
    (far / "parts" / "f.dcx").write_bytes(b"far")
    a, b = s / "a.me3", s / "b.me3"
    a.write_bytes(A_ME3.encode())
    b.write_bytes(B_ME3.encode())
    (s / "a.me3.bak").write_bytes(b"old bak")
    ps.update(a, overlay={"package": "mod/grass", "rebuild": None}, after_overlay=["flora"])
    save_settings(
        setup=str(a),
        native_configs={configs.key_for(s / "natives/Foo/foo.dll"): [str(s / "natives/Foo/foo.ini")]},
    )
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(root)))
    return loc, root, s


def adopt_it(loc, **kw):
    [setup] = adopt.setups(loc)
    pre = adopt.preview(setup, loc=loc, **kw)
    assert pre.ok, pre.refusals
    return pre, adopt.adopt(pre, loc=loc)


def resolved(profile: Path):
    from roundtable_souls.formats import me3_profile

    return [
        (e["name"], os.path.normcase(os.path.abspath(me3_profile.resolve(profile, e["path"]))))
        for e in me3_profile.entries(me3_profile.read_text(profile))
    ]


def hashes(profile: Path):
    from roundtable_souls.formats import me3_profile

    out = {}
    for e in me3_profile.entries(me3_profile.read_text(profile)):
        p = me3_profile.resolve(profile, e["path"])
        out[e["name"]] = {
            x.name + str(x.stat().st_size) for x in ([p] if p.is_file() else p.rglob("*") if p.is_dir() else [])
        }
    return out


def test_adopt_then_undo_round_trip(world):
    """A1: after adopting, every entry still reaches the same files and the records follow; undoing puts every
    file, profile byte and record back."""
    loc, root, s = world
    before_tree = tree(root.parent)
    before_hash = {p.name: hashes(p) for p in (s / "a.me3", s / "b.me3")}
    before_settings = load_settings()
    pre, out = adopt_it(loc)
    lib = library.ModLibrary.at(root, "eldenring")
    a, b = lib.profile("a"), lib.profile("b")
    assert a.is_file() and b.is_file() and not (s / "a.me3").exists() and not (s / "b.me3").exists()
    assert {p.name: hashes(p) for p in (a, b)} == {"a.me3": before_hash["a.me3"], "b.me3": before_hash["b.me3"]}
    assert (lib.package("flora") / "parts" / "a.dcx").read_bytes() == b"flora"
    assert (lib.package("grass")).is_dir() and (lib.native("foo") / "foo.dll").is_file()
    assert (s / "mod" / "unused-thing").is_dir() and (s / "natives" / "loose.dll").is_file()  # left where they are
    text = a.read_bytes().decode()
    assert "# the flowers\r\n" in text and 'load_after = [{ id = "flora", optional = true }]' in text
    assert 'id = "Plain Pack"' in text  # a package without an id keeps the name other entries called it
    assert "path = '../packages/grass'" in text and "../natives/foo/foo.dll" in text
    assert b.read_bytes().decode().count("../packages/grass") == 1 and "# only grass\n" in b.read_bytes().decode()
    assert not operations.pending(a) and operations.problem(a) is None
    now = load_settings()
    assert list(now.native_configs) == [configs.key_for(lib.native("foo") / "foo.dll")]
    assert now.native_configs[configs.key_for(lib.native("foo") / "foo.dll")] == [str(lib.native("foo") / "foo.ini")]
    assert now.setup == str(a)
    assert ps.load(a)["overlay"]["package"] == "../packages/grass" and ps.load(a)["after_overlay"] == ["flora"]
    assert (lib.state.backups / "a.me3.bak").read_bytes() == b"old bak"
    msg = adopt.undo_adopt(Path(out["operation"]))
    assert "took back" in msg
    assert tree(root.parent) == before_tree
    assert load_settings().native_configs == before_settings.native_configs and load_settings().setup == str(
        s / "a.me3"
    )
    assert not a.exists() and not (lib.state.backups / "a.me3.bak").exists()


def test_a_crash_while_adopting_is_undone_and_play_is_blocked_until_then(world, monkeypatch):
    """A2: a move failing in the middle undoes itself; a journal left 'activating' by a dying process blocks Play
    and is undone by recovery, from the old folder or the library."""
    loc, root, s = world
    before = tree(root.parent)
    [setup] = adopt.setups(loc)
    pre = adopt.preview(setup, loc=loc)
    real = B._move
    calls = {"n": 0}

    def failing(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk full")
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B, "_move", failing)
        with pytest.raises(OSError):
            adopt.adopt(pre, loc=loc)
    assert tree(root.parent) == before and not operations.pending(s / "a.me3")

    calls["n"] = 0

    def dying(src, dst):
        calls["n"] += 1
        if calls["n"] == 3:
            raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B, "_move", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            adopt.adopt(adopt.preview(setup, loc=loc), loc=loc)
    assert tree(root.parent) != before
    assert "did not finish" in (operations.problem(s / "a.me3") or "")
    said = operations.recover(s / "a.me3")
    assert said and "undone" in said[0]
    assert tree(root.parent) == before and operations.problem(s / "a.me3") is None
    assert load_settings().setup == str(s / "a.me3")

    # a prepared move step that is given up leaves both sides alone
    kept = s / "mod" / "flora"
    op = B.Operation(root / "scratch-ops", "x")
    op.move_folder(kept, root / "elsewhere-flora")
    op.discard()
    assert kept.is_dir() and not (root / "elsewhere-flora").exists()

    # dying after every move but before the launcher's records were re-keyed: recovery finishes that
    with monkeypatch.context() as m:
        m.setattr(adopt, "finish_state", lambda op: (_ for _ in ()).throw(Crash()))
        with pytest.raises(Crash):
            adopt.adopt(adopt.preview(setup, loc=loc), loc=loc)
    lib = library.ModLibrary.at(root, "eldenring")
    assert load_settings().setup == str(s / "a.me3")
    operations.recover(lib.profile("a"))
    assert load_settings().setup == str(lib.profile("a"))
    assert configs.key_for(lib.native("foo") / "foo.dll") in load_settings().native_configs


def test_refusals_change_nothing(world, monkeypatch):
    """A3: a profile edited after the preview, a path too long, a library name taken: no file or folder changes."""
    loc, root, s = world
    before = tree(root.parent)
    [setup] = adopt.setups(loc)
    pre = adopt.preview(setup, loc=loc)
    (s / "b.me3").write_bytes(B_ME3.encode() + b"# edited meanwhile\n")
    edited = tree(root.parent)
    with pytest.raises(ModError):
        adopt.adopt(pre, loc=loc)
    assert tree(root.parent) == edited and not (root / "rs-eldenring" / "packages").exists()
    (s / "b.me3").write_bytes(B_ME3.encode())

    monkeypatch.setattr(naming, "MAX_PATH", 60)  # real paths this long can't be made here
    pre = adopt.preview(setup, loc=loc)
    assert not pre.ok and "too long" in " ".join(pre.refusals)
    with pytest.raises(ModError):
        adopt.adopt(pre, loc=loc)
    assert tree(root.parent) == before
    monkeypatch.setattr(naming, "MAX_PATH", 220)

    (root / "rs-eldenring" / "profiles").mkdir(parents=True)
    (root / "rs-eldenring" / "profiles" / "b.me3").write_bytes(B_ME3.encode())
    pre = adopt.preview(setup, loc=loc)
    assert not pre.ok and "already has a profile called b" in " ".join(pre.refusals)
    assert tree(root.parent) == {**before, "profiles/rs-eldenring/profiles/b.me3": B_ME3.encode()}


def test_undo_is_refused_after_an_adopted_profile_changed(world):
    """A4: an adopted profile edited after adopting: Undo is refused with the reason and nothing changes."""
    loc, root, s = world
    _pre, out = adopt_it(loc)
    lib = library.ModLibrary.at(root, "eldenring")
    lib.profile("b").write_bytes(lib.profile("b").read_bytes() + b"# my edit\n")
    mid = tree(root.parent)
    settings = load_settings()
    with pytest.raises(adopt.AdoptError, match="changed after it was adopted"):
        adopt.undo_adopt(Path(out["operation"]))
    assert tree(root.parent) == mid and load_settings().setup == settings.setup
    assert not (s / "a.me3").exists()
