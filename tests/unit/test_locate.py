"""The saves-folder override: refused unless it holds a game's save, blank detects, a valid one is what is used."""

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game import catalog
from roundtable_souls.game.locate import Locations, saves_dir_problem


def test_a_saves_folder_with_no_account_holding_a_save_is_refused(tmp_path):
    (tmp_path / "123").mkdir()
    (tmp_path / "123" / "notes.txt").write_text("x")
    assert saves_dir_problem(tmp_path, catalog.ELDEN_RING)
    assert saves_dir_problem(tmp_path / "missing", catalog.ELDEN_RING)


def test_a_valid_override_is_what_save_roots_returns_and_blank_detects(tmp_path, monkeypatch):
    (tmp_path / "123").mkdir()
    (tmp_path / "123" / "ER0000.sl2").write_bytes(b"x")
    assert saves_dir_problem(tmp_path, catalog.ELDEN_RING) == ""
    loc = Locations.from_settings(LauncherSettings(saves_dir=str(tmp_path)), catalog.ELDEN_RING)
    assert loc.save_roots() == [tmp_path]
    monkeypatch.setattr("roundtable_souls.platform.paths.save_roots_for", lambda *a: ["detected"])
    blank = Locations.from_settings(LauncherSettings(), catalog.ELDEN_RING)
    assert blank.save_roots() == ["detected"]
