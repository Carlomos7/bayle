"""The one window-chrome row lays out: menus left, the title centred, minimise/maximise/close right, level with the menus."""

import pytest

from roundtable_souls.ui import self_test
from roundtable_souls.ui.launcher.host import ShellHost
from roundtable_souls.ui.launcher.window import ShellWindow

# known stall: a whole shell or the Mods rows (every delegate built in one model reset, see perf/ui-thread.md) is built in one turn
pytestmark = pytest.mark.ui_stall_ok


def _find(win, name):
    todo = [win.contentItem()]
    while todo:
        item = todo.pop()
        if item.objectName() == name:
            return item
        todo.extend(item.childItems())
    return None


def _box(item):
    p = item.mapToScene(item.boundingRect().topLeft())
    return p.x(), p.y(), item.width(), item.height()


def test_the_row_has_menus_left_title_centred_and_buttons_right(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(ShellHost, "me3_facts", lambda self: {})
    w = ShellWindow(ShellHost(self_test._Context(tmp_path, "dark")))  # type: ignore[arg-type]
    try:
        assert w.build() and w.window is not None
        w.window.resize(1100, 760)
        w.window.show()
        qt_app.processEvents()
        row, menus = _box(_find(w.window, "chromeRow")), _box(_find(w.window, "chromeMenus"))
        mn, mx, cl = (_box(_find(w.window, f"chrome{n}")) for n in ("Min", "Max", "Close"))
        title = _box(_find(w.window, "chromeTitle"))
        assert menus[0] < 40 and title[0] > menus[0] + menus[2]
        assert abs((title[0] + title[2] / 2) - row[2] / 2) <= 1, "the title is centred"
        assert mn[0] < mx[0] < cl[0] and cl[0] + cl[2] == pytest.approx(row[2])
        assert title[0] + title[2] <= mn[0]
        for b in (mn, mx, cl):
            assert b[1] == row[1] and b[3] == row[3], "the buttons span the row, level with the menus"
    finally:
        w.dispose()
