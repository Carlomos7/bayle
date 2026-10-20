"""New installs into the library (mods.install, remove, operations on a profile in rs-<game>/profiles) move and
remove players' files: these are the safety tests. Temporary folders only."""

from pathlib import Path

import pytest
from test_mod_operations import Crash
from test_overhaul_install import world  # noqa: F401  (a fixture)

from roundtable_souls.merging import build as B
from roundtable_souls.mods import install, operations, overhaul_install, remove
from support import er

NEW = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


def lib_profile(root: Path, name: str) -> Path:
    p = root / "rs-eldenring" / "profiles" / f"{name}.me3"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(NEW.encode())
    return p


@pytest.fixture
def two(tmp_path):
    return lib_profile(tmp_path, "a"), lib_profile(tmp_path, "b")


def source(tmp_path, version: str):
    src = tmp_path / f"src-{version}" / "Grass"
    (src / "parts").mkdir(parents=True, exist_ok=True)
    (src / "parts" / "g.partsbnd.dcx").write_bytes(f"grass {version}".encode())
    return src


def put(profile, src, **kw):
    plan = install.plan_install(profile, src, name="Grass Mod", loc=er())
    return plan, install.install(profile, plan, overwrite=bool(plan.get("exists")), **kw, loc=er())


def tree(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file() and ".roundtable" not in p.relative_to(folder).parts and p.suffix != ".bak"
    }


def list_in(profile, folder):
    """The other profile lists the library folder (as Adopt or a second install would)."""
    text = profile.read_text() + f"\n[[packages]]\nid = 'grass-mod'\npath = '../packages/{folder}'\n"
    profile.write_text(text)


def test_l1_library_install_lands_in_packages_and_undo_restores_the_profile(two):
    a, _b = two
    before = a.read_bytes()
    plan, out = put(a, source(a.parents[3], "1"))
    lib = a.parents[1]
    assert plan["name"] == "grass-mod" and out["dest"] == lib / "packages" / "grass-mod"
    assert tree(lib / "packages" / "grass-mod") == {"parts/g.partsbnd.dcx": b"grass 1"}
    assert "path = '../packages/grass-mod'" in a.read_text()
    assert not (lib / "profiles" / "mod").exists()
    operations.undo_install(Path(out["operation"]))
    assert a.read_bytes() == before and not (lib / "packages" / "grass-mod").exists()


def test_l2_updating_a_mod_another_profile_lists_is_refused_then_allowed_and_b_is_untouched(two, tmp_path):
    a, b = two
    put(a, source(tmp_path, "1"))
    list_in(b, "grass-mod")
    b_bytes = b.read_bytes()
    plan = install.plan_install(a, source(tmp_path, "2"), name="Grass Mod", loc=er())
    assert plan["used_by"] == ["b"]
    with pytest.raises(Exception, match="b also use"):
        install.install(a, plan, overwrite=False, loc=er())
    assert tree(a.parents[1] / "packages" / "grass-mod") == {"parts/g.partsbnd.dcx": b"grass 1"}
    out = install.install(a, plan, overwrite=True, loc=er())
    assert out["update"] and tree(out["dest"]) == {"parts/g.partsbnd.dcx": b"grass 2"}
    assert b.read_bytes() == b_bytes


def test_l3_remove_keeps_a_shared_folder_and_removes_a_lone_one(two, tmp_path):
    a, b = two
    put(a, source(tmp_path, "1"))
    list_in(b, "grass-mod")
    folder = a.parents[1] / "packages" / "grass-mod"
    out = remove.uninstall(a, 0, delete_folder=True, loc=er())
    assert not out["removed_folder"] and out["kept_for"] == ["b"]
    assert tree(folder) == {"parts/g.partsbnd.dcx": b"grass 1"} and "grass-mod" not in a.read_text()
    out = remove.uninstall(b, 0, delete_folder=True, loc=er())
    assert out["removed_folder"] and not folder.exists()


def test_l4_undo_install_keeps_a_folder_another_profile_now_lists_and_rollback_is_refused(two, tmp_path):
    a, b = two
    before = a.read_bytes()
    _plan, out = put(a, source(tmp_path, "1"))
    folder = Path(out["dest"])
    list_in(b, "grass-mod")
    operations.undo_install(Path(out["operation"]))
    assert a.read_bytes() == before and tree(folder) == {"parts/g.partsbnd.dcx": b"grass 1"}
    # a shared update cannot be rolled back
    _p, up = put(a, source(tmp_path, "2"))
    _p, up2 = put(a, source(tmp_path, "3"))
    snapshot = tree(folder)
    with pytest.raises(operations.OperationError, match="also used by b"):
        operations.rollback(Path(up2["operation"]))
    assert tree(folder) == snapshot


def test_l5_an_interrupted_library_install_is_undone_and_uses_only_known_steps(two, tmp_path, monkeypatch):
    a, _b = two
    before = tree(a.parents[1])
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        if "journal" not in str(dst) and Path(dst).is_relative_to(a.parents[1]):
            n["i"] += 1
            if n["i"] == 2:
                raise Crash()
        return real(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            put(a, source(tmp_path, "1"))
    assert "did not finish" in (operations.problem(a) or "")
    assert operations.recover(a) and tree(a.parents[1]) == before and operations.problem(a) is None
    _p, out = put(a, source(tmp_path, "1"))
    steps = {s["type"] for s in B.Operation.load(Path(out["operation"])).steps}
    assert steps <= {"folder", "file"}


def test_l6_an_overhaul_is_refused_for_a_library_profile(world):  # noqa: F811
    lib_p = lib_profile(world.base, "mine")
    lib_p.write_text(world.profile.read_text(encoding="utf-8"), encoding="utf-8")
    before = lib_p.read_bytes()
    world.profile = lib_p
    p = world.preview()
    assert not p.ok and any("into a profile in the library" in r for r in p.refusals)
    with pytest.raises(overhaul_install.OverhaulError):
        overhaul_install.install(p, loc=world.loc)
    assert lib_p.read_bytes() == before and not (lib_p.parent / "ExampleOverhaul").exists()
