"""The command line's modes: every window, service and OS call is faked (or the data folder is a temporary one), so
no window opens, no game starts and nothing outside the test's folders changes."""

import importlib
import subprocess
import sys
import types
from types import SimpleNamespace

import pytest
from bayle import cli
from bayle.adapters.persistence import db as storage_db
from bayle.adapters.persistence import settings_file
from bayle.adapters.system import data_folder
from bayle.adapters.system import logging as run_logging
from bayle.modules.launch import play as core
from bayle.runtime import bootstrap

from bayle_qt import entry
from bayle_qt.updater import apply, headless


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
    monkeypatch.setattr(bootstrap, "use_data_folder", lambda: None)
    monkeypatch.setattr(run_logging, "setup_logging", lambda level="INFO", **kw: levels.append(level))
    monkeypatch.setattr(run_logging, "log", lines.append)
    monkeypatch.setattr(run_logging, "log_crash", lambda *args: None)
    monkeypatch.setattr(settings_file, "load_settings", lambda: SimpleNamespace(log_level="normal", game="er"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    return SimpleNamespace(lines=lines, levels=levels)


def hooks(**over):
    """The injected window program: every hook fails the test unless the test gives it."""

    def unexpected(*args):
        raise AssertionError("unexpected window hook")

    return cli.WindowHooks(
        **{
            "shell_main": unexpected, "ask": unexpected, "self_test": unexpected,
            "startup": entry._startup, "ready": entry._ready, "program": entry._program(),
            **over,
        }
    )  # fmt: skip


def argv(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["roundtable-souls", *args])


def test_self_test_flag_hands_over_before_anything_else(monkeypatch):
    argv(monkeypatch, "--self-test")
    monkeypatch.setattr(cli, "self_test", lambda argv, window: 5)
    assert cli.main() == 5


def test_update_flag_passes_the_other_arguments(monkeypatch, quiet):
    argv(monkeypatch, "--update", "--game", "er")
    seen = []
    monkeypatch.setattr(headless, "update_headless", lambda args: seen.append(args) or 0)
    assert cli.main(window=hooks()) == 0
    assert seen == [["--game", "er"]]
    assert quiet.levels == ["INFO"]


def test_verbose_log_level_is_debug(monkeypatch, quiet):
    argv(monkeypatch, "--check-storage")
    monkeypatch.setattr(settings_file, "load_settings", lambda: SimpleNamespace(log_level="verbose"))
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
        cli, "play_from_shortcut", lambda g, allow_without_backup, window: calls.append((g, allow_without_backup)) or 0
    )
    assert cli.main() == 0
    assert calls == [(game, True)]


def test_check_flag_runs_the_check_on_the_context(monkeypatch, quiet):
    argv(monkeypatch, "--check", "--game", "er")
    monkeypatch.setattr(core, "game_from_args", lambda args: SimpleNamespace(key="er"))
    ctx = SimpleNamespace(settings="S", locations="L", data_dir="D", activity=None)
    monkeypatch.setattr(bootstrap, "create_engine", lambda game: ctx)
    checked = []
    monkeypatch.setattr(core, "check", lambda *args: checked.append(args))
    assert cli.main() == 0
    assert checked == [("S", "L", "D")]


def test_check_stops_when_the_database_upgrade_fails(monkeypatch, quiet):
    argv(monkeypatch, "--check", "--game", "er")
    monkeypatch.setattr(core, "game_from_args", lambda args: SimpleNamespace(key="er"))

    def failing(game):
        raise storage_db.MigrationFailed("the upgrade broke")

    monkeypatch.setattr(bootstrap, "create_engine", failing)
    monkeypatch.setattr(cli, "storage_failed", lambda error, window: 4)
    assert cli.main() == 4


def test_window_path_opens_the_window_on_the_context(monkeypatch, quiet):
    argv(monkeypatch)
    ctx = SimpleNamespace(name="ctx")
    monkeypatch.setattr(bootstrap, "create_engine", lambda game: ctx)
    shown = []
    assert cli.main(window=hooks(shell_main=lambda c: shown.append(c) or 3)) == 3
    assert shown == [ctx]


def test_window_path_without_a_window_program_says_so(monkeypatch, quiet, capsys):
    argv(monkeypatch)
    monkeypatch.setattr(bootstrap, "create_engine", lambda game: pytest.fail("no context without a window"))
    assert cli.main() == 2
    assert "No window program" in capsys.readouterr().err


def test_window_path_reports_a_failed_upgrade_in_a_window(monkeypatch, quiet):
    argv(monkeypatch)

    def failing(game):
        raise storage_db.MigrationFailed("no")

    monkeypatch.setattr(bootstrap, "create_engine", failing)
    seen = []
    monkeypatch.setattr(cli, "storage_failed", lambda error, window: seen.append(window) or 1)
    window = hooks()
    assert cli.main(window=window) == 1
    assert seen == [window]


def test_frozen_build_runs_velopack_startup_first(monkeypatch, quiet):
    argv(monkeypatch, "--update")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    started = []
    monkeypatch.setattr(apply, "velopack_startup", lambda: started.append(True))
    monkeypatch.setattr(headless, "update_headless", lambda args: 0)
    assert cli.main(window=hooks()) == 0
    assert started == [True]


def test_self_test_writes_the_report_and_returns_the_checks_result(monkeypatch, tmp_path, quiet):
    report = tmp_path / "report.txt"
    argv(monkeypatch, "--self-test", str(report))
    monkeypatch.setenv("ROUNDTABLE_SOULS_DATA", "")  # restored after the test; self_test sets it for this run
    monkeypatch.setenv("QT_QPA_PLATFORM", "")
    shutdowns = []
    monkeypatch.setattr(run_logging, "shutdown", lambda: shutdowns.append(True))
    window = hooks(self_test=lambda data, out: out("PASS window") or 0)
    assert cli.self_test(sys.argv, window) == 0
    assert report.read_text(encoding="utf-8") == "PASS window\n"
    assert shutdowns == [True]


def test_self_test_crash_in_the_harness_is_a_failure(monkeypatch, quiet, capsys):
    argv(monkeypatch, "--self-test")
    monkeypatch.setenv("ROUNDTABLE_SOULS_DATA", "")
    monkeypatch.setenv("QT_QPA_PLATFORM", "")
    monkeypatch.setattr(run_logging, "shutdown", lambda: None)

    def boom(data, out):
        raise ValueError("bad state")

    assert cli.self_test(sys.argv, hooks(self_test=boom)) == 1
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
    assert cli.storage_failed(RuntimeError("disk full"), None) == 1
    assert quiet.lines == ["error: Bayle could not start: disk full"]
    assert "could not start: disk full" in capsys.readouterr().err


def test_storage_failed_with_a_window_asks_and_survives_a_broken_box(monkeypatch, quiet):
    asked = []
    window = hooks(ask=lambda *args: asked.append(args))
    assert cli.storage_failed(RuntimeError("disk full"), window) == 1
    assert asked == [("Bayle could not start.", "disk full")]

    def broken(*args):
        raise OSError("no display")

    cli.storage_failed(RuntimeError("disk full"), hooks(ask=broken))
    assert quiet.lines[-1] == "the message could not be shown: no display"


def test_play_is_handed_to_an_open_window(monkeypatch, quiet):
    from bayle.runtime import instance

    from bayle_qt.updater import apply as updates

    marks, starts = [], []
    monkeypatch.setattr(instance, "held", lambda name: True)
    monkeypatch.setattr(instance, "send", lambda message: message == "play er")
    monkeypatch.setattr(updates, "mark_ready", marks.append)
    monkeypatch.setattr(run_logging, "start_log", lambda *args: starts.append(args))
    assert cli.play_from_shortcut(SimpleNamespace(key="er"), window=hooks()) == 0
    assert marks == ["play"] and starts == [("launcher: play (no window)", "er")]


def test_second_play_from_a_shortcut_is_refused(monkeypatch, quiet):
    from bayle.runtime import instance

    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(instance, "acquire", lambda name: None)
    monkeypatch.setattr(run_logging, "start_log", lambda *args: None)
    assert cli.play_from_shortcut(SimpleNamespace(key="er")) == 1
    assert quiet.lines == ["error: a Play from a Steam shortcut is already running"]


@pytest.mark.parametrize("allow", [False, True])
def test_play_runs_headless_and_releases_its_hold(monkeypatch, quiet, allow):
    from bayle.runtime import instance

    from bayle_qt.updater import apply as updates

    released, started = [], []
    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(instance, "acquire", lambda name: SimpleNamespace(release=lambda: released.append(True)))
    monkeypatch.setattr(updates, "mark_ready", lambda how: None)
    ctx = SimpleNamespace(start_imports=lambda: started.append(True), settings="S", locations="L", activity=None)
    monkeypatch.setattr(bootstrap, "create_engine", lambda game: ctx)
    calls = []
    monkeypatch.setattr(core, "play_headless", lambda s, loc, **kw: calls.append(kw) or 0)
    assert cli.play_from_shortcut(SimpleNamespace(key="er"), allow_without_backup=allow) == 0
    assert started == [True] and released == [True]
    assert calls[0].get("allow_without_backup", False) is allow


def test_play_with_a_failed_upgrade_still_releases_the_hold(monkeypatch, quiet):
    from bayle.runtime import instance

    released = []
    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(instance, "acquire", lambda name: SimpleNamespace(release=lambda: released.append(True)))
    monkeypatch.setattr(run_logging, "start_log", lambda *args: None)

    def failing(game):
        raise storage_db.MigrationFailed("no")

    monkeypatch.setattr(bootstrap, "create_engine", failing)
    monkeypatch.setattr(cli, "storage_failed", lambda error, window: 6)
    assert cli.play_from_shortcut(SimpleNamespace(key="er")) == 6
    assert released == [True]


class _Asked(list):
    window: cli.WindowHooks


def _notice_box(monkeypatch, answer):
    asked = _Asked()

    def ask(heading, detail, buttons=None):
        asked.append((heading, detail))
        if isinstance(answer, Exception):
            raise answer
        return answer

    asked.window = hooks(ask=ask)
    return asked


def test_notice_offers_the_launcher_and_opens_it_for_the_game(monkeypatch, quiet):
    asked = _notice_box(monkeypatch, 0)
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: opened.append(args))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "a mod needs a rebuild", window=asked.window)
    assert asked[0][0] == "Elden Ring was not started: your mods need a rebuild"
    assert "a mod needs a rebuild" in asked[0][1]
    assert opened == [[sys.executable, "-m", "bayle_qt", "--game", "er"]]


def test_notice_in_the_frozen_build_reopens_the_executable(monkeypatch, quiet):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    asked = _notice_box(monkeypatch, 0)
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: opened.append(args))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "why", window=asked.window)
    assert opened == [[sys.executable, "--game", "er"]]


def test_notice_closed_by_the_player_opens_nothing(monkeypatch, quiet):
    asked = _notice_box(monkeypatch, 1)
    opened = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: opened.append(args))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "why", window=asked.window)
    assert opened == []


def test_notice_with_a_headline_uses_it_as_the_heading(monkeypatch, quiet):
    asked = _notice_box(monkeypatch, 1)
    cli.not_started_notice(
        SimpleNamespace(key="er", name="Elden Ring"), "the backup failed", "Backup failed", asked.window
    )
    assert asked == [("Backup failed", "the backup failed")]


def test_notice_without_a_display_logs_why(monkeypatch, quiet):
    asked = _notice_box(monkeypatch, RuntimeError("no display"))
    cli.not_started_notice(SimpleNamespace(key="er", name="Elden Ring"), "why", window=asked.window)
    assert quiet.lines == ["the notice could not be shown: no display"]


def test_the_entry_module_exits_with_the_command_lines_code(monkeypatch):
    import runpy

    monkeypatch.setattr(entry, "main", lambda: 9)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("bayle_qt.__main__", run_name="__main__")
    assert exit_info.value.code == 9


def test_headless_paths_import_no_qt(tmp_path):
    """--worker, --update, --check-storage and --play never load PySide6: the engine is usable without Qt (the
    window program is injected). A fresh interpreter, because this process may already have imported Qt."""
    import os
    import textwrap

    code = textwrap.dedent(
        """
        import sys
        from unittest import mock
        from bayle import cli

        for flags in (["--worker"], ["--update"], ["--check-storage"], ["--play", "--game", "nope"]):
            with mock.patch("bayle.work.cpu.worker_main", return_value=0):
                cli.main(["bayle", *flags])
        assert not [m for m in sys.modules if m.split(".")[0] == "PySide6"], "Qt was imported"
        assert not [m for m in sys.modules if m.startswith("bayle_qt")], "bayle_qt was imported"
        """
    )
    env = {**os.environ, **{k: str(tmp_path / k) for k in ("LOCALAPPDATA", "APPDATA", "USERPROFILE")}}
    env["ROUNDTABLE_SOULS_DATA"] = str(tmp_path / "data")
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
