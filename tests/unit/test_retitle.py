"""After the rename: launcher-made shortcuts get the new name, the old stub stays for Steam, nothing else is touched."""

from pathlib import Path

from bayle.platform import steam_shortcuts
from bayle.updates import inno, retitle


def _lnk(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{name}.lnk"
    p.write_text("lnk")
    return p


def test_renames_only_shortcuts_that_start_this_install(tmp_path):
    root = tmp_path / "root"
    start, desktop = tmp_path / "Start", tmp_path / "Desktop"
    mine, other = _lnk(start, "Roundtable Souls"), _lnk(desktop, "Roundtable Souls")
    targets = {mine: root / "Roundtable Souls.exe", other: tmp_path / "elsewhere" / "game.exe"}
    moved = retitle.rename_links([start, desktop], root, "Roundtable Souls", "Bayle", targets.get)
    assert moved == [start / "Bayle.lnk"]
    assert (start / "Bayle.lnk").is_file() and not mine.exists() and other.is_file()
    # again: nothing left to do
    assert retitle.rename_links([start, desktop], root, "Roundtable Souls", "Bayle", targets.get) == []


def test_never_overwrites_a_shortcut_with_the_new_name_and_survives_failures(tmp_path):
    root = tmp_path / "root"
    start = tmp_path / "Start"
    _lnk(start, "Roundtable Souls")
    _lnk(start, "Bayle")
    assert retitle.rename_links([start], root, "Roundtable Souls", "Bayle", lambda p: root / "x.exe") == []
    (start / "Bayle.lnk").unlink()

    def boom(a, b):
        raise OSError("locked")

    assert retitle.rename_links([start], root, "Roundtable Souls", "Bayle", lambda p: root / "x.exe", boom) == []


def test_old_stub_is_kept_or_restored_beside_the_new_one(tmp_path):
    (tmp_path / "Bayle.exe").write_bytes(b"stub")
    assert retitle.keep_previous_stub(tmp_path, "Roundtable Souls.exe", "Bayle.exe") is True
    assert (tmp_path / "Roundtable Souls.exe").read_bytes() == b"stub"
    assert retitle.keep_previous_stub(tmp_path, "Roundtable Souls.exe", "Bayle.exe") is False  # idempotent


def test_run_does_nothing_outside_an_installed_copy(monkeypatch):
    monkeypatch.setattr(retitle, "is_installed", lambda: False)
    assert retitle.run() == {}


def _vdf(path: Path, exe: str) -> None:
    entry = steam_shortcuts.Node(steam_shortcuts.MAP, "0", children=[
        steam_shortcuts.Node(steam_shortcuts.STRING, "AppName", "Elden Ring"),
        steam_shortcuts.Node(steam_shortcuts.STRING, "Exe", f'"{exe}"'),
        steam_shortcuts.Node(steam_shortcuts.STRING, "StartDir", f'"{Path(exe).parent}"'),
        steam_shortcuts.Node(steam_shortcuts.STRING, "LaunchOptions", "--play"),
    ])  # fmt: skip
    path.parent.mkdir(parents=True)
    path.write_bytes(steam_shortcuts.dump([steam_shortcuts.Node(steam_shortcuts.MAP, "shortcuts", children=[entry])]))


def test_steam_shortcut_to_the_old_stub_is_recognised_and_can_move_to_the_new_one(tmp_path, monkeypatch):
    root = tmp_path / "root"
    steam = tmp_path / "Steam"
    _vdf(steam / "userdata" / "1" / "config" / "shortcuts.vdf", str(root / "Roundtable Souls.exe"))
    monkeypatch.setattr(inno, "steam_root", lambda: steam)
    monkeypatch.setattr(inno, "steam_running", lambda: False)
    monkeypatch.setattr(inno.data_folder, "data_root", lambda: tmp_path / "data")
    new_stub = root / "Bayle.exe"
    assert len(inno.play_shortcuts_elsewhere(new_stub)) == 1  # the old stub is a launcher program
    changed = inno.point_play_shortcuts_here(new_stub, running=False)
    assert len(changed) == 1
    after = steam_shortcuts.read(steam / "userdata" / "1" / "config" / "shortcuts.vdf")[0]
    assert after.exe_path == str(new_stub)
