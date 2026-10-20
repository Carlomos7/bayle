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
from typing import Any

from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QIcon, QWindow
from PySide6.QtQml import QQmlApplicationEngine, QQmlError
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from roundtable_souls.platform import instance
from roundtable_souls.resources import ASSETS_DIR
from roundtable_souls.services.play import TITLE
from roundtable_souls.ui.launcher.adapter import ShellAdapter
from roundtable_souls.ui.launcher.host import ShellHost
from roundtable_souls.ui.page_window import QML_DIR, load_fonts, use_qml_cache_folder

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
        self.engine.setInitialProperties({"shell": self.adapter, "visible": False})
        self.follow_theme()
        self.engine.load(QUrl.fromLocalFile(str(MAIN_QML)))
        return self.window is not None

    def _warned(self, errors: list[QQmlError]) -> None:
        self.warnings.extend(e.toString() for e in errors)

    def show(self) -> bool:
        win = self.window if self.build() else None
        if win is None:
            return False
        win.show()
        win.raise_()
        win.requestActivate()
        return True

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

    def _quit(self) -> None:
        app = QGuiApplication.instance()
        if app is not None:
            app.quit()

    def dispose(self) -> None:
        """Close the window and free it: the QML first, then its engine (the host outlives both)."""
        win = self.window
        if win is not None:
            win.close()
            win.deleteLater()
        if self.engine is not None:
            self.engine.deleteLater()
            self.engine = None


FIRST_PAGE_WAIT = 3.0  # seconds the shell has to show Main.qml and its first page before it counts as failed


def main(ctx, fallback: Callable[[object], int] | None = None) -> int:
    """The program with the QML shell as its window (ctx: app.create_app). Returns the exit code; 0 when a running
    launcher was asked to come forward instead. If Main.qml or the first page does not load, the reason is logged,
    the version is NOT reported ready (an update's watchdog then rolls back a build that never gets there), and
    `fallback(ctx)` (the Widgets window, while it exists) opens instead."""
    import threading

    from roundtable_souls.config import identity
    from roundtable_souls.platform import logging as run_logging
    from roundtable_souls.services.play import report_exception

    if identity.get().qt_platform:  # an isolated test build (Velopack starts it with the user's own environment)
        os.environ["QT_QPA_PLATFORM"] = identity.get().qt_platform
    app = QApplication.instance() or QApplication(sys.argv)  # Widgets only while the fallback window exists
    assert isinstance(app, QApplication)
    app.setApplicationName(TITLE)
    app.setWindowIcon(QIcon(str(ASSETS_DIR / "icon.ico")))
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
    host = ShellHost(ctx)
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
        if fallback is not None:
            return int(fallback(ctx) or 0)
        return 1
    host.instance.take(hold)
    host.start_background()
    QTimer.singleShot(0, host.after_show)  # marks the version ready, reports the last update, starts the imports
    code = app.exec()
    host.shutdown()
    return int(code)
