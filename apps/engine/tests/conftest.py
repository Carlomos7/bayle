"""Shared fixtures: an isolated settings file and data folder so tests never read or write the developer's own
(backups, the save library, deleted profiles), and no item names from whatever mods happen to be installed on the
machine running the tests (tests that read names build their own).

The write guard (writes_stay_in_temporary_folders, an audit hook): while a test runs, file changes made through
Python in the test process itself outside pytest's temporary folders and the system temporary folder raise
PermissionError, so a patch undone too early fails the test instead of touching the developer's files.
  Covered: open() and os.open() for writing (so Path.write_*, touch, tempfile), rename, replace, remove/unlink,
  rmdir, mkdir/makedirs, truncate, utime, chmod, link, symlink, shutil's copyfile, copytree, rmtree (and move,
  which is made of these), and sqlite3.connect (a read-only "mode=ro" URI excepted).
  Not covered: child processes the test starts; native code writing without Python's audit events (ctypes and
  Win32 calls such as the Recycle Bin's SHFileOperation, Qt's own file I/O such as QSettings or QSaveFile, writes
  SQLite makes after a connection is open); files opened before the test started (session- or module-scoped
  fixtures) and writes to already-open file descriptors; paths given relative to a dir_fd.
  Allowed besides the temporary folders: named pipes, the null device (os.devnull: output thrown away, as a
  library's quiet subprocess does), __pycache__ folders, and the Recycle Bin items a test itself
  created (recycle_bin_left_clean restores and purges them). Reading is never refused."""

import itertools
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import pytest

from bayle.adapters.filesystem import data_folder
from bayle.adapters.games import me3_paths
from bayle.adapters.games import paths as common
from bayle.adapters.persistence import settings_file
from bayle.adapters.saves import item_names
from bayle.modules.saves import backups as save_backups
from bayle.runtime import bootstrap, instance

bootstrap.bind_ports()  # the ports are stateless forwarders: bound once for the whole session

_WRITABLE: list[str] = []  # while a test runs: the folders it may write in; empty = not guarding
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC


def _refuse_outside(path) -> None:
    if not _WRITABLE or path is None or isinstance(path, int):
        return
    try:
        text = os.fsdecode(path)
    except TypeError:
        return
    if text.startswith("\\\\.\\pipe\\"):  # a named pipe (platform.instance talking to the window), not a file
        return
    if os.path.normcase(text) == os.path.normcase(os.devnull):  # output thrown away: no file changes
        return
    for candidate in (os.path.abspath(text), os.path.realpath(text)):
        p = os.path.normcase(candidate)
        if "__pycache__" in p or any(p == root or p.startswith(root + os.sep) for root in _WRITABLE):
            return
    raise PermissionError(f"a test tried to write outside its temporary folders: {text}")


def _relative_to_a_dir_fd(path, dir_fd) -> bool:
    """A name relative to an open directory (shutil.rmtree on Linux deletes this way): where it is can't be told
    from the name, so it is not checked (the module docstring lists dir_fd paths as not covered)."""
    return isinstance(dir_fd, int) and not isinstance(dir_fd, bool) and not os.path.isabs(os.fsdecode(path))


def _audit(event: str, args: tuple) -> None:
    """The audit events listed in the module docstring as covered."""
    if not _WRITABLE:
        return
    if event == "open":
        path, mode, flags = args
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (mode is None and flags & _WRITE_FLAGS):
            _refuse_outside(path)
    elif event in ("os.remove", "os.rmdir", "os.mkdir", "os.truncate", "os.utime", "os.chmod", "shutil.rmtree"):
        if not _relative_to_a_dir_fd(args[0], args[-1]):
            _refuse_outside(args[0])
    elif event in ("os.rename", "os.replace", "os.link", "os.symlink"):
        dir_fds = args[2:4] if event in ("os.rename", "os.replace", "os.link") else (args[-1], args[-1])
        for path, dir_fd in zip(args[:2], dir_fds, strict=False):
            if not _relative_to_a_dir_fd(path, dir_fd):
                _refuse_outside(path)
    elif event in ("shutil.copyfile", "shutil.copytree"):
        _refuse_outside(args[1])
    elif event == "sqlite3.connect":
        target = os.fsdecode(args[0]) if isinstance(args[0], (str, bytes, os.PathLike)) else ""
        if target and target != ":memory:" and "mode=ro" not in target:
            if target.startswith("file:"):
                target = url2pathname(urlparse(target).path)
            _refuse_outside(target)


sys.addaudithook(_audit)  # audit hooks can't be removed; _WRITABLE switches it on per test


@pytest.fixture(autouse=True)
def writes_stay_in_temporary_folders(tmp_path_factory):
    """Switch the write guard on for the whole test (module docstring): pytest's temporary folders (every tmp_path)
    and the system temporary folder (where pytest and Qt keep their own scratch files) stay writable."""
    roots = {tmp_path_factory.getbasetemp(), Path(tempfile.gettempdir())}
    _WRITABLE[:] = sorted(
        {os.path.normcase(os.path.realpath(r)) for r in roots} | {os.path.normcase(str(r)) for r in roots}
    )
    yield
    _WRITABLE.clear()


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_file, "settings_path", lambda: tmp_path / "launcher_settings.json")
    monkeypatch.setattr(data_folder, "data_root", lambda: tmp_path / "launcher-data")
    # Moving older folders into the data folder only ever happens inside this test's own folder: a test that builds
    # the real window sees the developer's real saves and profiles, and must never move anything out of them.
    for module, name in ((save_backups, "adopt_legacy_save_folders"), (data_folder, "adopt_legacy_profile_folders")):
        real = getattr(module, name)

        def guarded(folder, *args, _real=real, **kwargs):
            if tmp_path.resolve() in Path(folder).resolve().parents:
                return _real(folder, *args, **kwargs)
            return None

        monkeypatch.setattr(module, name, guarded)
    save_backups._adopted.clear()
    yield
    save_backups._adopted.clear()


@pytest.fixture(autouse=True)
def example_overhaul_shipped(monkeypatch):
    """The launcher ships no overhaul config; the tests ship an invented one (tests/data/overhauls)."""
    from bayle.adapters.overhauls import recipes as overhaul_recipes
    from bayle.adapters.overhauls import writer as overhaul_writer

    here = Path(__file__).parent / "data" / "overhauls"
    monkeypatch.setattr(overhaul_recipes, "SHIPPED_DIR", here)
    monkeypatch.setattr(overhaul_writer, "SHIPPED_DIR", here)


@pytest.fixture(autouse=True)
def installed_me3_not_asked(monkeypatch):
    """A rebuild records the installed me3's version by running it: tests never run the developer's me3."""
    from bayle.adapters.overhauls.backends import builtin

    monkeypatch.setattr(builtin, "_me3_version", lambda _loc: "0.13.0")


@pytest.fixture(autouse=True)
def no_programs_running(monkeypatch):
    """Tests never list this machine's processes (whether Steam or the game runs here): nothing is running unless a
    test says so. Listing them took about a second each time on Windows."""
    from bayle.adapters.system import proc

    monkeypatch.setattr(proc, "processes", lambda name: [])


@pytest.fixture(autouse=True)
def saves_written_without_waiting(monkeypatch):
    """The save lock waits until a save has been unchanged for 4 seconds; a test's save was always just written, so
    every write waited. Tests that check the wait set services.saves.SETTLE_SECONDS themselves."""
    from bayle.modules.saves import service as saves

    monkeypatch.setattr(saves, "SETTLE_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def run_in_a_temporary_folder(tmp_path, monkeypatch):
    """Every test runs from its own temporary folder, never the repository: a relative path gone wrong (an empty path
    is the current folder) can then only reach that folder."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def recycle_bin_left_clean(request, monkeypatch, tmp_path):
    """Removing a mod sends its folder to the trash. On Windows that is the real Recycle Bin: every item a test sends
    there is purged after it, so the bin is left as it was. Elsewhere the desktop trash is a folder the launcher
    writes itself, so each test gets its own in its temporary folder (the real one is never touched)."""
    from bayle.adapters.filesystem import trash

    if sys.platform != "win32":
        own = tmp_path / "Trash"
        monkeypatch.setattr(trash, "_home_trash", lambda: own)
        monkeypatch.setattr(trash, "_trash_for", lambda path: (own.mkdir(parents=True, exist_ok=True), own)[1])

    if sys.platform == "win32" and request.node.get_closest_marker("real_recycle_bin") is None:
        # The real shell call, made before Qt's first QML window exists, crashes that load on a Windows runner (access
        # violation; CI runs the session tests first). A bin of the test's own, laid out as the real one is, instead.
        bin_dir = tmp_path / "$Recycle.Bin" / "S-1-5-21-0"
        ids = itertools.count(1)

        def send_to_own_bin(path):
            n = f"T{next(ids):04d}"
            bin_dir.mkdir(parents=True, exist_ok=True)
            item, info = bin_dir / f"$R{n}", bin_dir / f"$I{n}"
            os.replace(path, item)
            info.write_bytes(b"x")
            return {
                "kind": "windows",
                "item": str(item),
                "info": str(info),
                "original": str(path),
                "deleted": time.time(),
            }

        monkeypatch.setattr(trash, "_send_windows", send_to_own_bin)

    made = []
    real = trash.send

    def send(path):
        rec = real(path)
        made.append(rec)
        for p in (rec.get("item"), rec.get("info")):  # this test's own bin items may be restored and purged
            if p:
                _WRITABLE.append(os.path.normcase(os.path.abspath(p)))
        return rec

    monkeypatch.setattr(trash, "send", send)
    yield
    for rec in made:
        trash.purge(rec)


@pytest.fixture(autouse=True)
def clean_logging(isolated_settings):
    """No job, sink or standalone run survives a test, so one test's lines never reach another's files. Ended while
    the test's own data folder is still in place (isolated_settings), where the job's index is written."""
    from bayle.adapters.system import logging as run_logging

    yield
    job = run_logging.current_job()
    if job is not None:
        run_logging.end_job(job)
    if run_logging._standalone is not None:
        run_logging.end_job(run_logging._standalone)
        run_logging._standalone = None
    run_logging._dir_override = None


@pytest.fixture(autouse=True)
def no_installed_mod_names(request, monkeypatch):
    if request.module.__name__.endswith("test_gamefiles"):
        return
    monkeypatch.setattr(item_names, "item_names", lambda *a, **k: item_names.ItemNames({}))


@pytest.fixture(autouse=True)
def runtime_unbound():
    """create_engine binds the record stores, the data folder and the instance scope (and the window the CPU pool);
    every test ends with all of them unbound, so no test writes through another test's (closed) database, finds
    another's folder, or counts the window's thread as the UI thread (CI runs the unit and ui tests in one process)."""
    yield
    bootstrap.bind(**bootstrap.UNBOUND)


@pytest.fixture(autouse=True)
def elden_ring_is_the_active_game(tmp_path, monkeypatch):
    """Every test starts with no detection cached from a prior test that used a different environment, and instance
    names scoped to its own folder. On Linux
    their lock files and sockets go in a folder of the test's own, not the real $XDG_RUNTIME_DIR: a short one directly
    in the system temporary folder, because a socket's path must stay under about 108 characters."""
    bootstrap.bind(instance_scope=instance.scope_name("RoundtableSouls.Test", tmp_path))
    locks = Path(tempfile.mkdtemp(prefix="rsl-"))
    monkeypatch.setattr(instance, "_lock_dir", lambda: locks)
    common.clear_detection_cache()
    me3_paths._PROFILE_GAMES_CACHE.clear()
    yield
    common.clear_detection_cache()
    me3_paths._PROFILE_GAMES_CACHE.clear()
    shutil.rmtree(locks, ignore_errors=True)


def pytest_collection_modifyitems(items):
    """The tests of the real Recycle Bin run last: the shell it loads must not come before Qt's first QML window."""
    items.sort(key=lambda item: item.get_closest_marker("real_recycle_bin") is not None)
