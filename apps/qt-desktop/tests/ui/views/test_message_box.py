"""The one-shot message window of cli.py (a failed start, a Play that did not start): it loads with no QML warning
and a closed window answers -1; a button press answers its index."""

import pytest
from PySide6.QtCore import QMetaObject, QTimer
from PySide6.QtGui import QGuiApplication

from bayle_qt import message_box


def _poke(action) -> None:
    def run():
        win = next(w for w in QGuiApplication.topLevelWindows() if w.isVisible())
        action(win)

    QTimer.singleShot(400, run)


def test_closing_the_window_answers_minus_one(qt_app):
    _poke(lambda win: win.close())
    assert message_box.ask("Heading", "Detail", ("Open", "Close")) == -1


@pytest.mark.parametrize("index", [0, 1])
def test_a_button_answers_its_index(qt_app, index):
    from PySide6.QtCore import Q_ARG

    _poke(lambda win: QMetaObject.invokeMethod(win, "pick", Q_ARG("QVariant", index)))
    assert message_box.ask("Heading", "", ("Open", "Close")) == index
