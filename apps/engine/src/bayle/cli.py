"""The command line: `bayle` opens the window; --play, --check and --update run without one, and --game
picks the game. --self-test [REPORT] checks that a build starts and initializes (off-screen, in a temporary data
folder). --play --allow-without-backup starts the game even when 'back up saves before Play' fails.
--check-storage opens (creating or upgrading) the launcher's database in the data folder, imports the old record files
(cache/hashes.json, logs/jobs.jsonl) into it and prints what it found: a check for builds, which touches nothing
outside the data folder. Each mode imports only what it needs, so a Play from a Steam shortcut never loads the
window."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bayle.modules.games.catalog import Game


@dataclass(frozen=True)
class WindowHooks:
    """What the engine borrows from the window program, injected so no path here imports Qt: the window's main
    (takes the Engine), the one-shot message box (heading, detail, buttons -> index) and the full self-test
    (data folder, out -> exit code). Each callable imports its Qt code when called, never at construction."""

    shell_main: Callable[..., int]
    ask: Callable[..., int]
    self_test: Callable[[Path, Callable[[str], None]], int]
    # the app's updater, called once the data folder and logging are set up: Velopack's install/update/uninstall
    # hooks (which exit there) and --update; returns an exit code to stop with, or None to go on
    startup: Callable[[list[str]], int | None] = lambda argv: None
    ready: Callable[[str], None] = lambda kind: None  # this version started and runs: an update's watchdog stands down
    program: tuple[str, ...] = ()  # the command that starts the window program (a notice's "Open Bayle")


def main(argv: list[str] | None = None, window: WindowHooks | None = None) -> int:
    """Console entry point: the window (when `window` is given); or without one --play, --check, --update (the window program's startup
    hook). argv is sys.argv by default (program name first)."""
    argv = sys.argv if argv is None else argv
    from bayle.runtime.bootstrap import bind_ports

    bind_ports()  # every path below may run a workflow, with or without an engine
    if "--worker" in argv:  # a CPU worker for the window (work/cpu.py): before anything else starts
        from bayle.work import cpu

        return cpu.worker_main()
    if "--backend" in argv:  # the HTTP API for the web front end (decision 0012): no Qt, no window
        from bayle.adapters.persistence.db import MigrationFailed
        from bayle.adapters.persistence.settings_file import load_settings
        from bayle.adapters.system import app_paths
        from bayle.adapters.system import logging as run_logging
        from bayle.api.server import main as backend_main
        from bayle.runtime.bootstrap import create_engine, use_data_folder

        try:
            data = app_paths.backend_data_dir()  # explicit, before anything creates or moves a folder
        except ValueError as e:
            print(f"bayle --backend: {e}", file=sys.stderr)
            return 2
        from bayle.adapters.system import sandbox

        # Bayle Dev: before anything reads settings, which may name the player's real folders
        sandbox.guard_from_env(data, app_paths.exe_dir().parent if app_paths.FROZEN else app_paths.exe_dir())
        os.environ[app_paths.DATA_ENV] = str(data)  # the rest of the start-up reads it there, as --self-test's does
        use_data_folder()  # the same start-up as the window, minus Qt
        run_logging.setup_logging("DEBUG" if load_settings().log_level == "verbose" else "INFO", console=False)
        try:
            engine = create_engine(storage=False)  # the backend opens no database: the window may hold it
        except MigrationFailed as e:
            return storage_failed(e, window=False)
        return backend_main(engine)
    if "--self-test" in argv:  # first: before anything picks the data folder or starts Velopack's hooks
        return self_test(argv, window)
    from bayle.adapters.system import logging as run_logging
    from bayle.runtime.bootstrap import use_data_folder

    use_data_folder()  # before anything logs: the platform layer is told where the data folder is
    from bayle.adapters.persistence.settings_file import load_settings

    run_logging.setup_logging("DEBUG" if load_settings().log_level == "verbose" else "INFO")

    def crashed(exc_type, exc, tb):  # the window replaces this with one that also shows a message
        run_logging.log_crash(exc_type, exc, tb, "command line")
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = crashed
    if window is not None and (stop := window.startup(argv)) is not None:  # the updater's hooks and --update
        return stop
    if "--check-storage" in argv:
        return check_storage()
    game = None  # --game without --play/--check: the tab the window opens on, this run only
    if "--play" in argv or "--check" in argv or any(a.startswith("--game") for a in argv):
        from bayle.modules.games import catalog as games
        from bayle.modules.launch import play as core

        game = core.game_from_args(argv)
        if game is None:
            print(f"Unknown game. --game takes one of: {games.names_help()}", file=sys.stderr)
            return 2
        if "--play" in argv:
            return play_from_shortcut(game, allow_without_backup="--allow-without-backup" in argv, window=window)
        if "--check" in argv:
            from bayle.adapters.persistence.db import MigrationFailed
            from bayle.runtime.bootstrap import create_engine

            try:
                ctx = create_engine(game)
            except MigrationFailed as e:
                return storage_failed(e, None)
            with run_logging.job_store_scope(ctx.activity):  # no JobManager here: the standalone job gets the engine's
                core.check(ctx.settings, ctx.locations, ctx.data_dir)
            return 0
    from bayle.adapters.persistence.db import MigrationFailed
    from bayle.runtime.bootstrap import create_engine

    if window is None:  # python -m bayle from the engine alone: the headless modes above still work
        print("No window program is installed: use --play, --check, --update or --check-storage.", file=sys.stderr)
        return 2
    try:
        engine = create_engine(game)
    except MigrationFailed as e:  # no window, so no ready report: an update's watchdog rolls back
        return storage_failed(e, window)
    return int(window.shell_main(engine) or 0)


def self_test(argv: list[str], window: WindowHooks | None = None) -> int:
    """--self-test [REPORT]: check that this build starts and initializes (ui/self_test.py; technical specification
    §8.5), off-screen, in a temporary data folder that is removed afterwards. The report goes to standard output and,
    when given, to the REPORT file (a windowed build has no console). Exit 0 only when every check passed."""
    import os
    import shutil
    import tempfile
    from pathlib import Path

    args = argv[argv.index("--self-test") + 1 :]
    report = Path(args[0]).resolve() if args and not args[0].startswith("-") else None
    data = Path(tempfile.mkdtemp(prefix="rs-self-test-")).resolve()
    os.environ["ROUNDTABLE_SOULS_DATA"] = str(data)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"  # never a window on screen
    lines: list[str] = []

    def out(line: str) -> None:
        lines.append(line)
        if sys.stdout is not None:
            print(line, flush=True)

    from bayle.adapters.system import logging as run_logging
    from bayle.runtime.bootstrap import use_data_folder

    try:
        use_data_folder()
        run_logging.setup_logging(console=False)
        if window is not None:
            code = window.self_test(data, out)
        else:
            from bayle import diagnostics

            code = diagnostics.run(data, out)
    except Exception as e:  # a crash in the harness itself is a failure, reported like the others
        out(f"FAIL  the self-test itself: {type(e).__name__}: {e}")
        code = 1
    finally:
        run_logging.shutdown()
        shutil.rmtree(data, ignore_errors=True)
    if report is not None:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return code


def check_storage() -> int:
    """--check-storage: open the database in the data folder (creating or upgrading it) and print the facts; exit 0
    only when it is open at the current schema. Used on builds, to prove the migrations were packaged."""
    import sqlite3

    from bayle.adapters.filesystem import data_folder
    from bayle.adapters.persistence import db as storage_db
    from bayle.adapters.system import identity
    from bayle.resources import MIGRATIONS_DIR
    from bayle.runtime.bootstrap import use_data_folder

    use_data_folder()
    root = data_folder.data_root()
    report: list[str] = []

    def say(line: str) -> None:
        report.append(line)
        print(line)

    scripts = sorted(p.name for p in (MIGRATIONS_DIR / "versions").glob("*.py"))
    say(f"identity: {identity.get().pack_id}")
    say(f"data folder: {root}")
    say(f"sqlite: {sqlite3.sqlite_version} (minimum {'.'.join(map(str, storage_db.MIN_SQLITE))})")
    say(f"migrations: {MIGRATIONS_DIR} ({len(scripts)} scripts: {', '.join(scripts) or 'none'})")
    ok = False
    try:
        db = storage_db.open_database(root, log=lambda line: say(f"  {line}"))
    except storage_db.StorageError as e:
        say(f"FAILED: {e}")
    else:
        try:
            head = storage_db.head_revision()
            say(f"database: {db.path} at {db.revision} (head {head}), journal {db.journal_mode}")
            ok = db.revision == head
            from bayle.adapters.persistence.activity import ActivityLog
            from bayle.adapters.persistence.cache import HashCache
            from bayle.adapters.persistence.imports import run_imports
            from bayle.adapters.system import logging as run_logging

            cache, activity = HashCache(db, say), ActivityLog(db, say)
            jobs = run_logging.log_dir() / run_logging.JOBS_INDEX
            from bayle.adapters.persistence.rebuild_runs import RebuildRuns

            out = run_imports(
                root / "cache" / "hashes.json",
                jobs,
                cache,
                activity,
                lambda line: say(f"  {line}"),
                RebuildRuns(db, say),
                root / "merges.json",
            )
            ok = ok and bool(out["hash cache"]) and bool(out["activity log"]) and bool(out["rebuild runs"])
        finally:
            db.close()
        say("OK" if ok else "FAILED: not at the current schema")
    try:  # a windowed build has no console: the report is also a file in the data folder
        (root / "storage-check.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok else 1


def storage_failed(error: Exception, window: WindowHooks | None) -> int:
    """The database upgrade failed: say so (the log, the console, and a small window when there is a display);
    this version does not report itself ready."""
    from bayle.adapters.system import logging as run_logging

    run_logging.log(f"error: Bayle could not start: {error}")
    print(f"Bayle could not start: {error}", file=sys.stderr)
    if window is not None:
        try:
            window.ask("Bayle could not start.", str(error))
        except Exception as e:  # no display: the log and the console say it
            run_logging.log(f"the message could not be shown: {e}")
    return 1


def play_from_shortcut(game, allow_without_backup: bool = False, window: WindowHooks | None = None) -> int:
    """--play: when the window is open, it runs Play itself (one launcher manages the session); otherwise Play runs
    here, holding the PLAY name so a second shortcut start, or a silent update, waits for it to end.
    allow_without_backup (--allow-without-backup): start even when 'back up saves before Play' fails."""
    from bayle.adapters.system import logging as run_logging
    from bayle.modules.launch import play as core
    from bayle.runtime import instance
    from bayle.runtime.bootstrap import create_engine

    ready = window.ready if window is not None else (lambda kind: None)
    message = f"play {game.key}" + (" allow-without-backup" if allow_without_backup else "")
    if instance.held(instance.WINDOW) and instance.send(message):
        ready("play")  # this version started and handed Play to its window
        run_logging.start_log("launcher: play (no window)", game.key)
        run_logging.log("Bayle is open: Play was handed to its window")
        return 0
    hold = instance.acquire(instance.PLAY)
    if hold is None:
        run_logging.start_log("launcher: play (no window)", game.key)
        run_logging.log("error: a Play from a Steam shortcut is already running")
        return 1
    try:
        from bayle.adapters.persistence.db import MigrationFailed

        try:
            ctx = create_engine(game)
        except MigrationFailed as e:  # not ready: an update's watchdog rolls back
            return storage_failed(e, None)
        ready("play")  # this version starts and runs: an update's watchdog can stand down
        ctx.start_imports()

        def notice(game: Game, why: str, headline: str | None = None) -> None:
            not_started_notice(game, why, headline, window)

        with run_logging.job_store_scope(ctx.activity):  # no JobManager here: the standalone job gets the engine's
            if allow_without_backup:
                return core.play_headless(ctx.settings, ctx.locations, notice=notice, allow_without_backup=True)
            return core.play_headless(ctx.settings, ctx.locations, notice=notice)
    finally:
        hold.release()


def not_started_notice(game: Game, why: str, headline: str | None = None, window: WindowHooks | None = None) -> None:
    """--play without the window, when the game was not started: a small window saying why, with a way to open the
    launcher (a Steam shortcut or Gaming Mode has nowhere else to show it). Nothing happens without a display."""
    from bayle.modules.launch import play as core

    try:
        import subprocess

        if window is None:
            raise RuntimeError("no window program")
        if headline:  # another reason than the merged mods (a failed backup before Play)
            heading, detail = headline, why
        else:
            heading = f"{game.name} was not started: your mods need a rebuild"
            detail = (
                f"{why}\n\nThe game does not start with merged mods that no longer match your mods, so it cannot "
                "run with a removed or changed mod still inside them."
            )
        if window.ask(heading, detail, ("Open Bayle", "Close")) == 0 and window.program:
            subprocess.Popen([*window.program, "--game", game.key], close_fds=True)
    except Exception as e:  # no display (a console, a test): the log says it
        core.run_logging.log(f"the notice could not be shown: {e}")
