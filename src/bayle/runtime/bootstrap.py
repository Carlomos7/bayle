"""The program's composition root: create_engine() puts one run together, and the Engine it returns is what every
client (the window, --play, --check, --backend) is handed.

create_engine() runs when the program starts (cli.main, or a test), never at import time. use_data_folder() runs
first of all (the command line calls it before logging starts): the platform layer is told the data folder and the
build's instance scope instead of reading the settings. Then the app data is migrated (migrate_data:
storage.datamigrations, one-way, before anything reads it), which resolves the operations the last run left half done
(services.startup_recovery, once per start), and the launcher's database (storage.db) is opened inside that, migrated
first when needed; storage=False (--backend, beside a window that may hold it) opens none. When storage is refused for
the run (storage.db.StorageUnavailable) the engine has no database and says why; when a migration fails,
MigrationFailed reaches the caller, which must not report the version ready. With a database, the hash cache and the
activity log use it (once their old files' import is verified); without one, the hash cache is bypassed and activity
records stay in logs/jobs.jsonl. start_imports() runs those imports once the caller has reported ready.

The engine also owns the event bus, the plan store and the job manager its clients share, and the start-up steps that
run after the window opens (startup()). The module slots below (the data root, the instance scope, the record stores,
the CPU backend) are read by code far below; this module is the only one that binds them, and Engine.close() puts back
what they held before.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bayle import __version__
from bayle.config import identity
from bayle.config.settings import LauncherSettings, data_dir, load_settings
from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.mods import rebuild as mod_rebuild
from bayle.platform import cpu, data_folder, instance, paths
from bayle.platform import logging as run_logging
from bayle.services import startup_recovery
from bayle.session.operations import StartupStep
from bayle.session.startup import recovery_steps
from bayle.storage import datamigrations, mirror
from bayle.storage import db as storage_db
from bayle.storage.activity import ActivityLog
from bayle.storage.cache import HashCache
from bayle.storage.imports import run_imports
from bayle.storage.mirror import Mirror
from bayle.storage.rebuild_runs import RebuildRuns
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore

# What the runtime binds: name -> (module, its private slot). Their readers sit deep in mods/ and saves/; Phase 5
# hands them over as ports instead.
_SLOTS: dict[str, tuple[Any, str]] = {
    "data_root": (data_folder, "_ROOT"),
    "instance_scope": (instance, "_SCOPE"),
    "hash_store": (mod_rebuild, "_HASH_STORE"),
    "hash_file_in_use": (mod_rebuild, "_HASH_FILE_IN_USE"),
    "run_store": (mod_rebuild, "_RUN_STORE"),
    "mirror": (mirror, "_CURRENT"),
    "job_store": (run_logging, "_store"),
    "cpu_backend": (cpu, "_backend"),
    "cpu_broadcast": (cpu, "_broadcast"),
    "ui_thread": (cpu, "_ui_thread"),
}
UNBOUND: dict[str, Any] = {name: None for name in _SLOTS} | {"hash_file_in_use": True}


def bind(**values: Any) -> Callable[[], None]:
    """Point the named slots at values; the call returned puts back what they held before."""
    before = {name: getattr(*_SLOTS[name]) for name in values}
    for name, value in values.items():
        setattr(*_SLOTS[name], value)

    def restore() -> None:
        for name, value in before.items():
            setattr(*_SLOTS[name], value)

    return restore


@dataclass
class Engine:
    identity: identity.Identity
    settings: LauncherSettings
    game: catalog.Game
    locations: Locations
    data_dir: Path
    storage: storage_db.Database | None = field(default=None, repr=False)
    storage_problem: str = ""  # why there is no database this run, when there isn't
    hash_cache: HashCache | None = field(default=None, repr=False)
    rebuild_runs: RebuildRuns | None = field(default=None, repr=False)
    activity: ActivityLog | None = field(default=None, repr=False)
    bus: EventBus = field(default_factory=EventBus, repr=False)
    plans: PlanStore = field(default_factory=PlanStore, repr=False)
    jobs: JobManager = field(init=False, repr=False)
    recovered: frozenset[str] = frozenset()  # the profiles (normcased) the start's journal recovery looked at
    _unbind: list[Callable[[], None]] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        self.jobs = JobManager(self.bus)  # a client (the shell) sets its gates and observer on it

    def _located(self, loc: Locations) -> Locations:
        self.locations = loc
        return loc

    def reload_settings(self) -> LauncherSettings:
        """Read the settings file again (another part of the program, or another process, changed it) and apply its
        location overrides."""
        self.settings = load_settings()
        names = self.locations.profile_save_names
        paths.clear_detection_cache()  # Steam/me3/game folders may now resolve differently
        self._located(Locations.from_settings(self.settings, self.game).with_profile_save_names(names))
        return self.settings

    def select_game(self, game: catalog.Game | str) -> Locations:
        """Make game the one the window shows: its own location overrides, no setup save names yet."""
        self.game = game if isinstance(game, catalog.Game) else catalog.get(game)
        self.settings = load_settings()
        paths.clear_detection_cache()
        return self._located(Locations.from_settings(self.settings, self.game))

    def note_profile_saves(self, names: Mapping[str, str]) -> Locations:
        """The profile in use names its own save files (role -> file name): they are listed and repaired too."""
        return self._located(self.locations.with_profile_save_names(names))

    def startup(self, profile: Callable[[], Path | None] = lambda: None) -> list[StartupStep]:
        """The steps that run once the client is up, in order, off its UI thread (Session.startup): unreported game
        runs, the profile in use when the journal recovery did not cover it (profile: asked when the step runs), older
        save folders."""
        return recovery_steps(lambda: self.locations, profile, self.recovered)

    def use_cpu(self, backend: cpu.Backend, broadcast: cpu.Backend, ui_thread: int | None) -> None:
        """CPU tasks go to the window's worker pool (platform/cpu_pool.py) until close(); ui_thread is the window's."""
        self._unbind.append(bind(cpu_backend=backend, cpu_broadcast=broadcast, ui_thread=ui_thread))

    def start_imports(self) -> threading.Thread | None:
        """Import the old record files into the database in the background (storage.imports); call it only after
        reporting ready. None without a database."""
        if self.storage is None or self.hash_cache is None or self.activity is None:
            return None
        cache, activity, runs = self.hash_cache, self.activity, self.rebuild_runs
        hashes, jobs = data_folder.data_root() / "cache" / "hashes.json", run_logging.log_dir() / run_logging.JOBS_INDEX
        merges = data_folder.data_root() / "merges.json"
        thread = threading.Thread(
            target=run_imports,
            args=(hashes, jobs, cache, activity, run_logging.log, runs, merges),
            name="storage-imports",
            daemon=True,
        )
        thread.start()
        return thread

    def close(self) -> None:
        """Unbind everything the engine bound (the hash cache and the activity log go back to their files), then
        close the database (its connections and its shared lock); the process ending does the same."""
        while self._unbind:
            self._unbind.pop()()
        if self.storage is not None:
            self.storage.close()
            self.storage = None


def use_data_folder() -> Path:
    """Tell the platform layer where the data folder is and scope the instance names to this build and folder. The
    command line calls it before logging starts; create_engine calls it again."""
    data = data_dir()
    bind(data_root=data, instance_scope=instance.scope_name(identity.get().instance_prefix, data))
    return data


def migrate_data(open_db=None, covered: set[str] | None = None):
    """The one place the app data is brought to this build's data version (storage.datamigrations), before anything
    reads it; the journal recovery runs inside it (covered gets the profiles it looked at). open_db: the database
    open, or None to open none. Raises datamigrations.MigrationError, a storage.db.MigrationFailed, when the folder is
    refused or the migration failed; the caller must not report the version ready."""
    return datamigrations.migrate(
        data_folder.data_root(),
        __version__,
        recover_journals=lambda: startup_recovery.recover(covered),
        open_db=open_db,
    )


def create_engine(start_game: catalog.Game | None = None, *, storage: bool = True) -> Engine:
    """The engine for one run: the game is start_game (--game), else the tab the window last showed. storage=False
    opens no database (the files alone work, as before it existed)."""
    data = data_dir()
    unbind = [bind(data_root=data, instance_scope=instance.scope_name(identity.get().instance_prefix, data))]
    covered: set[str] = set()
    problem = ""
    try:
        db = migrate_data(
            (lambda: storage_db.open_database(data_folder.data_root())) if storage else None, covered=covered
        )
    except storage_db.StorageUnavailable as e:
        db = None
        problem = str(e)
        run_logging.log(f"storage: {e}")
    settings = load_settings()  # after the migration: it may have rewritten the file
    game = start_game or catalog.get(settings.game)
    engine = Engine(identity.get(), settings, game, Locations.from_settings(settings, game), data)
    engine.storage, engine.storage_problem, engine.recovered = db, problem, frozenset(covered)
    engine._unbind = unbind
    if db is not None:
        engine.hash_cache = HashCache(db, run_logging.log)
        engine.activity = ActivityLog(db, run_logging.log)
        engine.rebuild_runs = RebuildRuns(db, run_logging.log)
        unbind.append(
            bind(
                hash_store=engine.hash_cache,
                run_store=engine.rebuild_runs,
                mirror=Mirror(db, run_logging.log),
                job_store=engine.activity,
            )
        )
    elif storage:  # storage refused for this run: no persistent hash cache; job records go to jobs.jsonl
        unbind.append(bind(hash_store=None, hash_file_in_use=False, job_store=None))
    return engine
