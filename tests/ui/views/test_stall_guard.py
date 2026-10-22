"""The UI-stall watch sees a turn of the event loop that runs too long, with the stack that caused it."""

import sys
import time

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from bayle.ui import stall


def slow_handler():
    time.sleep(0.25)


@pytest.mark.ui_stall_ok
@pytest.mark.skipif(sys.platform != "win32", reason="the offscreen glib dispatcher on Linux does not signal turns")
def test_a_slow_turn_is_reported_with_its_stack(qt_app):
    found = []
    watch = stall.StallWatch(100, lambda ms, stack: found.append((ms, stack)))
    watch.begin()
    loop = QEventLoop()
    QTimer.singleShot(0, slow_handler)
    QTimer.singleShot(400, loop.quit)
    loop.exec()
    watch.end()
    assert found and found[0][0] >= 200
    assert "slow_handler" in found[0][1]


@pytest.mark.ui_stall_ok
def test_the_marker_lets_a_test_block(qt_app):
    time.sleep(0.01)
