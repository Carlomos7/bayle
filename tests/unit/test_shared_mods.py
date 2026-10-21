"""The Library (mods.shared_mods) moves players' mod files between profiles: the safety tests. Temporary folders only.

Profiles are home/roundtable/eldenring/profiles/<name>/<name>.me3 with packages/<mod>/; the library sits beside profiles/."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

import pytest

from roundtable_souls.formats import me3_profile
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.merging import build as B
from roundtable_souls.mods import library, operations, profile_rename, shared_mods, undo
from roundtable_souls.platform import trash

HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def tree(home: Path) -> dict[str, bytes]:
    """Every file below home but the launcher's own records (journals, locks, backups, history)."""
    skip = {B.OPS, library.OPS, library.STATE}
    return {
        p.relative_to(home).as_posix(): p.read_bytes()
        for p in Path(home).rglob("*")
        if p.is_file() and not skip & set(p.relative_to(home).parts) and not p.name.endswith(".lock")
    }


def make(root: Path, name: str, mods: dict[str, dict[str, bytes]]) -> Path:
    folder = root / name
    entries = ""
    for mod, files in mods.items():
        for rel, data in files.items():
            (folder / "packages" / mod / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / "packages" / mod / rel).write_bytes(data)
        entries += f"\n[[packages]]\nid = '{mod}'\npath = 'packages/{mod}'\n"
    profile = folder / f"{name}.me3"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_bytes((HEAD + entries).encode())
    return profile


class Bin:
    """A Recycle Bin in a temporary folder."""

    def __init__(self, where: Path):
        self.where = where

    def send(self, path: Path) -> dict:
        n = len(list(self.where.glob("*")))
        dst = self.where / str(n) / Path(path).name
        dst.parent.mkdir(parents=True)
        shutil.move(str(path), dst)
        return {"item": str(dst), "original": str(path), "info": ""}

    def exists(self, record: dict | None) -> bool:
        return bool(record) and Path(record["item"]).exists()  # type: ignore[index]

    def restore(self, record: dict, dest: Path | None = None) -> Path:
        target = Path(dest or record["original"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(record["item"], target)
        return target


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "profiles"
    root = home / "roundtable" / "eldenring" / "profiles"
    grass = {"g.dcx": b"grass", "sub/g2.dcx": b"grass2"}
    a = make(root, "a", {"grass": grass, "sky": {"s.dcx": b"sky"}})
    b = make(root, "b", {"grass": grass})
    c = make(root, "c", {"fog": {"f.dcx": b"fog"}})
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    bin_ = Bin(tmp_path / "bin")
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", bin_.send)
    monkeypatch.setattr(trash, "exists", bin_.exists)
    monkeypatch.setattr(trash, "restore", bin_.restore)
    lib = library.library_root(home, "eldenring")
    return loc, home, root, lib, a, b, c


def index_of(profile: Path, name: str) -> int:
    return next(e["index"] for e in me3_profile.entries(profile.read_text()) if e["id"] == name)


def link(profile: Path, name: str) -> str:
    return next(e["path"] for e in me3_profile.entries(profile.read_text()) if e["id"] == name)


def version_of(profile: Path, name: str) -> Path:
    return Path(os.path.abspath(me3_profile.resolve(profile, link(profile, name))))


def undo_it(out: dict, kind: str, loc: Locations) -> str:
    return undo.run({"type": kind, "operation": out["operation"], "profile": out["profile"]}, lambda s: None, loc=loc)


def test_share_makes_a_read_only_version_and_links_it_relatively(world):
    loc, home, root, lib, a, b, c = world
    out = shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    assert out["shared"] == ["grass"] and out["reused"] == []
    path = link(a, "grass")
    assert path.startswith("../../library/grass/") and len(path.split("/")[-1]) == shared_mods.ID_LENGTH
    version = version_of(a, "grass")
    assert (version / "sub" / "g2.dcx").read_bytes() == b"grass2"
    assert not (root / "a" / "packages" / "grass").exists()  # the Separate copy went (to the bin)
    assert (root / "a" / "packages" / "sky" / "s.dcx").is_file()  # the other mod is untouched
    rec = shared_mods.read_mod(lib, "grass")
    assert (
        rec
        and [v.id for v in rec.versions] == [version.name]
        and rec.versions[0].size == len(b"grass") + len(b"grass2")
    )
    assert rec.versions[0].installed
    if os.name == "nt" or os.geteuid() != 0:
        with pytest.raises(PermissionError):
            (version / "g.dcx").write_bytes(b"changed")
        assert not (version / "g.dcx").stat().st_mode & stat.S_IWUSR
    assert tree(home)  # the other profiles are untouched
    assert (root / "b" / "packages" / "grass" / "g.dcx").read_bytes() == b"grass"


def test_an_identical_package_reuses_the_version_and_usage_is_derived(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    out = shared_mods.share(b, [index_of(b, "grass")], loc=loc)
    assert out["reused"] == ["grass"]
    assert version_of(a, "grass") == version_of(b, "grass")
    rec = shared_mods.read_mod(lib, "grass")
    assert rec and len(rec.versions) == 1
    seen = shared_mods.usage(root, lib)
    assert {u.profile.stem for u in seen.of("grass", version_of(a, "grass").name)} == {"a", "b"}
    assert not seen.unreadable


def test_share_then_undo_is_byte_exact_even_when_the_bin_is_emptied(world, tmp_path):
    loc, home, root, lib, a, b, c = world
    before = tree(home)
    out = shared_mods.share(a, [index_of(a, "grass"), index_of(a, "sky")], loc=loc)
    assert tree(home) != before
    shutil.rmtree(tmp_path / "bin")  # the bin is emptied: the copy is rebuilt from the version, hash checked
    undo_it(out, "library-share", loc)
    assert tree(home) == before
    assert not lib.exists()  # nothing of the library is left
    assert (root / "a" / "packages" / "grass" / "g.dcx").stat().st_mode & stat.S_IWUSR


def test_undo_refuses_when_the_profile_changed_since(world):
    loc, home, root, lib, a, b, c = world
    out = shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    a.write_text(a.read_text() + "\n# edited\n")
    with pytest.raises(undo.UndoError):
        undo_it(out, "library-share", loc)
    assert version_of(a, "grass").is_dir()


def test_undo_refuses_when_another_profile_uses_the_version_now(world):
    loc, home, root, lib, a, b, c = world
    out = shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    shared_mods.use_in("grass", version_of(a, "grass").name, {c: False}, loc=loc)
    with pytest.raises(undo.UndoError):
        undo_it(out, "library-share", loc)


def test_use_in_adds_the_entry_and_replaces_a_separate_copy_only_when_asked(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    ver = version_of(a, "grass").name
    # c has no grass: it gets the entry; b has a Separate copy and keeps it
    out = shared_mods.use_in("grass", ver, {c: False, b: False}, loc=loc)
    assert out["linked"] == ["c"] and out["skipped"] == ["b"]
    assert version_of(c, "grass").name == ver
    assert (root / "b" / "packages" / "grass" / "g.dcx").is_file() and link(b, "grass") == "packages/grass"
    before = tree(home)
    out = shared_mods.use_in("grass", ver, {b: True}, loc=loc)
    assert out["linked"] == ["b"] and version_of(b, "grass").name == ver
    assert not (root / "b" / "packages" / "grass").exists()
    undo_it(out, "library-use", loc)
    assert tree(home) == before


def test_a_differing_copy_replaced_by_choice_comes_back_from_the_bin(world, tmp_path):
    loc, home, root, lib, a, b, c = world
    (root / "b" / "packages" / "grass" / "g.dcx").write_bytes(b"my edit")
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    ver = version_of(a, "grass").name
    before = tree(home)
    out = shared_mods.use_in("grass", ver, {b: True}, loc=loc)
    undo_it(out, "library-use", loc)
    assert tree(home) == before and (root / "b" / "packages" / "grass" / "g.dcx").read_bytes() == b"my edit"
    out = shared_mods.use_in("grass", ver, {b: True}, loc=loc)
    shutil.rmtree(tmp_path / "bin")  # the edited copy is gone for good: undoing would lose it, so it is refused
    with pytest.raises(undo.UndoError):
        undo_it(out, "library-use", loc)


def test_separate_copies_the_version_back_writable_and_undoes(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    version = version_of(a, "grass")
    before = tree(home)
    out = shared_mods.separate(a, [index_of(a, "grass")], loc=loc)
    assert link(a, "grass") == "packages/grass"
    copy = root / "a" / "packages" / "grass"
    assert (copy / "sub" / "g2.dcx").read_bytes() == b"grass2" and (copy / "g.dcx").stat().st_mode & stat.S_IWUSR
    (copy / "g.dcx").write_bytes(b"edited")  # it is the player's again
    assert (version / "g.dcx").read_bytes() == b"grass"  # the library is unchanged
    (copy / "g.dcx").write_bytes(b"grass")
    undo_it(out, "library-separate", loc)
    assert tree(home) == before and not copy.exists()


def test_separate_refuses_when_the_folder_is_taken(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    (root / "a" / "packages" / "Grass").mkdir(parents=True)
    before = tree(home)
    with pytest.raises(shared_mods.LibraryError):
        shared_mods.separate(a, [index_of(a, "grass")], loc=loc)
    assert tree(home) == before


def newer(tmp_path: Path) -> Path:
    src = tmp_path / "download" / "grass"
    (src / "sub").mkdir(parents=True)
    (src / "g.dcx").write_bytes(b"grass v2")
    (src / "sub" / "g2.dcx").write_bytes(b"grass2")
    return src


def test_update_here_and_everywhere_and_remove_unused(world, tmp_path):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    shared_mods.share(b, [index_of(b, "grass")], loc=loc)
    old = version_of(a, "grass").name
    src = newer(tmp_path)
    before = tree(home)
    out = shared_mods.update(a, index_of(a, "grass"), src, everywhere=False, loc=loc, label="v2")
    new = version_of(a, "grass").name
    assert new != old and version_of(b, "grass").name == old and out["profiles"] == ["a"]
    rec = shared_mods.read_mod(lib, "grass")
    assert rec and [v.label for v in rec.versions] == ["", "v2"]
    undo_it(out, "library-update", loc)
    assert tree(home) == before
    out = shared_mods.update(a, index_of(a, "grass"), src, everywhere=True, loc=loc)
    assert version_of(a, "grass").name == version_of(b, "grass").name == new
    assert sorted(out["profiles"]) == ["a", "b"]
    again = shared_mods.update(b, index_of(b, "grass"), src, everywhere=False, loc=loc)
    assert again["reused"] is True
    # the old version is used by nobody now: it is listed with its size, and removed
    found, why = shared_mods.unused(loc)
    assert why is None and [(m.id, v.id) for m, v in found] == [("grass", old)]
    assert found[0][1].size == len(b"grass") + len(b"grass2")
    done = shared_mods.remove_unused(loc=loc)
    assert done["removed"] == 1 and done["size"] == found[0][1].size and done["undoable"]
    assert not (lib / "grass" / old).exists() and (lib / "grass" / new).is_dir()
    with pytest.raises(shared_mods.LibraryError):
        shared_mods.remove_unused(loc=loc)  # nothing left to remove
    undo_it(done, "library-clean", loc)
    assert (lib / "grass" / old / "g.dcx").read_bytes() == b"grass"
    rec = shared_mods.read_mod(lib, "grass")
    assert rec and {v.id for v in rec.versions} == {old, new}


def test_remove_unused_never_removes_a_version_a_profile_uses_or_cannot_be_ruled_out(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    found, why = shared_mods.unused(loc)
    assert found == [] and why is None
    (root / "c" / "c.me3").write_bytes(b"\xff\xfe not text")  # a profile nobody can read
    a.write_text(a.read_text().replace("../../library/grass/", "../../library/grass/ "))  # no longer parsed as a link
    found, why = shared_mods.unused(loc)
    assert why and "c.me3" in why
    with pytest.raises(shared_mods.LibraryError):
        shared_mods.remove_unused(loc=loc)


def test_a_mention_the_parser_missed_still_counts_as_use(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    ver = version_of(a, "grass").name
    other = root / "c" / "c.me3"
    other.write_text(other.read_text() + f"\n# [[packages]] path = '../../library/grass/{ver}'\n")
    found, _ = shared_mods.unused(loc)
    assert found == []


def test_a_profile_rename_and_a_copy_keep_the_links_working(world):
    loc, home, root, lib, a, b, c = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    ver = version_of(a, "grass")
    out = profile_rename.apply(profile_rename.preview(a, "Renamed", loc=loc), loc=loc)
    new = Path(out["profile"])
    assert link(new, "grass") == link_text(ver) and version_of(new, "grass").is_dir()
    copy = Path(profile_rename.duplicate(new, loc=loc)["profile"])
    assert version_of(copy, "grass") == ver and ver.is_dir()
    seen = shared_mods.usage(root, lib)
    assert {u.profile.stem for u in seen.of("grass", ver.name)} == {"Renamed", copy.stem}


def link_text(version: Path) -> str:
    return f"../../library/{version.parent.name}/{version.name}"


def test_a_package_that_is_not_in_the_profiles_own_folder_cannot_be_shared(world, tmp_path):
    loc, home, root, lib, a, b, c = world
    far = tmp_path / "elsewhere" / "far"
    far.mkdir(parents=True)
    (far / "f.dcx").write_bytes(b"far")
    c.write_text(c.read_text() + f"\n[[packages]]\nid = 'far'\npath = '{far.as_posix()}'\n")
    before = tree(home)
    with pytest.raises(shared_mods.LibraryError):
        shared_mods.share(c, [index_of(c, "far")], loc=loc)
    assert tree(home) == before and not lib.exists()


def test_natives_are_never_shared(world):
    loc, home, root, lib, a, b, c = world
    (root / "a" / "natives" / "n").mkdir(parents=True)
    (root / "a" / "natives" / "n" / "n.dll").write_bytes(b"dll")
    a.write_text(a.read_text() + "\n[[natives]]\npath = 'natives/n/n.dll'\n")
    n = next(e["index"] for e in me3_profile.entries(a.read_text()) if e["kind"] == "native")
    with pytest.raises(shared_mods.LibraryError):
        shared_mods.share(a, [n], loc=loc)


def test_nothing_is_changed_while_the_game_runs_or_the_source_changes(world, monkeypatch):
    loc, home, root, lib, a, b, c = world
    before = tree(home)
    with monkeypatch.context() as m:
        m.setattr(Locations, "game_running", lambda self: True)
        with pytest.raises(shared_mods.LibraryError):
            shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    assert tree(home) == before and not lib.exists()
    real = shared_mods._Job.changed

    def edit_then_check(self):
        (root / "a" / "packages" / "grass" / "g.dcx").write_bytes(b"edited meanwhile")
        return real(self)

    with monkeypatch.context() as m:
        m.setattr(shared_mods._Job, "changed", edit_then_check)
        with pytest.raises(shared_mods.LibraryError):
            shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    (root / "a" / "packages" / "grass" / "g.dcx").write_bytes(b"grass")
    assert tree(home) == before and not lib.exists()


def test_a_copy_that_does_not_match_is_never_committed(world, monkeypatch):
    loc, home, root, lib, a, b, c = world
    before = tree(home)
    real = shutil.copytree

    def bad(src, dst, *args, **kw):
        out = real(src, dst, *args, **kw)
        for f in Path(dst).rglob("*.dcx"):
            f.write_bytes(b"damaged")
        return out

    monkeypatch.setattr(shutil, "copytree", bad)
    with pytest.raises(shared_mods.LibraryError):
        shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    assert tree(home) == before and not lib.exists()


@pytest.mark.parametrize("dies_at", [1, 2])
def test_a_crash_during_the_commit_is_undone_by_the_next_start(world, monkeypatch, dies_at):
    loc, home, root, lib, a, b, c = world
    before = tree(home)
    real, calls = B._move, {"n": 0}

    def dying(src, dst):
        calls["n"] += 1
        if calls["n"] == dies_at:
            raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B, "_move", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    assert operations.problem(a)  # Play is blocked until it is recovered
    assert operations.recover(a)
    assert tree(home) == before and not lib.exists()
    assert operations.problem(a) is None
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)  # and the library works afterwards


def test_a_crash_before_the_commit_leaves_only_a_stage_that_the_next_start_clears(world, monkeypatch):
    loc, home, root, lib, a, b, c = world
    before = tree(home)
    with monkeypatch.context() as m:  # the process dies: nothing after the crash runs, not even the clean-up
        m.setattr(B.Operation, "commit", lambda self, *args, **kw: (_ for _ in ()).throw(Crash()))
        m.setattr(B.Operation, "discard", lambda self: None)
        m.setattr(shared_mods, "_delete", lambda p: None)
        m.setattr(shared_mods, "prune", lambda p: None)
        with pytest.raises(Crash):
            shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    assert list(lib.glob("*/.stage-*"))
    assert operations.recover(a)
    assert tree(home) == before and not lib.exists()


def test_the_activity_undo_is_offered_until_it_is_used(world):
    loc, home, root, lib, a, b, c = world
    out = shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    record = {"type": "library-share", "operation": out["operation"], "profile": out["profile"]}
    assert undo.available(record) and undo.label(record) == "Undo share"
    undo.run(record, lambda s: None, loc=loc)
    assert not undo.available(record)


def test_a_mixed_case_folder_is_one_lower_case_mod_in_the_library(world):
    loc, home, root, lib, a, b, c = world
    (root / "c" / "packages" / "Fog").rename(root / "c" / "packages" / "Fog2")
    (root / "c" / "packages" / "Fog2").rename(root / "c" / "packages" / "Fog")
    c.write_text(c.read_text().replace("packages/fog", "packages/Fog"))
    shared_mods.share(c, [index_of(c, "fog")], loc=loc)
    assert [d.name for d in lib.iterdir() if d.is_dir()] == ["fog"]
    rec = shared_mods.read_mod(lib, "fog")
    assert rec and rec.name == "Fog"
    shared_mods.separate(c, [index_of(c, "fog")], loc=loc)
    assert (root / "c" / "packages" / "Fog" / "f.dcx").read_bytes() == b"fog"


def test_listings_find_identical_copies_and_say_who_uses_what(world, tmp_path):
    loc, home, root, lib, a, b, c = world
    twins = shared_mods.duplicates(loc)
    assert [(t.name, len(t.copies), t.wasted) for t in twins] == [("grass", 2, len(b"grass") + len(b"grass2"))]
    assert shared_mods.duplicate_total(twins) == twins[0].wasted
    found = shared_mods.identical_elsewhere(loc, root / "a" / "packages" / "grass", c)
    assert sorted(x.profile.stem for x in found) == ["a", "b"]
    assert shared_mods.identical_elsewhere(loc, root / "a" / "packages" / "sky", a) == []
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    shared_mods.share(b, [index_of(b, "grass")], loc=loc)
    assert shared_mods.duplicates(loc) == []
    info = shared_mods.listing(loc)
    assert [(m.mod.id, m.versions[0].used_by, m.versions[0].unused) for m in info] == [("grass", ["a", "b"], False)]
    assert shared_mods.shared_count(loc, a, index_of(a, "grass")) == 2
    assert shared_mods.shared_count(loc, a, index_of(a, "sky")) == 0


def download(tmp_path: Path, folder: str, data: bytes) -> Path:
    src = tmp_path / "dl" / folder
    (src / "parts").mkdir(parents=True, exist_ok=True)
    (src / "parts" / "p.dcx").write_bytes(data)
    return src


def test_install_hook_updates_a_shared_mod_here_or_everywhere(world, tmp_path):
    from roundtable_souls.services import mods as mod_service
    from roundtable_souls.services import profile_mods

    loc, home, root, lib, a, b, c = world
    for p in (a, b):
        (root / p.stem / "packages" / "grass" / "parts").mkdir(parents=True)
        (root / p.stem / "packages" / "grass" / "parts" / "p.dcx").write_bytes(b"v1")
        shutil.rmtree(root / p.stem / "packages" / "grass" / "sub", ignore_errors=True)
        (root / p.stem / "packages" / "grass" / "g.dcx").unlink(missing_ok=True)
        shared_mods.share(p, [index_of(p, "grass")], loc=loc)
    old = version_of(a, "grass").name
    plan = mod_service.plan_mod_install(a, download(tmp_path, "grass", b"v2"), loc=loc)
    assert plan["library"]["shared"]["profiles"] == 2 and not plan["id_taken"]
    out = profile_mods.install_and_record(a, {**plan, "library_choice": "here"}, loc=loc)
    assert out["update"] and version_of(a, "grass").name != old and version_of(b, "grass").name == old
    plan = mod_service.plan_mod_install(b, download(tmp_path, "grass", b"v2"), loc=loc)
    profile_mods.install_and_record(b, {**plan, "library_choice": "everywhere"}, loc=loc)
    assert version_of(a, "grass") == version_of(b, "grass")


def test_install_hook_offers_to_share_identical_copies_and_shares_them(world, tmp_path):
    from roundtable_souls.services import mods as mod_service
    from roundtable_souls.services import profile_mods

    loc, home, root, lib, a, b, c = world
    for p in (a, b):
        shutil.rmtree(root / p.stem / "packages" / "grass")
        (root / p.stem / "packages" / "grass" / "parts").mkdir(parents=True)
        (root / p.stem / "packages" / "grass" / "parts" / "p.dcx").write_bytes(b"same")
    plan = mod_service.plan_mod_install(c, download(tmp_path, "grass", b"same"), loc=loc)
    assert plan["library"]["identical"] == ["a", "b"]
    kept = profile_mods.install_and_record(c, dict(plan), loc=loc)
    assert kept["update"] is False and link(c, "grass") == "packages/grass" and not lib.exists()
    shutil.rmtree(root / "c" / "packages" / "grass")
    c.write_text(c.read_text().replace("\n[[packages]]\nid = 'grass'\npath = 'packages/grass'\n", ""))
    plan = mod_service.plan_mod_install(c, download(tmp_path, "grass", b"same"), loc=loc)
    profile_mods.install_and_record(c, {**plan, "library_choice": "share"}, loc=loc)
    assert version_of(a, "grass") == version_of(b, "grass") == version_of(c, "grass")
    assert shared_mods.duplicates(loc) == []


def test_duplicate_can_share_with_the_original_and_an_export_names_shared_mods_by_name(world, tmp_path):
    from roundtable_souls.services import profile_rename as rename_service
    from roundtable_souls.services import profile_transfer

    loc, home, root, lib, a, b, c = world
    out = rename_service.duplicate(a, loc=loc, share=True)
    copy = Path(out["profile"])
    assert version_of(a, "grass") == version_of(copy, "grass") and not (copy.parent / "packages" / "grass").exists()
    assert (copy.parent / "packages").exists() is False or not list((copy.parent / "packages").glob("grass"))
    names = {it.folder for it in profile_transfer.items(copy, full=True)}
    assert {"grass", "sky"} <= names and not any(len(n) == shared_mods.ID_LENGTH for n in names)


def recorded(monkeypatch) -> dict:
    """What a job leaves as its undo record (run_logging.set_undo)."""
    from roundtable_souls.platform import logging as run_logging

    got: dict = {}
    monkeypatch.setattr(run_logging, "set_undo", lambda data: got.update(data=data))
    return got


def test_share_through_the_install_prompt_leaves_one_undo_for_everything(world, tmp_path, monkeypatch):
    from roundtable_souls.services import mods as mod_service
    from roundtable_souls.services import profile_mods

    loc, home, root, lib, a, b, c = world
    for p in (a, b):
        shutil.rmtree(root / p.stem / "packages" / "grass")
        (root / p.stem / "packages" / "grass" / "parts").mkdir(parents=True)
        (root / p.stem / "packages" / "grass" / "parts" / "p.dcx").write_bytes(b"same")
    before = tree(home)
    got = recorded(monkeypatch)
    plan = mod_service.plan_mod_install(c, download(tmp_path, "grass", b"same"), loc=loc)
    profile_mods.install_and_record(c, {**plan, "library_choice": "share"}, loc=loc)
    rec = got["data"]
    assert rec["type"] == "multi" and [u["type"] for u in rec["undos"]] == ["library-use", "library-share", "install"]
    assert undo.available(rec)
    undo.run(rec, lambda s: None, loc=loc)
    assert tree(home) == before and not lib.exists()
    assert not undo.available(rec)


def test_duplicate_with_share_leaves_one_undo_for_the_sharing_and_the_copy(world, monkeypatch):
    from roundtable_souls.services import profile_rename as rename_service

    loc, home, root, lib, a, b, c = world
    before = tree(home)
    got = recorded(monkeypatch)
    rename_service.duplicate(a, loc=loc, share=True)
    rec = got["data"]
    assert rec["type"] == "multi" and [u["type"] for u in rec["undos"]] == ["profile-duplicate", "library-share"]
    undo.run(rec, lambda s: None, loc=loc)
    assert tree(home) == before and not lib.exists()
