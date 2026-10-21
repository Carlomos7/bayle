"""--self-test (technical specification §8.5): proves that a build, as packaged, starts and initializes: the modules,
data and QML the bundler had to collect are there, the database opens at the current schema, and the shell loads
with every registered page in every theme with no QML warning. It runs off-screen in a temporary data folder
(cli.py points ROUNDTABLE_SOULS_DATA there before anything else runs) over an empty context: nothing of the user's
is read or written, no game or me3 is started, no update feed is contacted.

What it does not verify: visual correctness, behaviour against a real game, saves or me3, or native integration
(window manager, high-DPI, file dialogs, shortcuts, the installer, the updater). It covers the QML shell (Main.qml
with every registered page in every theme at 740 and 1100 px).

One line per check, then a summary; exit code 0 only when every check passed."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from roundtable_souls.platform import cpu
from roundtable_souls.resources import DATA_DIR, PACKAGE_DIR

THEMES = ("dark", "tarnished", "light")
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


def requirements() -> dict:
    return json.loads(LIST_FILE.read_text(encoding="utf-8"))


def run(data_dir: Path, out: Callable[[str], None] = print) -> int:
    """All checks; 0 when every one passed."""
    report = Report(out)
    out(f"Roundtable Souls self-test, data folder {data_dir}")
    report.check("isolated data folder", lambda: _isolated(data_dir))
    try:
        need = requirements()
    except (OSError, ValueError) as e:
        problem = e
        report.check("the self-test list", lambda: _raise(problem))
        need = {"python_modules": [], "qml_modules": [], "files": []}
    for name in need["python_modules"]:
        report.check(f"module {name}", lambda name=name: _import(name))
    for spec in need["files"]:
        report.check(f"file {spec.get('path') or spec.get('glob')}", lambda spec=spec: _files(spec))
    report.check("SQLite version", _sqlite)
    report.check("database opens at the current schema", lambda: _database(data_dir))
    report.check("a CPU worker process starts and answers", _worker)
    _qml(report, need["qml_modules"], data_dir)
    out(f"{report.passed} passed, {report.failed} failed")
    out(
        "Limits: packaging and initialization only; not visual correctness, real games, saves or me3, native "
        "integration, the installer or the updater."
    )
    return 1 if report.failed else 0


def _worker() -> str:
    """The build starts itself again with --worker (platform/cpu.py) and gets an answer, without Qt in the worker."""
    import subprocess

    request = json.dumps({"id": 1, "task": "roundtable_souls.platform.cpu:probe", "args": {"value": 41}}) + "\n"
    done = subprocess.run(cpu.worker_command(), input=request.encode(), capture_output=True, timeout=120, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"the worker exited with {done.returncode}: {done.stderr.decode(errors='replace')[-300:]}")
    reply = json.loads(done.stdout.decode().splitlines()[-1])
    if not reply.get("ok") or reply["result"]["value"] != 42:
        raise RuntimeError(f"unexpected reply {reply}")
    if reply["result"]["qt"]:
        raise RuntimeError("the worker loaded Qt")
    return f"pid {reply['result']['pid']}"


def _raise(e: Exception):
    raise e


def _isolated(data_dir: Path) -> str:
    from roundtable_souls.config.settings import data_dir as settings_data_dir

    data_dir = data_dir.resolve()
    if Path(os.environ.get("ROUNDTABLE_SOULS_DATA", "")).resolve() != data_dir or settings_data_dir() != data_dir:
        raise RuntimeError(f"the data folder is {settings_data_dir()}, not the temporary {data_dir}")
    return str(data_dir)


def _import(name: str) -> None:
    importlib.import_module(name)


def _files(spec: dict) -> str | None:
    if "path" in spec:
        path = PACKAGE_DIR / spec["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        return None
    found = list(PACKAGE_DIR.glob(spec["glob"]))
    if len(found) < int(spec.get("min", 1)):
        raise FileNotFoundError(f"{len(found)} found, {spec.get('min', 1)} needed")
    return f"{len(found)}"


def _sqlite() -> str:
    import sqlite3

    from roundtable_souls.storage.db import sqlite_problem

    problem = sqlite_problem()
    if problem:
        raise RuntimeError(problem)
    return sqlite3.sqlite_version


def _database(data_dir: Path) -> None:
    from roundtable_souls.storage import db

    database = db.open_database(data_dir)
    database.close()


def _qml(report: Report, modules: list[str], data_dir: Path) -> None:
    """The QML modules import, and the shell loads with every registered page in every theme with no warning."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    from roundtable_souls.ui.qml_env import use_qml_cache_folder

    cache = use_qml_cache_folder()  # before the first engine: Qt's compiled QML stays in the temporary data folder
    if QCoreApplication.instance() is None:
        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    app = QGuiApplication.instance() or QGuiApplication([])
    for name in modules:
        report.check(f"QML module {name}", lambda name=name: _qml_module(name))

    def cache_stays_in_the_data_folder() -> str:
        if os.environ.get("QML_DISABLE_DISK_CACHE"):
            return "the disk cache is off for this run"
        if cache is None or not any(cache.glob("*.qmlc")):
            raise RuntimeError(f"no compiled QML in {cache}: Qt's cache went somewhere else")
        return str(cache)

    _shell(report, app, data_dir)

    report.check("QML cache in the temporary data folder", cache_stays_in_the_data_folder)


class _Context:
    """The app context of the shell checks: no database, no real profile or save folder (the temporary data folder's
    own empty ones), the settings in memory."""

    def __init__(self, data_dir: Path, theme: str):
        from roundtable_souls.config.settings import LauncherSettings
        from roundtable_souls.game import catalog
        from roundtable_souls.game.locate import Locations

        (data_dir / "profiles").mkdir(exist_ok=True)
        (data_dir / "saves").mkdir(exist_ok=True)
        self.data_dir = data_dir
        self.settings = LauncherSettings(
            theme=theme,  # type: ignore[arg-type]
            me3_profile_dir=str(data_dir / "profiles"),
            saves_dir=str(data_dir / "saves"),
            tips_seen=["launch", "rail"],
        )
        self.game = catalog.ELDEN_RING
        self.locations = Locations.from_settings(self.settings, self.game)

    def select_game(self, game):
        from roundtable_souls.game.locate import Locations

        self.game = game
        self.locations = Locations.from_settings(self.settings, game)
        return self.locations

    def note_profile_saves(self, names):
        return self.locations

    def reload_settings(self):
        return self.settings

    def start_imports(self):
        return None


def _settle(ms: int) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _shell(report: Report, app, data_dir: Path) -> None:
    """The QML shell: Main.qml loads in every theme at the narrow and the wide size, and every registered page loads
    in it, with no QML warning."""
    from roundtable_souls.ui.launcher.host import ShellHost
    from roundtable_souls.ui.launcher.window import ShellWindow
    from roundtable_souls.ui.pages.registry import QML_PAGES

    for theme in THEMES:
        for width in (740, 1100):

            def shell(theme=theme, width=width) -> None:
                host = ShellHost(_Context(data_dir, theme))  # type: ignore[arg-type]
                w = ShellWindow(host)
                try:
                    if not w.build() or w.window is None:
                        raise RuntimeError("Main.qml did not load: " + "; ".join(w.warnings))
                    w.window.resize(width, 760)
                    w.window.show()
                    for entry in QML_PAGES:
                        w.adapter.open_page(entry.name)
                        _settle(200)
                        if w.page_item(entry.name) is None:
                            raise RuntimeError(f"page {entry.name} did not load: " + "; ".join(w.warnings))
                    if w.warnings:
                        raise RuntimeError(f"{len(w.warnings)} QML warning(s): " + "; ".join(w.warnings))
                finally:
                    w.dispose()
                    app.processEvents()

            report.check(f"shell in the {theme} theme at {width} px, every page", shell)


def _qml_module(name: str) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from roundtable_souls.ui.qml_env import QML_DIR

    engine = QQmlEngine()
    engine.addImportPath(str(QML_DIR))
    component = QQmlComponent(engine)
    component.setData(f"import QtQuick\nimport {name}\nQtObject {{}}\n".encode(), QML_DIR.as_uri() + "/probe.qml")
    if component.isError():
        raise RuntimeError("; ".join(e.toString() for e in component.errors()))
    obj = component.create()
    if obj is None:
        raise RuntimeError("; ".join(e.toString() for e in component.errors()) or "it did not instantiate")
