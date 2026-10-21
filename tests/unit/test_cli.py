"""The command line's modes: every window, service and OS call is faked (or the data folder is a temporary one), so
no window opens, no game starts and nothing outside the test's folders changes."""

import importlib
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest

from roundtable_souls import app, cli
from roundtable_souls.config import settings
from roundtable_souls.platform import data_folder
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import play as core
from roundtable_souls.storage import db as storage_db
from roundtable_souls.updates import apply, headless


def fake_module(monkeypatch, dotted, **attrs):
    """A stand-in for a module the command line imports inside a function: it is found by both `import` and
    `from package import name`, whether or not the real one was imported earlier in this run."""
    parent_name, leaf = dotted.rsplit(".", 1)
    parent = importlib.import_module(parent_name)
    module = types.ModuleType(dotted)
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, dotted, module)
    monkeypatch.setattr(parent, leaf, module, raising=False)
    return module


@pytest.fixture
def quiet(monkeypatch):
    """main() installs its own excepthook and logging; both are put back, and the log is kept in a list."""
    lines, levels = [], []
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(app, "use_data_folder", lambda: None)
    monkeypatch.setattr(run_logging, "setup_logging", lambda level="INFO", **kw: levels.append(level))
    monkeypatch.setattr(run_logging, "log", lines.append)
    monkeypatch.setattr(run_logging, "log_crash", lambda *args: None)
    monkeypatch.setattr(settings, "load_settings", lambda: SimpleNamespace(log_level="normal", game="er"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    return SimpleNamespace(lines=lines, levels=levels)


def argv(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["roundtable-souls", *args])


def test_self_test_flag_hands_over_before_anything_else(monkeypatch):
    argv(monkeypatch, "--self-test")
    monkeypatch.setattr(cli, "self_test", lambda: 5)
    assert cli.main() == 5


def test_update_flag_passes_the_other_arguments(monkeypatch, quiet):
    argv(monkeypatch, "--update", "--game", "er")
    seen = []
    monkeypatch.setattr(headless, "update_headless", lambda args: seen.append(args) or 0)
    assert cli.main() == 0
    assert seen == [["--game", "er"]]
    assert quiet.levels == ["INFO"]


def test_verbose_log_level_is_debug(monkeypatch, quiet):
    argv(monkeypatch, "--check-storage")
    monkeypatch.setattr(settings, "load_settings", lambda: SimpleNamespace(log_level="verbose"))
    monkeypatch.setattr(cli, "check_storage", lambda: 0)
    cli.main()
    assert quiet.levels == ["DEBUG"]


def test_check_storage_flag(monkeypatch, quiet):
    argv(monkeypatch, "--check-storage")
    monkeypatch.setattr(cli, "check_storage", lambda: 7)
    assert cli.main() == 7


def test_unknown_game_is_exit_2(monkeypatch, quiet, capsys):
    argv(monkeypatch, "--play", "--game", "nope")
    monkeypatch.setattr(core, "game_from_args", lambda args: None)
    assert cli.main() == 2
    assert "Unknown game" in capsys.readouterr().err


def test_play_flag_runs_play_from_the_shortcut(monkeypatch, quiet):
    argv(monkeypatch, "--play", "--game", "er", "--allow-without-backup")
    game = SimpleNamespace(key="er")
    monkeypatch.setattr(core, "game_from_args", lambda args: game)
    calls = []
    monkeypatch.setattr(
        cli, "play_from_shortcut", lambda g, allow_without_backup: calls.append((g, allow_without_backup)) or 0
    )
    assert cli.main() == 0
    assert calls == [(game, True)]


def test_check_flag_runs_the_check_on_the_context(monkeypatch, quiet):
    argv(monkeypatch, "--check", "--game", "er")
    monkeypatch.setattr(core, "game_from_args", lambda args: SimpleNamespace(key="er"))
    ctx = SimpleNamespace(settings="S", locations="L", data_dir="D")
    monkeypatch.setattr(app, "create_app", lambda game: ctx)
    checked = []
    monkeypatch.setattr(core, "check", lambda *args: checked.append(args))
    assert cli.main() == 0
    assert checked == [("S", "L", "D")]


def test_check_stops_when_the_database_upgrade_fails(monkeypatch, quiet):
    argv(monkeypatch, "--check", "--game", "er")
    monkeypatch.setattr(core, "game_from_args", lambda args: SimpleNamespace(key="er"))

    def failing(game):
        raise storage_db.MigrationFailed("the upgrade broke")

    monkeypatch.setattr(app, "create_app", failing)
    monkeypatch.setattr(cli, "storage_failed", lambda error, window: 4)
    assert cli.main() == 4


def test_window_path_opens_the_window_on_the_context(monkeypatch, quiet):
    argv(monkeypatch)
    ctx = SimpleNamespace(name="ctx")
    monkeypatch.setattr(app, "create_app", lambda game: ctx)
    shown = []
    fake_module(monkeypatch, "roundtable_souls.ui.launcher.window", main=lambda c: shown.append(c) or 3)
    assert cli.main() == 3
    assert shown == [ctx]


def test_window_path_reports_a_failed_upgrade_in_a_window(monkeypatch, quiet):
    argv(monkeypatch)

    def failing(game):
        raise storage_db.MigrationFailed("no")

    monkeypatch.setattr(app, "create_app", failing)
    seen = []
    monkeypatch.setattr(cli, "storage_failed", lambda error, window: seen.append(window) or 1)
    assert cli.main() == 1
    assert seen == [True]


def test_frozen_build_runs_velopack_startup_first(monkeypatch, quiet):
    argv(monkeypatch, "--update")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    started = []
    monkeypatch.setattr(apply, "velopack_startup", lambda: started.append(True))
    monkeypatch.setattr(headless, "update_headless", lambda args: 0)
    assert cli.main() == 0
    assert started == [True]


def test_self_test_writes_the_report_and_returns_the_checks_result(monkeypatch, tmp_path, quiet):
    report = tmp_path / "report.txt"
    argv(monkeypatch, "--self-test", str(report))
    monkeypatch.setenv("ROUNDTABLE_SOULS_DATA", "")  # restored after the test; self_test sets it for this run
    monkeypatch.setenv("QT_QPA_PLATFORM", "")
    shutdowns = []
    monkeypatch.setattr(run_logging, "shutdown", lambda: shutdowns.append(True))
    fake_module(monkeypatch, "roundtable_souls.ui.self_test", run=lambda data, out: out("PASS window") or 0)
    assert cli.self_test() == 0
    assert report.read_text(encoding="utf-8") == "PASS window\n"
    assert shutdowns == [True]


def test_self_test_crash_in_the_harness_is_a_failure(monkeypatch, quiet, capsys):
    argv(monkeypatch, "--self-test")
    monkeypatch.setenv("ROUNDTABLE_SOULS_DATA", "")
    monkeypatch.setenv("QT_QPA_PLATFORM", "")
    monkeypatch.setattr(run_logging, "shutdown", lambda: None)

    def boom(data, out):
        raise ValueError("bad state")

    fake_module(monkeypatch, "roundtable_souls.ui.self_test", run=boom)
    assert cli.self_test() == 1
    assert "FAIL  the self-test itself: ValueError: bad state" in capsys.readouterr().out


def test_check_storage_reports_an_open_database(quiet):
    """The conftest points the data folder at a temporary folder: a real database is created there."""
    root = data_folder.data_root()
    assert cli.check_storage() == 0
    report = (root / "storage-check.txt").read_text(encoding="utf-8")
    assert report.splitlines()[-1] == "OK"
    assert "migrations:" in report


def test_check_storage_fails_when_the_database_will_not_open(monkeypatch, quiet, capsys):
    def locked(root, log=None):
        raise storage_db.StorageError("locked by another process")

    monkeypatch.setattr(storage_db, "open_database", locked)
    assert cli.check_storage() == 1
    assert "FAILED: locked by another process" in capsys.readouterr().out


def test_storage_failed_without_a_window_logs_and_prints(monkeypatch, quiet, capsys):
    assert cli.storage_failed(RuntimeError("disk full"), window=False) == 1
    assert quiet.lines == ["error: Bayle could not start: disk full"]
    assert "could not start: disk full" in capsys.readouterr().err


def test_storage_failed_with_a_window_asks_and_survives_a_broken_box(monkeypatch, quiet):
    asked = []
    fake_module(monkeypatch, "roundtable_souls.ui.message_box", ask=lambda *args: asked.append(args))
    assert cli.storage_failed(RuntimeError("disk full"), window=True) == 1
    assert asked == [("Bayle could not start.", "disk full")]

    def broken(*args):
        raise OSError("no display")

    fake_module(monkeypatch, "roundtable_souls.ui.message_box", ask=broken)
    cli.storage_failed(RuntimeError("disk full"), window=True)
    assert quiet.lines[-1] == "the message could not be shown: no display"


def test_play_is_handed_to_an_open_window(monkeypatch, quiet):
    from roundtable_souls.platform import instance
    from roundtable_souls.updates import apply as updates

    marks, starts = [], []
    monkeypatch.setattr(instance, "held", lambda name: True)
    monkeypatch.setattr(instance, "send", lambda message: message == "play er")
    monkeypatch.setattr(updates, "mark_ready", marks.append)
    monkeypatch.setattr(run_logging, "start_log", lambda *args: starts.append(args))
    assert cli.play_from_shortcut(SimpleNamespace(key="er")) == 0
    assert marks == ["play"] and starts == [("launcher: play (no window)", "er")]


def test_second_play_from_a_shortcut_is_refused(monkeypatch, quiet):
    from roundtable_souls.platform import instance

    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(instance, "acquire", lambda name: None)
    monkeypatch.setattr(run_logging, "start_log", lambda *args: None)
    assert cli.play_from_shortcut(SimpleNamespace(key="er")) == 1
    assert quiet.lines == ["error: a Play from a Steam shortcut is already running"]


@pytest.mark.parametrize("allow", [False, True])
def test_play_runs_headless_and_releases_its_hold(monkeypatch, quiet, allow):
    from roundtable_souls.platform import instance
    from roundtable_souls.updates import apply as updates

    released, started = [], []
    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(instance, "acquire", lambda name: SimpleNamespace(release=lambda: released.append(True)))
    monkeypatch.setattr(updates, "mark_ready", lambda how: None)
    ctx = SimpleNamespace(start_imports=lambda: started.append(True), settings="S", locations="L")
    monkeypatch.setattr(app, "create_app", lambda game: ctx)
    calls = []
    monkeypatch.setattr(core, "play_headless", lambda s, loc, **kw: calls.append(kw) or 0)
    assert cli.play_from_shortcut(SimpleNamespace(key="er"), allow_without_backup=allow) == 0
    assert started == [True] and released == [True]
    assert calls[0].get("allow_without_backup", False) is allow


def test_play_with_a_failed_upgrade_still_releases_the_hold(monkeypatch, quiet):
    from roundtable_souls.platform import instance

    released = []
    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(instance, "acquire", lambda name: SimpleNamespace(release=lambda: released.append(True)))
    monkeypatch.setattr(run_logging, "start_log", lambda *args: None)

    def failing(game):
        raise storage_db.MigrationFailed("no")

    monkeypatch.setattr(app, "create_app", failing)
    monkeypatch.setattr(cli, "storage_failed", lambda error, window: 6)
    assert cli.play_from_shortcut(SimpleNamespace(key="er")) == 6
    assert released == [True]


def _notice_box(monkeypatch, answer):
    asked = []

    def ask(heading, detail, buttons=None):
        asked.append((heading, detail))
        if isinstance(answer, Exception):
            raise answer
        return answer

    fake_module(monkeypatch, "roundtable_souls.ui.message_box", ask=ask)
    return asked


def test_notice_offers_the_launcher_and_opens_it_for_the_game(monkeypatch, quiet):
    asked = _notice_box(monkeypatch, 0)
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: opened.append(args))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "a mod needs a rebuild")
    assert asked[0][0] == "Elden Ring was not started: your mods need a rebuild"
    assert "a mod needs a rebuild" in asked[0][1]
    assert opened == [[sys.executable, "-m", "roundtable_souls", "--game", "er"]]


def test_notice_in_the_frozen_build_reopens_the_executable(monkeypatch, quiet):
    _notice_box(monkeypatch, 0)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: opened.append(args))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "why")
    assert opened == [[sys.executable, "--game", "er"]]


def test_notice_closed_by_the_player_opens_nothing(monkeypatch, quiet):
    _notice_box(monkeypatch, 1)
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: opened.append(args))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "why")
    assert opened == []


def test_notice_with_a_headline_uses_it_as_the_heading(monkeypatch, quiet):
    asked = _notice_box(monkeypatch, 1)
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "the backup failed", "Backup failed")
    assert asked == [("Backup failed", "the backup failed")]


def test_notice_without_a_display_logs_why(monkeypatch, quiet):
    _notice_box(monkeypatch, RuntimeError("no display"))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "why")
    assert quiet.lines == ["the notice could not be shown: no display"]


def test_the_entry_module_exits_with_the_command_lines_code(monkeypatch):
    import runpy

    monkeypatch.setattr(cli, "main", lambda: 9)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("roundtable_souls.__main__", run_name="__main__")
    assert exit_info.value.code == 9
