"""The engine half of --self-test (technical specification §8.5): proves that a build, as packaged, starts and
initializes: the modules and data the bundler had to collect are there, the database opens at the current schema,
and a CPU worker answers. The window program adds its own checks through `qt` (ui/self_test.py: the QML modules and
the shell with every registered page in every theme with no QML warning). It runs off-screen in a temporary data folder
(cli.py points ROUNDTABLE_SOULS_DATA there before anything else runs) over an empty context: nothing of the user's
is read or written, no game or me3 is started, no update feed is contacted.

What it does not verify: visual correctness, behaviour against a real game, saves or me3, or native integration
(window manager, high-DPI, file dialogs, shortcuts, the installer, the updater).

One line per check, then a summary; exit code 0 only when every check passed."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from bayle.resources import DATA_DIR, PACKAGE_DIR
from bayle.work import cpu

LIST_FILE = DATA_DIR / "self-test.json"


class Report:
    def __init__(self, out: Callable[[str], None] = print):
        self.out = out
        self.failed = 0
        self.passed = 0

    def check(self, name: str, test: Callable[[], str | None]) -> None:
        """Run test(); it returns None (or a note) when the check passed and raises when it did not."""
        try:
            note = test()
        except Exception as e:  # every failure is reported, none stops the others
            self.failed += 1
            self.out(f"FAIL  {name}: {type(e).__name__}: {e}")
            return
        self.passed += 1
        self.out(f"ok    {name}" + (f" ({note})" if note else ""))


def requirements(list_file: Path = LIST_FILE) -> dict:
    return json.loads(list_file.read_text(encoding="utf-8"))


def run_list(report: Report, need: dict, base: Path = PACKAGE_DIR) -> None:
    """The python_modules and files of one requirements list (files relative to base, the package that ships them);
    a missing one is a failure, never a skip."""
    for name in need["python_modules"]:
        report.check(f"module {name}", lambda name=name: _import(name))
    for spec in need["files"]:
        report.check(f"file {spec.get('path') or spec.get('glob')}", lambda spec=spec: _files(spec, base))


def run(data_dir: Path, out: Callable[[str], None] = print, qt: Callable[[Report, Path], None] | None = None) -> int:
    """All checks; 0 when every one passed. qt adds the window program's checks (module and file list, QML)."""
    report = Report(out)
    out(f"Roundtable Souls self-test, data folder {data_dir}")
    report.check("isolated data folder", lambda: _isolated(data_dir))
    try:
        need = requirements()
    except (OSError, ValueError) as e:
        problem = e
        report.check("the self-test list", lambda: _raise(problem))
        need = {"python_modules": [], "files": []}
    run_list(report, need)
    report.check("SQLite version", _sqlite)
    report.check("database opens at the current schema", lambda: _database(data_dir))
    report.check("a CPU worker process starts and answers", _worker)
    if qt is not None:
        qt(report, data_dir)
    out(f"{report.passed} passed, {report.failed} failed")
    out(
        "Limits: packaging and initialization only; not visual correctness, real games, saves or me3, native "
        "integration, the installer or the updater."
    )
    return 1 if report.failed else 0


def _worker() -> str:
    """The build starts itself again with --worker (work/cpu.py) and gets an answer, without Qt in the worker."""
    import subprocess

    request = json.dumps({"id": 1, "task": "bayle.work.cpu:probe", "args": {"value": 41}}) + "\n"
    done = subprocess.run(cpu.worker_command(), input=request.encode(), capture_output=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"the worker exited with {done.returncode}: {done.stderr.decode(errors='replace')[-300:]}")
    reply = json.loads(done.stdout.decode().splitlines()[-1])
    if not reply.get("ok") or reply["result"]["value"] != 42:
        raise RuntimeError(f"unexpected reply {reply}")
    if reply["result"]["qt"]:
        raise RuntimeError("the worker started a Qt application")
    return f"pid {reply['result']['pid']}"


def _raise(e: Exception):
    raise e


def _isolated(data_dir: Path) -> str:
    from bayle.adapters.system.app_paths import data_dir as settings_data_dir

    data_dir = data_dir.resolve()
    if Path(os.environ.get("ROUNDTABLE_SOULS_DATA", "")).resolve() != data_dir or settings_data_dir() != data_dir:
        raise RuntimeError(f"the data folder is {settings_data_dir()}, not the temporary {data_dir}")
    return str(data_dir)


def _import(name: str) -> None:
    importlib.import_module(name)


def _files(spec: dict, base: Path) -> str | None:
    if "path" in spec:
        path = base / spec["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        return None
    found = list(base.glob(spec["glob"]))
    if len(found) < int(spec.get("min", 1)):
        raise FileNotFoundError(f"{len(found)} found, {spec.get('min', 1)} needed")
    return f"{len(found)}"


def _sqlite() -> str:
    import sqlite3

    from bayle.adapters.persistence.db import sqlite_problem

    problem = sqlite_problem()
    if problem:
        raise RuntimeError(problem)
    return sqlite3.sqlite_version


def _database(data_dir: Path) -> None:
    from bayle.adapters.persistence import db

    database = db.open_database(data_dir)
    database.close()
