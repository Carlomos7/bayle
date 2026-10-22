"""A registered QML page in a top-level window of its own, for the off-screen view tests: its own engine over ui/qml,
the page's adapter and Notifier, and tests/ui/views/PageWindow.qml around the page (bar, InfoBar, toasts, confirm).
Every QML warning the engine reports is kept in `warnings`; the tests fail on any."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine, QQmlError
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from bayle.ui.notifications import Notifier
from bayle.ui.pages.registry import QmlPage
from bayle.ui.qml_env import QML_DIR, load_fonts, use_qml_cache_folder

WINDOW_QML = Path(__file__).resolve().parent / "PageWindow.qml"


def theme_mode(setting: str) -> str:
    return setting if setting in ("dark", "light", "tarnished", "system") else "dark"


class PageWindow(QObject):
    """The window for one registered page. show() builds it the first time and brings it forward after that."""

    def __init__(
        self,
        entry: QmlPage,
        host,
        theme: str = "dark",
        parent: QObject | None = None,
        effects: str = "full",
        grain: str = "subtle",
    ):
        super().__init__(parent)
        self.entry = entry
        self.host = host
        self.theme = theme_mode(theme)
        self.effects, self.grain = effects, grain
        self.notifier = Notifier(self)
        self.adapter = entry.make_adapter(host, self.notifier)
        if isinstance(self.adapter, QObject) and self.adapter.parent() is None:
            self.adapter.setParent(self)  # it lives as long as the window that binds to it
        self.engine: QQmlApplicationEngine | None = None
        self.warnings: list[str] = []

    @property
    def window(self) -> QQuickWindow | None:
        roots = self.engine.rootObjects() if self.engine is not None else []
        return roots[0] if roots and isinstance(roots[0], QQuickWindow) else None

    def build(self) -> bool:
        """Load the window's QML (hidden); False when it did not load."""
        if self.engine is not None:
            return self.window is not None
        use_qml_cache_folder()  # before the engine compiles anything
        QQuickStyle.setStyle("Basic")
        load_fonts()
        self.engine = QQmlApplicationEngine(self)
        self.engine.addImportPath(str(QML_DIR))
        self.engine.warnings.connect(self._warned)
        self.engine.setInitialProperties(
            {
                "adapter": self.adapter,
                "notifier": self.notifier,
                "pageUrl": QUrl.fromLocalFile(str(QML_DIR / self.entry.qml)),
                "themeMode": self.theme,
                "effects": self.effects,
                "grain": self.grain,
                "visible": False,
            }
        )
        self.engine.load(QUrl.fromLocalFile(str(WINDOW_QML)))
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

    def set_theme(self, theme: str) -> None:
        self.theme = theme_mode(theme)
        if self.window is not None:
            self.window.setProperty("themeMode", self.theme)

    def set_appearance(self, theme: str, effects: str, grain: str) -> None:
        """Settings > Appearance, applied live."""
        self.set_theme(theme)
        self.effects, self.grain = effects, grain
        if self.window is not None:
            self.window.setProperty("effects", effects)
            self.window.setProperty("grain", grain)

    def page_item(self):
        """The page's root item once loaded (tests and the self-test)."""
        win = self.window
        return win.findChild(QObject, f"{self.entry.name}Page") if win is not None else None

    def close(self) -> None:
        win = self.window
        if win is not None:
            win.close()

    def dispose(self) -> None:
        """Close the window and free it: the QML first, then its engine (the adapter outlives both)."""
        win = self.window
        if win is not None:
            win.close()
            win.deleteLater()
        self.notifier.drop_pending()
        if self.engine is not None:
            self.engine.deleteLater()
            self.engine = None
