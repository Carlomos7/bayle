"""Install, update and undo as one recoverable operation (mods.operations): staged first, applied under one journal,
undone as a whole when interrupted, taken back as a set. Temporary folders only."""

import os
from pathlib import Path

import pytest

from roundtable_souls.merging import build as B
from roundtable_souls.mods import install, operations
from support import er

PROFILE = (
    'profileVersion = "v1"\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n\r\n'
    "[[natives]]\r\npath = 'natives/SeamlessCoop/ersc.dll'\r\nload_early = true\r\n\r\n"
    "[[packages]]\r\nid = \"flora\"\r\npath = 'mod/flora'\r\n"
)


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def files(folder):
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and not p.relative_to(folder).as_posix().startswith(".roundtable") and p.suffix != ".bak"
    }


@pytest.fixture
def profile(tmp_path):
    root = tmp_path / "profiles"
    (root / "mod" / "flora" / "parts").mkdir(parents=True)
    (root / "mod" / "flora" / "parts" / "a.partsbnd.dcx").write_bytes(b"flora")
    seamless = root / "natives" / "SeamlessCoop"
    seamless.mkdir(parents=True)
    (seamless / "ersc.dll").write_bytes(b"dll")
    (seamless / "ersc_settings.ini").write_text("cooppassword = x\n")
    p = root / "my.me3"
    p.write_bytes(PROFILE.encode())
    return p


def source(tmp_path, version: str, extra: dict | None = None):
    src = tmp_path / f"src-{version}" / "Grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.partsbnd.dcx").write_bytes(f"grass {version}".encode())
    (src / "grass.ini").write_bytes(f"version = {version}\n".encode())
    for rel, data in (extra or {}).items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    return src


def do_install(profile, src, **kw):
    plan = install.plan_install(profile, src, name="grass", loc=er())
    return install.install(profile, plan, overwrite=bool(plan.get("exists")), **kw, loc=er())


def test_install_is_staged_then_applied_with_a_record(profile, tmp_path):
    out = do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    assert files(grass) == {"parts/grass.partsbnd.dcx": b"grass 1", "grass.ini": b"version = 1\n"}
    assert "path = 'mod/grass'" in profile.read_text()
    assert operations.pending(profile) == [] and operations.problem(profile) is None
    [kept] = operations.kept_versions(profile)
    assert kept["kind"] == "install" and kept["dir"] == out["operation"]
    assert not [p for p in grass.parent.iterdir() if ".staging" in p.name]


def test_failed_preparation_leaves_the_previous_install_untouched(profile, tmp_path, monkeypatch):
    do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    before = files(profile.parent)
    with monkeypatch.context() as m:
        m.setattr(install.shutil, "copytree", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        with pytest.raises(OSError, match="disk full"):
            do_install(profile, source(tmp_path, "2"))
    assert files(profile.parent) == before
    assert files(grass)["grass.ini"] == b"version = 1\n"
    assert operations.pending(profile) == []


def test_failed_rebuild_undoes_the_whole_install(profile, tmp_path):
    before = files(profile.parent)
    seen = {}

    def rebuild():
        seen["live"] = (profile.parent / "mod" / "grass").is_dir() and "grass" in profile.read_text()
        raise RuntimeError("the rebuild failed")

    with pytest.raises(RuntimeError, match="rebuild failed"):
        do_install(profile, source(tmp_path, "1"), then=rebuild)
    assert seen["live"]  # the rebuild saw the new state
    assert files(profile.parent) == before  # and it is gone again, all of it
    assert operations.kept_versions(profile) == []


@pytest.mark.parametrize(("update", "crash_at"), [(False, 1), (False, 2), (True, 1), (True, 2)])
def test_an_interrupted_install_is_undone_on_the_next_start(profile, tmp_path, monkeypatch, update, crash_at):
    """Dies at each rename: the new folder moved in and the profile replaced (an install), the installed folder moved
    aside and the new one moved in (an update, whose entry is there already). The next start finds the journal and
    puts the state before back, all of it."""
    if update:
        do_install(profile, source(tmp_path, "1"))
    before = files(profile.parent)
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        if "journal" not in str(dst) and Path(dst).is_relative_to(profile.parent):  # the profile's folder only
            n["i"] += 1
            if n["i"] == crash_at:
                raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            do_install(profile, source(tmp_path, "2"))
    assert "did not finish" in (operations.problem(profile) or "")
    said = operations.recover(profile)
    assert said and "undone" in said[0]
    assert files(profile.parent) == before and operations.problem(profile) is None


@pytest.mark.parametrize("where", [".roundtable-ops", ".roundtable/ops"])
def test_an_interrupted_install_is_undone_wherever_its_journal_is(profile, tmp_path, monkeypatch, where):
    """Safety (players' files): a journal left in .roundtable-ops beside the profile (launchers before 3.23) blocks
    Play and is undone on the next start, as one in the profile's .roundtable/ops is."""

    def before_3_23(prof, what):
        op = B.Operation(Path(prof).parent, what)
        op.note(profile=str(Path(prof)))
        return op

    before = files(profile.parent)
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        if "journal" not in str(dst) and Path(dst).is_relative_to(profile.parent):
            n["i"] += 1
            if n["i"] == 2:
                raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        if where == ".roundtable-ops":
            m.setattr(operations, "start", before_3_23)
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            do_install(profile, source(tmp_path, "1"))
    assert [d for d in (profile.parent / where).iterdir() if d.is_dir()]
    assert "did not finish" in (operations.problem(profile) or "")
    said = operations.recover(profile)
    assert said and "undone" in said[0]
    assert files(profile.parent) == before and operations.problem(profile) is None


def test_update_keeps_the_previous_version_and_rolls_back_as_a_set(profile, tmp_path):
    do_install(profile, source(tmp_path, "1"))
    v1_profile = profile.read_bytes()
    out = do_install(profile, source(tmp_path, "2", {"new.txt": b"n"}))
    grass = profile.parent / "mod" / "grass"
    assert out["update"] and files(grass)["grass.ini"] == b"version = 2\n"
    assert [k["kind"] for k in operations.kept_versions(profile)] == ["update"]  # the install's record let go
    said = operations.rollback(Path(out["operation"]))
    assert "rolled grass back" in said
    assert files(grass) == {"parts/grass.partsbnd.dcx": b"grass 1", "grass.ini": b"version = 1\n"}
    assert profile.read_bytes() == v1_profile
    [rb] = operations.kept_versions(profile)
    assert rb["kind"] == "rollback"  # the version rolled back is kept aside until kept
    aside = list((profile.parent / ".roundtable" / "previous").glob("grass-*"))  # in the profile's .roundtable
    assert len(aside) == 1 and files(aside[0])["new.txt"] == b"n"
    operations.keep(Path(rb["dir"]))
    assert not list((profile.parent / ".roundtable" / "previous").glob("grass-*"))
    assert not any(p.name.startswith(".grass.") for p in grass.parent.iterdir())


def test_user_edits_survive_an_update(profile, tmp_path):
    do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    (grass / "grass.ini").write_text("version = 1\nmine = yes\n")
    os.utime(grass / "grass.ini", ns=(1, 1))
    (grass / "notes.txt").write_text("my notes")
    out = do_install(profile, source(tmp_path, "2"))
    assert out["kept"] == ["grass.ini", "notes.txt"]
    assert (grass / "grass.ini").read_text() == "version = 1\nmine = yes\n"
    assert (grass / "grass.ini.new").read_text() == "version = 2\n"  # the new version's copy, beside it
    assert (grass / "notes.txt").read_text() == "my notes"
    assert (grass / "parts" / "grass.partsbnd.dcx").read_bytes() == b"grass 2"


def test_fresh_install_undo_restores_the_exact_profile_and_only_unchanged_files(profile, tmp_path):
    before = profile.read_bytes()
    out = do_install(profile, source(tmp_path, "1"))
    grass = profile.parent / "mod" / "grass"
    (grass / "grass.ini").write_text("edited")
    said = operations.undo_install(Path(out["operation"]))
    assert profile.read_bytes() == before  # byte for byte
    assert files(grass) == {"grass.ini": b"edited"}  # changed since: left, and said
    assert "grass.ini" in said
    assert operations.kept_versions(profile) == []


def test_fresh_install_undo_after_a_profile_edit_takes_only_its_entries(profile, tmp_path):
    out = do_install(profile, source(tmp_path, "1"))
    edited = profile.read_text().replace('id = "flora"', 'id = "flora"\r\n# my note')
    profile.write_bytes(edited.encode())
    said = operations.undo_install(Path(out["operation"]))
    text = profile.read_text()
    assert "# my note" in text and "mod/grass" not in text and "mod/flora" in text
    assert "changed since" in said
    assert not (profile.parent / "mod" / "grass").exists()


def test_seamless_is_never_taken_out_by_an_undo(profile, tmp_path):
    """Seamless installed with a mod the user then undoes: its entry and folder stay (other mods rely on it)."""
    no_coop = PROFILE.replace("[[natives]]\r\npath = 'natives/SeamlessCoop/ersc.dll'\r\nload_early = true\r\n\r\n", "")
    profile.write_bytes(no_coop.encode())
    src = tmp_path / "src" / "SeamlessCoop"
    src.mkdir(parents=True)
    (src / "ersc.dll").write_bytes(b"dll 2")
    plan = install.plan_install(profile, src, loc=er())
    out = install.install(profile, plan, overwrite=bool(plan.get("exists")), loc=er())
    said = operations.undo_install(Path(out["operation"]))
    assert "ersc.dll" in profile.read_text()
    assert (profile.parent / "natives" / "SeamlessCoop" / "ersc.dll").is_file()
    assert "Seamless Co-op" in said


def test_an_unfinished_operation_blocks_play(profile, tmp_path):
    from roundtable_souls.game import catalog
    from roundtable_souls.game.locate import Locations
    from roundtable_souls.services import play

    op = operations.start(profile, "install of grass")  # prepared, never applied: as a crash leaves it
    s = play.LaunchProfile("me3", str(profile), loc=Locations(catalog.ELDEN_RING))
    assert any("did not finish" in p for p in s.problems())
    operations.recover(profile)
    assert not any("did not finish" in p for p in s.problems())
    assert not op.dir.exists()


def test_activity_takes_an_install_and_an_update_back(profile, tmp_path):
    from roundtable_souls.mods import undo

    before = profile.read_bytes()
    first = do_install(profile, source(tmp_path, "1"))
    rec = {"type": "install", "profile": str(profile), "name": "grass", "operation": first["operation"]}
    assert undo.available(rec) and undo.label(rec) == "Undo install"
    second = do_install(profile, source(tmp_path, "2"))
    assert not undo.available(rec)  # the update let the install's record go: only the newest can be taken back
    upd = {"type": "update", "profile": str(profile), "name": "grass", "operation": second["operation"]}
    assert undo.available(upd) and undo.label(upd) == "Roll back"
    said = undo.run(upd, lambda s: None, loc=er())
    assert "rolled grass back" in said and not undo.available(upd)
    grass = profile.parent / "mod" / "grass"
    assert files(grass)["grass.ini"] == b"version = 1\n"
    assert profile.read_bytes() != before  # rolled back to version 1, not uninstalled


def test_an_install_with_a_rebuild_hands_the_rebuild_the_games_locations(profile, tmp_path, monkeypatch):
    """The rebuild inside the operation is the game's: the service passes on the Locations it is given."""
    from roundtable_souls.mods import rebuild
    from roundtable_souls.services import mods as service

    seen = []
    monkeypatch.setattr(rebuild, "rebuild", lambda prof, log, combine=None, *, loc: seen.append(loc))
    loc = er()
    plan = install.plan_install(profile, source(tmp_path, "1"), name="grass", loc=loc)
    service.install_mod(profile, plan, rebuild=True, loc=loc)
    assert seen == [loc]


def test_rolling_back_an_update_that_rebuilt_rebuilds_for_the_same_game(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import rebuild, undo

    do_install(profile, source(tmp_path, "1"))
    second = do_install(profile, source(tmp_path, "2"))
    seen = []
    monkeypatch.setattr(rebuild, "rebuild", lambda prof, log, combine=None, *, loc: seen.append(loc))
    loc = er()
    rec = {"type": "update", "profile": str(profile), "name": "grass", "operation": second["operation"]}
    undo.run({**rec, "rebuild": True}, lambda s: None, loc=loc)
    assert seen == [loc]


def test_removal_interrupted_before_the_folder_went_is_undone(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import remove

    do_install(profile, source(tmp_path, "1"))
    before = files(profile.parent)
    index = next(e["index"] for e in install.entries(profile) if e["name"] == "grass")
    with monkeypatch.context() as m:
        real = B.os.replace

        def dying(src, dst):
            if Path(src).name == "grass":
                raise Crash()  # the folder about to be taken aside
            return real(src, dst)

        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            remove.uninstall(profile, index, delete_folder=True, to_trash=False, loc=er())
    assert "mod/grass" not in profile.read_text()  # the profile was written, the folder not yet taken
    assert operations.problem(profile)
    assert operations.recover(profile) == ["an interrupted removal of grass was undone: the previous state is back"]
    assert files(profile.parent) == before


def test_removal_interrupted_after_the_folder_went_is_finished(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import remove

    do_install(profile, source(tmp_path, "1"))
    index = next(e["index"] for e in install.entries(profile) if e["name"] == "grass")
    with monkeypatch.context() as m:
        m.setattr(remove.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(Crash()))  # after the rename
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            remove.uninstall(profile, index, delete_folder=True, to_trash=False, loc=er())
    assert not (profile.parent / "mod" / "grass").exists()
    assert operations.recover(profile) == ["an interrupted removal of grass was finished"]
    assert "mod/grass" not in profile.read_text() and operations.problem(profile) is None
    assert operations.kept_versions(profile) == []  # the install's record went with the mod


def test_failed_removal_leaves_the_mod_installed(profile, tmp_path, monkeypatch):
    from roundtable_souls.mods import remove

    do_install(profile, source(tmp_path, "1"))
    before = files(profile.parent)
    index = next(e["index"] for e in install.entries(profile) if e["name"] == "grass")
    with monkeypatch.context() as m:
        real = B.os.replace

        def refused(src, dst):
            if Path(src).name == "grass":
                raise PermissionError("in use")
            return real(src, dst)

        m.setattr(B.os, "replace", refused)
        with pytest.raises(PermissionError):
            remove.uninstall(profile, index, delete_folder=True, to_trash=False, loc=er())
    assert files(profile.parent) == before and operations.problem(profile) is None


def test_looking_for_interrupted_operations_writes_nothing(profile):
    before = sorted(p.name for p in profile.parent.iterdir())
    assert operations.recover(profile) == [] and operations.problem(profile) is None
    assert sorted(p.name for p in profile.parent.iterdir()) == before


def test_importing_a_bundled_profile_renames_a_clash_keeps_the_rest_and_undo_puts_it_back(tmp_path):
    import difflib
    import tomllib

    from roundtable_souls.mods import profile_import, undo

    p = tmp_path / "prof" / "my.me3"
    (p.parent / "mod" / "flora").mkdir(parents=True)
    (p.parent / "natives" / "SeamlessCoop").mkdir(parents=True)
    (p.parent / "natives" / "SeamlessCoop" / "ersc.dll").write_bytes(b"d")
    text = PROFILE.replace('[[packages]]\r\nid = "flora"', '# keep me\r\n[[packages]]\r\nid = "flora"')
    p.write_bytes(text.encode())
    before = p.read_bytes()
    pack = tmp_path / "pack"
    (pack / "mods" / "Flora" / "parts").mkdir(parents=True)
    (pack / "mods" / "Flora" / "parts" / "a.partsbnd.dcx").write_bytes(b"a")
    (pack / "mods" / "Other" / "chr").mkdir(parents=True)
    (pack / "mods" / "Other" / "chr" / "b.anibnd.dcx").write_bytes(b"b")
    (pack / "natives" / "Cool").mkdir(parents=True)
    (pack / "natives" / "Cool" / "cool.dll").write_bytes(b"c")
    (pack / "me3.exe").write_bytes(b"never copied")
    (pack / "Pack.me3").write_text(
        'profileVersion = "v1"\n\n[[packages]]\nid = "flora"\npath = \'mods/Flora\'\n\n'
        '[[packages]]\nid = "other"\npath = \'mods/Other\'\nload_after = [{ id = "flora", optional = false }]\n\n'
        "[[natives]]\npath = 'natives/Cool/cool.dll'\nload_early = true\n\n"
        "[[natives]]\npath = 'C:/elsewhere/x.dll'\n",
        encoding="utf-8",
    )
    pre = profile_import.preview_import(pack, "Pack.me3", p, loc=er())
    assert pre.ok, pre.refusals
    assert pre.renamed == {"flora": "flora-2"} and len(pre.skipped) == 1
    out = profile_import.apply_import(pre)
    old, new = before.decode().splitlines(), p.read_bytes().decode().splitlines()
    assert [d for d in difflib.ndiff(old, new) if d[0] == "-"] == []  # every line kept (comment, CRLF)
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    pk = {x["id"]: x for x in data["packages"]}
    assert pk["flora-2"]["path"] == "mod/flora-2" and pk["flora"]["path"] == "mod/flora"
    assert pk["other"]["load_after"] == [{"id": "flora-2", "optional": False}]
    assert {"path": "natives/cool/cool.dll", "load_early": True}.items() <= data["natives"][-1].items()
    assert (p.parent / "mod" / "flora-2" / "parts" / "a.partsbnd.dcx").is_file()
    assert not any(x.name == "me3.exe" for x in p.parent.rglob("*"))
    rec = {"type": "profile-import", "profile": str(p), "name": p.name, "operation": out["operation"]}
    assert undo.available(rec) and undo.label(rec) == "Undo import"
    undo.run(rec, lambda s: None, loc=er())
    assert p.read_bytes() == before
    assert not (p.parent / "mod" / "flora-2").exists() and not (p.parent / "natives" / "cool").exists()


# ----------------------------------------------------------------------------- renaming a mod's folder and id
RENAME_PROFILE = (
    '# my notes\r\nprofileVersion = "v1"\r\n\r\n[[supports]]\r\ngame = "eldenring"\r\n\r\n'
    "[[natives]]\r\npath = 'natives/Cool/cool.dll'\r\nload_early = true\r\n\r\n"
    "# the flora\r\n[[packages]]\r\nid = \"alpha\"\r\npath = 'mod/Alpha'\r\n\r\n"
    "[[packages]]\r\npath = 'mod/beta'\r\nload_after = [{ id = \"alpha\", optional = false }]\r\n\r\n"
    '[[packages]]\r\nid = "gamma"\r\npath = \'mod/gamma\'\r\nload_before = ["alpha"]\r\n'
)


def tree(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in Path(root).rglob("*")
        if p.is_file() and ".roundtable" not in p.relative_to(root).parts and p.suffix not in (".bak", ".lock")
    }


@pytest.fixture
def world(tmp_path):
    import json

    from roundtable_souls.config import settings
    from roundtable_souls.mods import library, profile_settings

    root = tmp_path / "prof"
    for name in ("Alpha", "beta", "gamma"):
        (root / "mod" / name / "parts").mkdir(parents=True)
        (root / "mod" / name / "parts" / "a.dcx").write_bytes(name.encode())
    (root / "natives" / "Cool").mkdir(parents=True)
    (root / "natives" / "Cool" / "cool.dll").write_bytes(b"dll")
    (root / "natives" / "Cool" / "cool.ini").write_bytes(b"x = 1\n")
    p = root / "my.me3"
    p.write_bytes(RENAME_PROFILE.encode())
    library.ensure_state(library.state_of(p))
    profile_settings.path(p).write_text(
        json.dumps({"version": 1, "schema": 1, "profiles": {"my.me3": {"after_overlay": ["alpha"]}}}), encoding="utf-8"
    )
    dll = root / "natives" / "Cool" / "cool.dll"
    settings.settings_path().write_text(
        json.dumps({"native_configs": {str(dll): [str(dll.with_name("cool.ini"))]}, "theme": "light"}), encoding="utf-8"
    )
    return p


def snapshot(p):
    from roundtable_souls.config import settings
    from roundtable_souls.mods import profile_settings

    return tree(p.parent), p.read_bytes(), profile_settings.path(p).read_bytes(), settings.settings_path().read_bytes()


def entry_index(p, name):
    from roundtable_souls.formats import me3_profile

    return next(e["index"] for e in me3_profile.entries(p.read_text(encoding="utf-8")) if e["name"] == name)


def no_leftovers(p):
    assert not [
        x for x in p.parent.rglob("*") if x.name.endswith(".tmp") or ".staging" in x.name or "rename-" in x.name
    ]
    assert operations.pending(p) == []


def test_rename_then_undo_is_byte_exact(world):
    import json
    import tomllib

    from roundtable_souls.config import settings
    from roundtable_souls.mods import profile_settings, rename, undo

    p, before = world, snapshot(world)
    pre = rename.preview(p, entry_index(p, "alpha"), "flora", loc=er())
    assert pre.ok, pre.refusals
    out = rename.apply(pre, loc=er())
    data = tomllib.loads(p.read_text(encoding="utf-8"))
    pk = {x.get("id") or x["path"]: x for x in data["packages"]}
    assert pk["flora"]["path"] == "mod/flora" and not (p.parent / "mod" / "Alpha").exists()
    assert pk["mod/beta"]["load_after"] == [{"id": "flora", "optional": False}]
    assert [d["id"] if isinstance(d, dict) else d for d in pk["gamma"]["load_before"]] == ["flora"]
    assert "# my notes" in p.read_text(encoding="utf-8") and "# the flora" in p.read_text(encoding="utf-8")
    assert json.loads(profile_settings.path(p).read_text())["profiles"]["my.me3"]["after_overlay"] == ["flora"]
    assert tree(p.parent)["mod/flora/parts/a.dcx"] == b"Alpha"
    # a native: the folder only, its attached config follows
    pre = rename.preview(p, entry_index(p, "cool.dll"), "cooler", loc=er())
    assert pre.ok, pre.refusals
    out2 = rename.apply(pre, loc=er())
    dll = p.parent / "natives" / "cooler" / "cool.dll"
    assert json.loads(settings.settings_path().read_text())["native_configs"] == {
        str(dll): [str(dll.with_name("cool.ini"))]
    }
    assert "natives/cooler/cool.dll" in p.read_text(encoding="utf-8")
    for o in (out2, out):
        rec = {"type": "rename", "profile": str(p), "name": o["name"], "operation": o["operation"]}
        assert undo.available(rec)
        undo.run(rec, lambda s: None, loc=er())
    assert snapshot(p) == before
    no_leftovers(p)


def do_rename(p, name, new, **kw):
    from roundtable_souls.mods import rename

    pre = rename.preview(p, entry_index(p, name), new, loc=er())
    assert pre.ok, pre.refusals
    return rename.apply(pre, loc=er(), **kw)


@pytest.mark.parametrize("crash", [False, True])
@pytest.mark.parametrize("name", ["alpha", "cool.dll"])
@pytest.mark.parametrize("fail_at", [1, 2, 3])
def test_a_rename_that_fails_or_is_interrupted_at_any_step_leaves_the_original(
    world, tmp_path, monkeypatch, fail_at, crash, name
):
    """Safety (players' files): the profile, the two settings files and the folder move are steps; dying after
    any of them (an error, or the process itself) puts every byte back."""
    p, before = world, snapshot(world)
    real, commit = B.os.replace, B.Operation.commit
    n = {"i": 0, "armed": False}

    def dying(src, dst):
        if n["armed"] and "journal" not in str(dst) and Path(dst).is_relative_to(tmp_path):
            n["i"] += 1
            if n["i"] == fail_at:
                raise (Crash() if crash else OSError("denied"))
        return real(src, dst)

    def arming(self, *a, **k):
        n["armed"] = True
        return commit(self, *a, **k)

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B.Operation, "commit", arming)
        if crash:
            m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash if crash else Exception):
            do_rename(p, name, "flora")
    if crash:
        assert "did not finish" in (operations.problem(p) or "")
        assert operations.recover(p)
    assert snapshot(p) == before
    no_leftovers(p)


def test_discarding_a_prepared_move_never_deletes_the_folder(tmp_path):
    (tmp_path / "mine").mkdir()
    (tmp_path / "mine" / "f").write_bytes(b"x")
    op = B.Operation(tmp_path, "test")
    op.move_folder(tmp_path / "mine", tmp_path / "yours")
    op.discard()
    assert (tmp_path / "mine" / "f").read_bytes() == b"x" and not (tmp_path / "yours").exists()


def _edit_profile(p, extra):
    p.write_bytes(p.read_bytes() + extra.encode())


@pytest.mark.parametrize(
    "case",
    ["game", "folder-taken", "same-folder", "other-profile", "seamless", "unknown-key", "unsafe", "same-name"],
)
def test_a_refused_rename_changes_nothing(world, monkeypatch, case):
    import json

    from roundtable_souls.game.locate import Locations
    from roundtable_souls.mods import profile_settings, rename

    p = world
    new, name = "flora", "alpha"
    if case == "game":
        monkeypatch.setattr(Locations, "game_running", lambda self: True)
    elif case == "folder-taken":
        new = "BETA"
    elif case == "same-folder":
        _edit_profile(p, "\r\n[[packages]]\r\nid = \"twin\"\r\npath = 'mod/Alpha'\r\n")
    elif case == "other-profile":
        (p.parent / "other.me3").write_text("[[packages]]\npath = 'mod/Alpha'\n", encoding="utf-8")
    elif case == "seamless":
        (p.parent / "natives" / "Sea").mkdir()
        (p.parent / "natives" / "Sea" / "ersc.dll").write_bytes(b"d")
        _edit_profile(p, "\r\n[[natives]]\r\npath = 'natives/Sea/ersc.dll'\r\n")
        name = "ersc.dll"
    elif case == "unknown-key":
        profile_settings.path(p).write_text(
            json.dumps({"version": 1, "profiles": {"my.me3": {"mystery": {"keep": "alpha"}}}}), encoding="utf-8"
        )
    elif case == "unsafe":
        new = "bad:name"
    elif case == "same-name":
        new = "Alpha"
    before = snapshot(p)
    pre = rename.preview(p, entry_index(p, name), new, loc=er())
    assert not pre.ok and pre.refusals
    with pytest.raises(rename.ModError):
        rename.apply(pre, loc=er())
    assert snapshot(p) == before
    no_leftovers(p)


def test_a_rename_is_refused_when_the_profile_changed_since_the_preview(world):
    from roundtable_souls.mods import rename

    p = world
    pre = rename.preview(p, entry_index(p, "alpha"), "flora", loc=er())
    assert pre.ok
    _edit_profile(p, "# edited outside\r\n")
    before = snapshot(p)
    with pytest.raises(rename.ModError):
        rename.apply(pre, loc=er())
    assert snapshot(p) == before
    no_leftovers(p)


def test_undoing_a_rename_does_not_overwrite_later_changes(world, tmp_path):
    import json

    from roundtable_souls.config import settings
    from roundtable_souls.mods import undo

    p = world
    out = do_rename(p, "alpha", "flora")
    rec = {"type": "rename", "profile": str(p), "name": "alpha", "operation": out["operation"]}
    # (b) a folder appeared at the old place: nothing moves
    (p.parent / "mod" / "Alpha").mkdir()
    after = snapshot(p)
    with pytest.raises(undo.UndoError):
        undo.run(rec, lambda s: None, loc=er())
    assert snapshot(p) == after and (p.parent / "mod" / "flora").is_dir()
    (p.parent / "mod" / "Alpha").rmdir()
    # (a) the profile edited, (c) launcher_settings.json changed: the edit stays, the rename goes
    _edit_profile(p, "# edited outside\r\n")
    cur = json.loads(settings.settings_path().read_text())
    settings.settings_path().write_text(json.dumps({**cur, "theme": "dark"}), encoding="utf-8")
    notes: list[str] = []
    undo.run(rec, notes.append, loc=er())
    text = p.read_bytes().decode()
    assert text.endswith("# edited outside\r\n") and "mod/Alpha" in text and "mod/flora" not in text
    assert (p.parent / "mod" / "Alpha" / "parts" / "a.dcx").is_file() and not (p.parent / "mod" / "flora").exists()
    assert json.loads(settings.settings_path().read_text())["theme"] == "dark"
    no_leftovers(p)


@pytest.mark.skipif(os.name != "nt", reason="a case-only rename is one folder only on Windows")
def test_a_case_only_rename_works_and_undoes(world):
    from roundtable_souls.mods import undo

    p, before = world, snapshot(world)
    out = do_rename(p, "beta", "Beta")
    assert "Beta" in os.listdir(p.parent / "mod") and "beta" not in os.listdir(p.parent / "mod")
    assert "mod/Beta" in p.read_text(encoding="utf-8")
    undo.run({"type": "rename", "profile": str(p), "name": "beta", "operation": out["operation"]}, print, loc=er())
    assert "beta" in os.listdir(p.parent / "mod") and snapshot(p) == before
    no_leftovers(p)


def test_renaming_makes_the_merged_build_stale_without_touching_its_record_and_never_the_last_mod(
    tmp_path, monkeypatch
):
    from test_mod_merge import World

    from roundtable_souls.mods import rebuild as merge
    from roundtable_souls.mods import rename

    w = World(tmp_path, monkeypatch)
    w.pack("params")
    merge.update_before_play(w.profile, lambda s: None, loc=er())
    assert merge.needs_update(w.profile, loc=er()) is None
    record = w.record
    kept = record.read_bytes()
    last = entry_index(w.profile, "last")
    pre = rename.preview(w.profile, last, "newest", loc=er())
    assert not pre.ok and any("stay last" in r for r in pre.refusals)
    do_rename(w.profile, "params", "params2")
    assert record.read_bytes() == kept
    assert merge.needs_update(w.profile, loc=er()) is not None
