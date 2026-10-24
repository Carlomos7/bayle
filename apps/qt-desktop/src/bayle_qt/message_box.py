"""A small message window for the places with no launcher around them (cli.py: a start that failed, a Steam
shortcut's Play that did not start). One-shot Qt Quick window (qml/MessageWindow.qml); `ask` waits for the answer."""

from __future__ import annotations

import sys

from PySide6.QtCore import QEventLoop, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from bayle_qt.qml_env import QML_DIR, load_fonts, use_qml_cache_folder


def ask(heading: str, detail: str = "", buttons: tuple[str, ...] = ("OK",)) -> int:
    """Show the message and wait: the index of the button pressed (the first is the primary one), -1 when the window
    was closed. Raises when there is no display or the window does not load; callers log that."""
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    use_qml_cache_folder()
    QQuickStyle.setStyle("Basic")
    load_fonts()
    engine = QQmlApplicationEngine()
    engine.addImportPath(str(QML_DIR))
    engine.setInitialProperties({"heading": heading, "detail": detail, "buttons": list(buttons)})
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "MessageWindow.qml")))
    roots = engine.rootObjects()
    if not roots or not isinstance(roots[0], QQuickWindow):
        raise RuntimeError("the message window did not load")
    win = roots[0]
    answer: list[int] = [-1]
    loop = QEventLoop()
    answered = win.answered  # pyright: ignore[reportAttributeAccessIssue]  # a signal declared in MessageWindow.qml
    answered.connect(lambda index: (answer.__setitem__(0, index), loop.quit()))
    win.show()
    win.raise_()
    win.requestActivate()
    loop.exec()
    del app
    return answer[0]
