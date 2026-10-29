"""Moving the Profiles folder and renaming the launcher's folders (mods.layout): they move players' files, so these
are the safety tests. Temporary folders only."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bayle.adapters.filesystem import build as B
from bayle.adapters.persistence import settings_file
from bayle.modules.mods import layout

HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the clean-up."""


def me3(*paths: str) -> bytes:
    return (HEAD + "".join(f"\n[[packages]]\npath = '{p}'\n" for p in paths)).encode()


def tree(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(Path(folder).rglob("*")) if p.is_file()}


class Loc:
    def __init__(self, root: Path):
        self.root, self.running = root, False

    def me3_profiles_dir(self) -> Path:
        return self.root

    def game_running(self) -> bool:
        return self.running


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "profiles"
    g = root / "b-eldenring"
    (g / ".shared" / "modS").mkdir(parents=True)
    (g / ".shared" / "modS" / "a.txt").write_text("shared")
    for sub, name in (("packages", "m1"), ("natives", "n1")):
        (g / "alpha" / sub / name).mkdir(parents=True)
        (g / "alpha" / sub / name / "f.bin").write_bytes(b"\0\1\2" * 1000)
    (g / "alpha" / "builds").mkdir()
    (g / "alpha" / "alpha.me3").write_bytes(
        me3(f"{g.as_posix()}/alpha/packages/m1", "natives/n1", f"{g.as_posix()}/.shared/modS", "../.shared/modS")
    )
    (root / "b-nightreign" / "beta" / "packages").mkdir(parents=True)
    (root / "b-nightreign" / "beta" / "beta.me3").write_bytes(me3("packages"))
    (tmp_path / "ops").mkdir()
    monkeypatch.setattr(layout, "ops_root", lambda: tmp_path / "ops")
    monkeypatch.setattr(layout, "_free", lambda p: 10**12)
    return SimpleNamespace(root=root, loc=Loc(root), tmp=tmp_path, g=g)


def ops_left(w) -> list[str]:
    base = w.tmp / "ops" / B.OPS
    return [p.name for p in base.glob("*")] if base.is_dir() else []


# ----------------------------------------------------------------------------- relocate
@pytest.mark.parametrize("cross", [False, True])
def test_relocate_moves_everything_and_undo_is_identical(world, monkeypatch, cross):
    if cross:
        monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    before = tree(world.root)
    new = world.tmp / "elsewhere"
    seen = []
    r = layout.relocate(world.loc, new, progress=lambda d, t: seen.append((d, t)))
    assert not (world.root / "b-eldenring").exists() and not (world.root / "b-nightreign").exists()
    assert tree(new).keys() == before.keys()
    text = (new / "b-eldenring" / "alpha" / "alpha.me3").read_text()
    assert f"{new.as_posix()}/b-eldenring/alpha/packages/m1" in text  # the absolute path follows
    assert "'natives/n1'" in text and "'../.shared/modS'" in text  # relative ones stay
    assert settings_file.load_settings().profiles_root == str(new)
    assert not list(new.glob(".rs-relocate-*"))
    if cross:
        assert seen and seen[-1][0] == seen[-1][1] > 0
    layout.undo_layout(Path(r["operation"]), world.loc)
    assert settings_file.load_settings().profiles_root is None
    assert tree(world.root) == before
    assert not (new / "b-eldenring").exists()
    assert ops_left(world) == []


def test_the_settings_move_to_another_drive_copies_without_a_progress_callback(world, monkeypatch):
    """The Settings page's move goes through settings.locations, which gave the copy loop a one-argument logger."""
    from bayle.modules.settings import locations

    monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    monkeypatch.setattr(locations.run_logging, "start_log", lambda *a, **k: None)
    monkeypatch.setattr(world.loc, "game", SimpleNamespace(key="eldenring"), raising=False)
    monkeypatch.setattr(locations, "_record", lambda out: None)
    before = tree(world.root)
    new = world.tmp / "other-drive"
    locations.relocate(world.loc, new)
    assert tree(new).keys() == before.keys() and not (world.root / "b-eldenring").exists()


def test_relocate_cancel_mid_copy_cleans_up(world, monkeypatch):
    monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    before = tree(world.root)
    new = world.tmp / "elsewhere"
    calls = []

    def cancel():
        calls.append(1)
        return len(calls) > 3

    with pytest.raises(layout.Cancelled):
        layout.relocate(world.loc, new, cancel=cancel)
    assert tree(world.root) == before
    assert not new.exists()
    assert ops_left(world) == []
    assert settings_file.load_settings().profiles_root is None


def test_relocate_crash_before_commit_recovers(world, monkeypatch):
    monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    before = tree(world.root)
    new = world.tmp / "elsewhere"
    new.mkdir()
    real_move, n = B._move, [0]

    def dying(src, dst):  # dies after the first folder is renamed into place
        n[0] += 1
        if n[0] == 2:
            raise Crash
        return real_move(src, dst)

    with monkeypatch.context() as m:
        m.setattr(B, "_move", dying)
        m.setattr(B, "_undo", lambda op: (_ for _ in ()).throw(Crash()))
        m.setattr(B.Operation, "discard", lambda self: None)
        m.setattr(layout, "_drop", lambda *a: None)
        with pytest.raises(Crash):
            layout.relocate(world.loc, new)
    assert (new / "b-eldenring").exists()  # half done
    layout.finish_pending()
    assert tree(world.root) == before
    assert list(new.iterdir()) == []
    assert ops_left(world) == []
    assert settings_file.load_settings().profiles_root is None


def test_relocate_crash_after_commit_is_finished(world, monkeypatch):
    monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    new = world.tmp / "elsewhere"
    with monkeypatch.context() as m:
        m.setattr(layout.shutil, "rmtree", lambda *a, **k: (_ for _ in ()).throw(Crash()))
        with pytest.raises(Crash):
            layout.relocate(world.loc, new)
    assert (world.root / "b-eldenring").exists()  # the originals wait, the copies are in place
    layout.finish_pending()
    assert not (world.root / "b-eldenring").exists()
    assert (new / "b-eldenring" / "alpha" / "alpha.me3").is_file()
    assert settings_file.load_settings().profiles_root == str(new)


def test_relocate_refusals(world, monkeypatch):
    (world.tmp / "t" / "B-ELDENRING").mkdir(parents=True)
    for name, target in {"same": world.root, "inside": world.g / "alpha", "clash": world.tmp / "t"}.items():
        assert layout.preview_relocate(world.loc, target)["refusal"], name
        with pytest.raises(layout.LayoutError):
            layout.relocate(world.loc, target)
    new = world.tmp / "ok"
    world.loc.running = True
    with pytest.raises(layout.LayoutError, match="Close the game"):
        layout.relocate(world.loc, new)
    world.loc.running = False
    monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    monkeypatch.setattr(layout, "_free", lambda p: 1000)
    with pytest.raises(layout.LayoutError, match="free space"):
        layout.relocate(world.loc, new)
    monkeypatch.setattr(layout, "_free", lambda p: 10**12)
    op = B.Operation(world.tmp / "ops", "something unfinished")
    with pytest.raises(layout.LayoutError, match="not finished"):
        layout.relocate(world.loc, new)
    op.discard()
    assert (world.root / "b-eldenring").exists() and not new.exists()


def test_preview_warnings(world, monkeypatch):
    p = layout.preview_relocate(world.loc, world.tmp / "OneDrive" / "Profiles")
    assert p["games"] == 2 and p["profiles"] == 2 and p["files"] >= 5 and p["bytes"] >= 6000
    assert p["refusal"] is None and any("cloud" in w for w in p["warnings"])
    monkeypatch.setattr(layout, "_same_drive", lambda a, b: False)
    monkeypatch.setattr(layout, "_free", lambda p: 3000)
    assert any("nearly full" in w for w in layout.preview_relocate(world.loc, world.tmp / "x")["warnings"])
    monkeypatch.setattr(layout, "_free", lambda p: 10**12)
    deep = world.tmp / ("d" * 120) / ("e" * 120)
    assert any("long" in w for w in layout.preview_relocate(world.loc, deep)["warnings"])
    assert layout.preview_relocate(world.loc, world.tmp / "plain")["warnings"] == []


# ----------------------------------------------------------------------------- rename_layout
@pytest.mark.parametrize(
    "kw", [{"packages": "mods"}, {"natives": "dlls"}, {"shared": "common"}, {"pattern": "g-{game}"}]
)
def test_rename_each_name_and_undo(world, kw):
    before = tree(world.root)
    r = layout.rename_layout(world.loc, **kw)
    assert tree(world.root) != before
    if "pattern" in kw:
        assert (world.root / "g-eldenring" / "alpha" / "alpha.me3").is_file()
        assert settings_file.load_settings().game_folder_pattern == "g-{game}"
    layout.undo_layout(Path(r["operation"]), world.loc)
    assert tree(world.root) == before
    assert settings_file.load_settings().packages_folder == "packages"
    assert settings_file.load_settings().game_folder_pattern == "b-{game}"
    assert ops_left(world) == []


def test_rename_all_together_keeps_shared_links(world):
    r = layout.rename_layout(world.loc, pattern="G_{game}", packages="mods", natives="dlls", shared="common")
    g = world.root / "G_eldenring"
    assert (g / "common" / "modS" / "a.txt").read_text() == "shared"
    assert (g / "alpha" / "mods" / "m1" / "f.bin").is_file() and (g / "alpha" / "dlls" / "n1").is_dir()
    text = (g / "alpha" / "alpha.me3").read_text()
    assert f"{g.as_posix()}/alpha/mods/m1" in text and f"{g.as_posix()}/common/modS" in text
    assert "'dlls/n1'" in text and "'../common/modS'" in text
    s = settings_file.load_settings()
    assert (s.game_folder_pattern, s.packages_folder, s.natives_folder, s.shared_folder) == (
        "G_{game}",
        "mods",
        "dlls",
        "common",
    )
    assert (world.root / "G_nightreign" / "beta" / "mods").is_dir()
    layout.undo_layout(Path(r["operation"]), world.loc)
    assert (world.g / ".shared" / "modS" / "a.txt").is_file()
    assert "'../.shared/modS'" in (world.g / "alpha" / "alpha.me3").read_text()


def test_rename_swap_and_case_only(world):
    layout.rename_layout(world.loc, packages="natives", natives="packages")
    assert (world.g / "alpha" / "natives" / "m1").is_dir() and (world.g / "alpha" / "packages" / "n1").is_dir()
    layout.rename_layout(world.loc, shared=".SHARED")
    assert [p.name for p in world.g.iterdir() if p.name.lower() == ".shared"] == [".SHARED"]


def test_rename_refusals(world):
    bad = (
        {"pattern": "nogame"},
        {"packages": "a/b"},
        {"packages": "natives"},
        {"shared": "NATIVES"},
        {"packages": "builds"},
    )
    for kw in bad:
        with pytest.raises(layout.LayoutError):
            layout.rename_layout(world.loc, **kw)
    (world.g / "alpha" / "Mods").mkdir()  # taken, whatever its case
    with pytest.raises(layout.LayoutError, match="already"):
        layout.rename_layout(world.loc, packages="mods")
    (world.root / "X-eldenring").mkdir()
    with pytest.raises(layout.LayoutError, match="already"):
        layout.rename_layout(world.loc, pattern="x-{game}")
    world.loc.running = True
    with pytest.raises(layout.LayoutError, match="Close the game"):
        layout.rename_layout(world.loc, natives="dlls")
    assert layout.preview_rename(world.loc, natives="dlls")["refusal"]
    world.loc.running = False
    p = layout.preview_rename(world.loc, natives="dlls")
    assert p["refusal"] is None and p["folders"] == 1 and p["profiles"] == 2


def test_the_activity_undo_records_take_a_relocation_and_a_rename_back(world):
    from bayle.modules.mods import undo

    before = tree(world.root)
    r = layout.rename_layout(world.loc, shared="common")
    assert r["undo"]["type"] == "layout-rename" and undo.available(r["undo"])
    assert undo.label(r["undo"]) == "Undo rename"
    undo.run(r["undo"], lambda s: None, loc=world.loc)
    assert tree(world.root) == before and not undo.available(r["undo"])
    new = world.tmp / "elsewhere"
    m = layout.relocate(world.loc, new)
    assert m["undo"]["type"] == "layout-relocate" and undo.available(m["undo"])
    undo.run(m["undo"], lambda s: None, loc=world.loc)
    assert tree(world.root) == before


def test_finish_pending_also_blocks_on_a_journal_in_a_game_folder(world):
    op = B.Operation(world.g, "something unfinished")
    assert "not finished" in (layout._unfinished(world.root, [world.g]) or "")
    op.discard()
    assert layout._unfinished(world.root, [world.g]) is None
