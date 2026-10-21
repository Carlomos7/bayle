"""DLL mods live in a folder of their own: install puts them there, loose() finds the ones that are not, and
mods.dll_folders moves them (with their files) as one journaled operation with Undo. Temporary folders only."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from roundtable_souls.game.locate import Locations
from roundtable_souls.merging import build as B
from roundtable_souls.mods import dll_folders as df
from roundtable_souls.mods import install, operations, undo
from roundtable_souls.mods.profile_edit import entries
from roundtable_souls.platform import trash
from support import er

HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


def profile_with(root: Path, *paths: str, packages: tuple[str, ...] = ()) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    text = HEAD + "".join(f"\n[[packages]]\nid = 'p{n}'\npath = '{p}'\n" for n, p in enumerate(packages))
    text += "".join(f"\n[[natives]]\npath = '{p}'\n" for p in paths)
    p = root / "my.me3"
    p.write_bytes(text.encode())
    return p


def put(root: Path, rel: str, data: bytes | None = None) -> None:
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data if data is not None else rel.encode())


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and ".bayle" not in p.relative_to(root).parts and not p.name.endswith(".lock")
    }


@pytest.fixture(autouse=True)
def recycle(monkeypatch):
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})


@pytest.fixture(autouse=True)
def idle(monkeypatch):
    monkeypatch.setattr(Locations, "game_running", lambda self: False)


@pytest.fixture
def loose(tmp_path):
    """Two DLLs directly in natives/ (each with files), one in the profile folder, one in a folder of its own."""
    root = tmp_path / "p"
    p = profile_with(root, "natives/Fps.dll", "natives/Cam.dll", "Top.dll", "natives/Own/Own.dll")
    put(root, "natives/Fps.dll", b"fps")
    put(root, "natives/Fps.ini", b"[fps]")
    put(root, "natives/Fps.zh-CN.ini", b"zh")
    put(root, "natives/Fps.log", b"log")
    put(root, "natives/Cam.dll", b"cam")
    put(root, "natives/Cam.json", b"{}")
    put(root, "natives/config.ini", b"shared")  # a generic file next to several DLLs
    put(root, "natives/readme.txt", b"read me")
    put(root, "Top.dll", b"top")
    put(root, "Top/data.bin", b"data")  # a folder named after the stem
    put(root, "Top.toml", b"t")
    put(root, "natives/Own/Own.dll", b"own")
    return p


def test_install_puts_a_bare_dll_and_an_archive_dll_in_their_own_folder(tmp_path):
    p = profile_with(tmp_path / "p")
    put(tmp_path / "dl", "UnlockTheFps.dll", b"u")
    plan = install.plan_install(p, tmp_path / "dl" / "UnlockTheFps.dll", loc=er())
    assert plan["name"] == "UnlockTheFps"
    out = install.install(p, plan, loc=er())
    assert [e["path"] for e in out["entries"]] == ["natives/UnlockTheFps/UnlockTheFps.dll"]
    assert (tmp_path / "p/natives/UnlockTheFps/UnlockTheFps.dll").read_bytes() == b"u"

    z = tmp_path / "dl" / "Some Download v1.2.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("NoGlow.dll", b"g")
        f.writestr("NoGlow.ini", b"i")
        f.writestr("NoGlow.zh-CN.ini", b"z")
    plan = install.plan_install(p, z, loc=er())
    assert plan["name"] == "NoGlow"
    out = install.install(p, plan, loc=er())
    assert [e["path"] for e in out["entries"]] == ["natives/NoGlow/NoGlow.dll"]
    names = sorted(x.name for x in (tmp_path / "p/natives/NoGlow").iterdir())
    assert names == ["NoGlow.dll", "NoGlow.ini", "NoGlow.zh-CN.ini"]

    q = profile_with(tmp_path / "q")
    plan = install.plan_install(q, z, name="My Glow", loc=er())  # the user's own name wins
    out = install.install(q, plan, loc=er())
    assert [e["path"] for e in out["entries"]] == ["natives/My-Glow/NoGlow.dll"]
    assert (tmp_path / "q/natives/My-Glow/NoGlow.ini").is_file()


def test_loose_finds_dlls_whose_folder_is_not_theirs(loose, tmp_path):
    found = df.loose(loose)
    assert sorted(d.name for d in found) == ["Cam.dll", "Fps.dll", "Top.dll"]
    assert found[tmp_path / "p/natives/Fps.dll"] == [0]


def test_a_shared_folder_and_a_package_dll_are_judged_apart(tmp_path):
    root = tmp_path / "p"
    p = profile_with(root, "tools/A.dll", "tools/B.dll", "mod/pack/own.dll", packages=("mod/pack",))
    for rel in ("tools/A.dll", "tools/B.dll", "mod/pack/own.dll", "mod/pack/parts/x.dcx"):
        put(root, rel)
    assert sorted(d.name for d in df.loose(p)) == ["A.dll", "B.dll"]  # a package's own DLL belongs to the package


def test_move_gives_each_dll_a_folder_with_its_files_and_changes_nothing_else(loose, tmp_path):
    root = tmp_path / "p"
    before = tree(root)
    plan = df.preview(loose, er())
    assert plan.ok and plan.files_copied == 2  # config.ini for Fps and Cam: copied, never moved
    fps = next(m for m in plan.moves if m.name == "Fps")
    assert [f.name for f in fps.moves] == ["Fps.ini", "Fps.log", "Fps.zh-CN.ini"]
    assert [f.name for f in fps.copies] == ["config.ini"]
    out = df.move(loose, er())
    after = tree(root)
    assert after["natives/Fps/Fps.dll"] == b"fps" and after["natives/Fps/Fps.zh-CN.ini"] == b"zh"
    assert after["natives/Fps/config.ini"] == b"shared" and after["natives/Cam/config.ini"] == b"shared"
    assert after["natives/config.ini"] == b"shared" and after["natives/readme.txt"] == b"read me"
    assert after["natives/Cam/Cam.json"] == b"{}" and after["natives/Top/Top.dll"] == b"top"
    assert after["natives/Top/Top.toml"] == b"t" and after["natives/Top/Top/data.bin"] == b"data"
    assert not (root / "Top.dll").exists() and not (root / "Top").exists() and not (root / "natives/Fps.dll").exists()
    assert after["natives/Own/Own.dll"] == b"own"  # a DLL already in a folder of its own stays
    assert [e["path"] for e in entries(loose) if e["kind"] == "native"] == [
        "natives/Fps/Fps.dll",
        "natives/Cam/Cam.dll",
        "natives/Top/Top.dll",
        "natives/Own/Own.dll",
    ]
    assert out["folders"] == 3 and df.loose(loose) == {}
    assert set(before) - set(after) == {
        "natives/Fps.dll",
        "natives/Fps.ini",
        "natives/Fps.zh-CN.ini",
        "natives/Fps.log",
        "natives/Cam.dll",
        "natives/Cam.json",
        "Top.dll",
        "Top.toml",
        "Top/data.bin",
    }


def test_undo_is_byte_identical(loose, tmp_path):
    root = tmp_path / "p"
    before = tree(root)
    out = df.move(loose, er())
    rec = {"type": df.KIND, "operation": out["operation"]}
    assert undo.available(rec) and undo.label(rec) == "Undo move"
    undo.run(rec, lambda s: None, loc=er())
    assert tree(root) == before and not (root / "natives/Fps").exists() and not (root / "natives/Top").exists()
    assert not undo.available(rec)


def test_undo_refuses_when_a_new_file_changed(loose, tmp_path):
    out = df.move(loose, er())
    (tmp_path / "p/natives/Fps/Fps.ini").write_bytes(b"edited")
    with pytest.raises(undo.UndoError):
        undo.run({"type": df.KIND, "operation": out["operation"]}, lambda s: None, loc=er())
    assert (tmp_path / "p/natives/Fps/Fps.ini").read_bytes() == b"edited" and not (tmp_path / "p/Top.dll").exists()


def test_refusals_change_nothing(loose, tmp_path, monkeypatch):
    root = tmp_path / "p"
    before = tree(root)
    (root / "natives/Fps").mkdir()  # the target is taken
    plan = df.preview(loose, er())
    assert not plan.ok and any("Fps" in r and "already there" in r for r in plan.refusals)
    with pytest.raises(df.DllFolderError):
        df.move(loose, er())
    (root / "natives/Fps").rmdir()
    monkeypatch.setattr(Locations, "game_running", lambda self: True)
    assert df.GAME_OPEN in df.preview(loose, er()).refusals
    with pytest.raises(df.DllFolderError):
        df.move(loose, er())
    assert tree(root) == before


def test_a_crash_midway_is_put_back_by_recovery_and_it_can_run_again(loose, tmp_path, monkeypatch):
    root = tmp_path / "p"
    before = tree(root)
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
            df.move(loose, er())
    assert tree(root) != before
    operations.recover(loose)
    assert tree(root) == before
    assert df.move(loose, er())["folders"] == 3
