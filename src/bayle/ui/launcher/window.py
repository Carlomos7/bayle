"""The shell's window and its boot (technical specification §8.10, §8.6 S9): one QGuiApplication, one
QQmlApplicationEngine with ui/qml as its import path and Main.qml as the window, the bundled fonts, Qt's compiled-QML
cache in the data folder. `ShellWindow` is what the self-test and the tests build; `main()` is the program's entry
once the shell is the app.

Every QML warning the engine reports is kept in `warnings` (the self-test fails on any)."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlError
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from bayle.platform import cpu_pool, instance
from bayle.resources import ASSETS_DIR
from bayle.services.play import TITLE
from bayle.ui import stall
from bayle.ui.branding import app_icon_path
from bayle.ui.launcher.adapter import ShellAdapter
from bayle.ui.launcher.host import ShellHost
from bayle.ui.qml_env import QML_DIR, load_fonts, use_qml_cache_folder

MAIN_QML = QML_DIR / "Main.qml"


class QmlPickers:
    """The file and folder dialogs of Main.qml (Qt Quick's FileDialog and FolderDialog), run with a nested event loop
    so the host's pickers stay synchronous: the page asks and gets the answer."""

    def __init__(self, window: ShellWindow):
        self._w = window

    def _ask(self, name: str, props: dict) -> Path | None:
        win = self._w.window
        dialog: Any = win.findChild(QObject, name) if win is not None else None
        if dialog is None:
            return None
        for key, value in props.items():
            dialog.setProperty(key, value)
        loop = QEventLoop()
        dialog.accepted.connect(loop.quit)
        dialog.rejected.connect(loop.quit)
        dialog.open()
        loop.exec()
        dialog.accepted.disconnect(loop.quit)
        dialog.rejected.disconnect(loop.quit)
        url = dialog.property("selectedFile") or dialog.property("selectedFolder")
        if not isinstance(url, QUrl) or not url.isValid() or not url.toLocalFile():
            return None
        return Path(url.toLocalFile())

    def file(self, title: str, filters: str) -> Path | None:
        return self._ask(
            "openFileDialog", {"title": title, "nameFilters": _qt_filters(filters), "selectedFile": QUrl()}
        )

    def folder(self, title: str) -> Path | None:
        return self._ask("folderDialog", {"title": title, "selectedFolder": QUrl()})

    def save(self, title: str, name: str) -> Path | None:
        return self._ask(
            "saveFileDialog", {"title": title, "selectedFile": QUrl.fromLocalFile(str(Path.home() / name))}
        )


def _qt_filters(filters: str) -> list[str]:
    """ "Mods (*.zip *.7z);;All files (*.*)" as the list FileDialog.nameFilters wants."""
    return [f for f in filters.split(";;") if f] or ["All files (*)"]


class ShellWindow(QObject):
    """The QML shell's window: built hidden, shown when asked."""

    def __init__(self, host: ShellHost, parent: QObject | None = None):
        super().__init__(parent)
        self.host = host
        self.adapter = ShellAdapter(host, self)
        self.engine: QQmlApplicationEngine | None = None
        self.chrome = None  # chrome_win.WindowChrome on Windows
        self.warnings: list[str] = []
        host.pickers = QmlPickers(self)
        self.adapter.quitRequested.connect(self._quit)
        host.appearanceChanged.connect(self.follow_theme)

    @property
    def window(self) -> QQuickWindow | None:
        roots = self.engine.rootObjects() if self.engine is not None else []
        return roots[0] if roots and isinstance(roots[0], QQuickWindow) else None

    def build(self) -> bool:
        """Load Main.qml (hidden); False when it did not load."""
        if self.engine is not None:
            return self.window is not None
        use_qml_cache_folder()  # before the engine compiles anything
        QQuickStyle.setStyle("Basic")
        load_fonts()
        self.engine = QQmlApplicationEngine(self)
        self.engine.addImportPath(str(QML_DIR))
        self.engine.warnings.connect(self._warned)
        self.engine.setInitialProperties({"shell": self.adapter, "visible": False, "winChrome": self.win_chrome()})
        self.follow_theme()
        self.engine.load(QUrl.fromLocalFile(str(MAIN_QML)))
        return self.window is not None

    @staticmethod
    def win_chrome() -> bool:
        """Windows draws its own caption row in the client area (chrome_win); off-screen runs keep the plain window."""
        return sys.platform == "win32" and QGuiApplication.platformName() != "offscreen"

    def _warned(self, errors: list[QQmlError]) -> None:
        self.warnings.extend(e.toString() for e in errors)

    def show(self) -> bool:
        win = self.window if self.build() else None
        if win is None:
            return False
        if self.win_chrome() and self.chrome is None:
            from bayle.ui.launcher.chrome_win import WindowChrome

            self.chrome = WindowChrome(win)
            self.chrome.install()
        win.sceneGraphInitialized.connect(lambda: self._log_backend(win))
        win.show()
        win.raise_()
        win.requestActivate()
        return True

    @staticmethod
    def _log_backend(win: QQuickWindow) -> None:
        """The render backend in the log (a GPU one in normal runs; Software only in offscreen tests)."""
        from bayle.platform import logging as run_logging

        api = win.rendererInterface().graphicsApi()
        run_logging.log_shown(f"render backend: {api.name.lower()}")

    def bring_forward(self) -> None:
        win = self.window
        if win is not None:
            if win.visibility() == QWindow.Visibility.Minimized:
                win.showNormal()
            win.show()
            win.raise_()
            win.requestActivate()

    def page_item(self, name: str) -> QObject | None:
        """A page's root item once loaded (tests and the self-test); pages live in Loaders, so the item tree is
        walked."""
        win = self.window
        if win is None:
            return None
        want = f"{name}Page"
        todo = [win.contentItem()]
        while todo:
            item = todo.pop()
            try:
                if item.objectName() == want:
                    return item
                todo.extend(item.childItems())
            except RuntimeError:  # an item that went away while looking
                continue
        return None

    def follow_theme(self) -> None:
        """The OS window frame (title bar, caption glyphs) follows the app's theme, not only the system's: dark and
        light are forced, System follows Windows again."""
        from PySide6.QtCore import Qt

        hints = QGuiApplication.styleHints()
        theme = self.host.state.settings.theme
        scheme = {"light": Qt.ColorScheme.Light, "system": Qt.ColorScheme.Unknown}.get(theme, Qt.ColorScheme.Dark)
        if hints is not None and hints.colorScheme() != scheme:
            hints.setColorScheme(scheme)
        dark = hints is None or hints.colorScheme() != Qt.ColorScheme.Light
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            app.setWindowIcon(QIcon(str(app_icon_path(dark, self.host.state.settings.logo))))

    def _quit(self) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            app.quit()

    def dispose(self) -> None:
        """Close the window and free it: the QML first, then its engine (the host outlives both)."""
        if self.chrome is not None:
            self.chrome.remove()
            self.chrome = None
        win = self.window
        if win is not None:
            win.close()
            win.deleteLater()
        if self.engine is not None:
            self.engine.deleteLater()
            self.engine = None


FIRST_PAGE_WAIT = 3.0  # seconds the shell has to show Main.qml and its first page before it counts as failed


def main(engine, run: Callable[[], int] | None = None) -> int:
    """The program with the QML shell as its window (engine: runtime.bootstrap.create_engine). Returns the exit code; 0 when a running
    launcher was asked to come forward instead. If Main.qml or the first page does not load, the reason is logged,
    and the version is NOT reported ready (an update's watchdog then rolls back a build that never gets there).
    run: the event loop (tests give their own)."""
    import threading

    from bayle.config import identity
    from bayle.platform import logging as run_logging
    from bayle.services.play import report_exception

    if identity.get().display_platform:  # an isolated test build (Velopack starts it with the user's own environment)
        os.environ["QT_QPA_PLATFORM"] = identity.get().display_platform
    app = cast(QGuiApplication, QGuiApplication.instance() or QGuiApplication(sys.argv))
    app.setApplicationName(TITLE)
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "app-crimson.png")))  # the window follows the chosen logo from then on
    hold = instance.acquire(instance.WINDOW)
    if hold is None and instance.send("show"):
        return 0  # the open window came forward
    deadline = time.monotonic() + 5
    while hold is None and time.monotonic() < deadline:  # a window closing for an update hand-off
        time.sleep(0.25)
        hold = instance.acquire(instance.WINDOW)
    if hold is None:
        sys.stderr.write(f"{TITLE} is already open but does not answer. Close it, then start it again.\n")
        return 1
    sys.excepthook = lambda t, e, tb: report_exception(t, e, tb, "main thread")
    threading.excepthook = lambda a: report_exception(
        a.exc_type, a.exc_value, a.exc_traceback, f"thread {a.thread.name}"
    )
    pool = cpu_pool.CpuPool()  # CPU-bound work runs in worker processes (platform/cpu.py)
    engine.use_cpu(pool.submit, pool.broadcast, threading.get_ident())
    QGuiApplication.instance().aboutToQuit.connect(pool.shutdown)
    host = ShellHost(engine)
    window = ShellWindow(host)
    window.adapter.forwardRequested.connect(window.bring_forward)
    first = host.state.game.ready and "mods" or "placeholder"
    shown = window.show()
    end = time.monotonic() + FIRST_PAGE_WAIT
    while shown and window.page_item(first) is None and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)
    if not shown or window.page_item(first) is None:
        run_logging.log(
            "error: the new interface did not load: " + ("; ".join(window.warnings) or "its first page did not show")
        )
        window.dispose()
        hold.release()
        return 1
    host.instance.take(hold)
    stalls = stall.log_stalls(run_logging.get_logger("ui"))
    host.start_background()
    QTimer.singleShot(0, host.after_show)  # marks the version ready, reports the last update, starts the imports
    code = (run or app.exec)()
    stalls.end()
    if host.shutdown() is False:  # a job is still running: it is journaled and recovered at the next start
        import logging

        logging.shutdown()
        os._exit(int(code))
    return int(code)
