"""The Qt half of --self-test (see bayle.diagnostics for the engine half and what the whole run covers): the QML
modules import, and the shell loads with every registered page in every theme at 740 and 1100 px with no QML
warning. The list of what a build must contain for the window is ui/self-test.json."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from bayle import diagnostics
from bayle.diagnostics import Report
from bayle.resources import PACKAGE_DIR

THEMES = ("dark", "tarnished", "light")
LIST_FILE = PACKAGE_DIR / "ui" / "self-test.json"


def requirements() -> dict:
    return diagnostics.requirements(LIST_FILE)


def run(data_dir: Path, out: Callable[[str], None] = print) -> int:
    """The whole self-test: the engine checks, then these."""
    return diagnostics.run(data_dir, out, qt=checks)


def checks(report: Report, data_dir: Path) -> None:
    try:
        need = requirements()
    except (OSError, ValueError) as e:
        problem = e
        report.check("the Qt self-test list", lambda: _raise(problem))
        need = {"python_modules": [], "qml_modules": [], "files": []}
    diagnostics.run_list(report, need)
    _qml(report, need["qml_modules"], data_dir)


def _raise(e: Exception):
    raise e


def _qml(report: Report, modules: list[str], data_dir: Path) -> None:
    """The QML modules import, and the shell loads with every registered page in every theme with no warning."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

    from bayle.ui.qml_env import use_qml_cache_folder

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
        from bayle.config.settings import LauncherSettings, save_settings
        from bayle.game import catalog
        from bayle.game.locate import Locations
        from bayle.work.events import EventBus
        from bayle.work.jobs import JobManager

        (data_dir / "profiles").mkdir(exist_ok=True)
        (data_dir / "saves").mkdir(exist_ok=True)
        self.data_dir = data_dir
        # no network from a self-test: a release check could still be writing when the temporary folder is removed
        save_settings(check_me3_updates=False, check_launcher_updates=False)
        self.settings = LauncherSettings(
            theme=theme,  # type: ignore[arg-type]
            me3_profile_dir=str(data_dir / "profiles"),
            saves_dir=str(data_dir / "saves"),
            tips_seen=["launch", "rail"],
        )
        self.game = catalog.ELDEN_RING
        self.locations = Locations.from_settings(self.settings, self.game)
        self.jobs = JobManager(EventBus())
        self.activity = None  # no database: the records are in jobs.jsonl

    def startup(self, profile):
        from bayle.session.startup import recovery_steps

        return recovery_steps(lambda: self.locations, profile)

    def select_game(self, game):
        from bayle.game.locate import Locations

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
    from bayle.ui.launcher.host import ShellHost
    from bayle.ui.launcher.window import ShellWindow
    from bayle.ui.pages.registry import QML_PAGES

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
                    host.shutdown()  # background reads (the Settings page's me3 facts) end before the folder goes
                    app.processEvents()

            report.check(f"shell in the {theme} theme at {width} px, every page", shell)


def _qml_module(name: str) -> None:
    from PySide6.QtQml import QQmlComponent, QQmlEngine

    from bayle.ui.qml_env import QML_DIR

    engine = QQmlEngine()
    engine.addImportPath(str(QML_DIR))
    component = QQmlComponent(engine)
    component.setData(f"import QtQuick\nimport {name}\nQtObject {{}}\n".encode(), QML_DIR.as_uri() + "/probe.qml")
    if component.isError():
        raise RuntimeError("; ".join(e.toString() for e in component.errors()))
    obj = component.create()
    if obj is None:
        raise RuntimeError("; ".join(e.toString() for e in component.errors()) or "it did not instantiate")
