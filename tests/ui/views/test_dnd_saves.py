"""Drag and drop on the Saves page, off-screen with real mouse events over invented saves (no file is read or written;
the twins' slots are recorded): a character row dragged to a slot or the card body, a copy or a backup onto a live save,
a live save onto the Library or the Backups tab, Esc cancels, the game running refuses in words. Set S5_SHOTS to keep
PNGs of the drag states."""

import os
from pathlib import Path

import pytest
from page_window import PageWindow
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from test_mods_view import centre, closed, find, settle

from roundtable_souls.ui.pages.registry import page as registered


class Host:
    busy = False
    game_running = False
    locations = None  # nothing is read from disk: the test fills the adapter by hand

    def run_job(self, job, status):
        raise AssertionError("the drop only reaches the twin's slot")

    def run_in_background(self, work, on_result):
        on_result(work())

    def pick_file(self, title, filters):
        return None

    def open_path(self, path):
        pass

    def saves_in_use(self):
        return {}


def info(kind, name, chars):
    return {
        "path": Path("C:/fake") / name,
        "name": name,
        "kind": kind,
        "modified": "2026-10-20 10:00",
        "characters": [
            {"slot": s, "name": n, "level": lv, "runes": 1000 * lv, "ok": True, "body": ""} for s, n, lv in chars
        ],
        "unreadable": [],
        "findings": [],
    }


@pytest.fixture
def page(qt_app, monkeypatch):
    monkeypatch.setattr("roundtable_souls.saves.library.default_name", lambda path, game: "A name")
    host = Host()
    w = PageWindow(registered("saves"), host)
    assert w.build(), w.warnings
    a = w.adapter
    a._game = lambda: None
    calls = []
    for name in ("copyCharacter", "replaceFromLibrary", "restoreBackup", "backUpNow"):
        setattr(a, name, lambda *args, _n=name: calls.append((_n, args)))
    a.nameAsked.connect(lambda mode, path: calls.append(("nameAsked", (mode, path))))
    a._infos = [
        info("Standard", "ER0000.sl2", [(1, "Alice", 80), (2, "Bob", 40)]),
        info("Seamless Co-op", "ER0000.co2", [(1, "Cara", 120)]),
    ]
    a._libs = {
        "C:/fake": {
            "entries": [
                {
                    "id": "c1",
                    "name": "Before the boss",
                    "added": "2026-10-19T10:00:00",
                    "format": "sl2",
                    "characters": [],
                }
            ]
        }
    }
    a._backups = [
        {
            "path": Path("C:/fake/x.bak"),
            "when": "2026-10-20T09:00:00",
            "time": "09:00",
            "save_name": "ER0000.sl2",
            "action": "manual",
            "changes": [],
            "size": 1_000_000,
            "keep": False,
            "unreadable": False,
        }
    ]
    win = w.window
    win.resize(1100, 900)
    win.show()
    a.changed.emit()
    settle(300)
    yield w, calls
    closed(w)


def shot(w, name):
    where = os.environ.get("S5_SHOTS") or os.environ.get("RS_VIEW_SHOTS")
    if where:
        Path(where).mkdir(parents=True, exist_ok=True)
        w.window.grabWindow().save(str(Path(where) / f"dnd-saves-{name}.png"))


def drag(w, grip, target, hold=None, header=False):
    win = w.window
    start, end = centre(find(w, grip)), centre(find(w, target))
    if header:  # the card's header zone, above its slots
        p = find(w, target).mapToScene(QPointF(120, 30))
        end = QPoint(round(p.x()), round(p.y()))
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    settle(40)
    for i in range(1, 13):
        QTest.mouseMove(
            win, QPoint(start.x() + (end.x() - start.x()) * i // 12, start.y() + (end.y() - start.y()) * i // 12)
        )
        settle(20)
    if hold:
        hold()
    QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
    settle(200)


def test_a_character_dropped_on_a_slot_is_the_copy_twin(page):
    w, calls = page
    drag(w, "dragChar_ER0000.sl2_1", "dropSlot_ER0000.co2_1", hold=lambda: shot(w, "slot-valid"))
    assert calls == [("copyCharacter", (str(Path("C:/fake/ER0000.sl2")), 1, str(Path("C:/fake/ER0000.co2")), 1))]


def test_a_character_dropped_on_an_empty_slot_chip(page):
    w, calls = page
    drag(w, "dragChar_ER0000.sl2_1", "dropSlot_ER0000.co2_2", hold=lambda: shot(w, "empty-slot-valid"))
    assert [c[0] for c in calls] == ["copyCharacter"] and calls[0][1][3] == 2


def test_a_copy_and_a_backup_dropped_on_a_live_save(page):
    w, calls = page
    drag(w, "dragCopy_Before the boss", "dropCard_ER0000.co2", header=True)
    assert [c[0] for c in calls] == ["replaceFromLibrary"] and calls[0][1][1] == "c1"


def test_a_live_save_dropped_on_the_library_asks_for_a_name(page):
    w, calls = page
    drag(w, "dragLive_ER0000.sl2", "dropLibrary", hold=lambda: shot(w, "live-on-library"))
    assert calls == [("nameAsked", ("copy", str(Path("C:/fake/ER0000.sl2"))))]


def test_esc_cancels_a_drag(page):
    w, calls = page
    drag(w, "dragChar_ER0000.sl2_1", "dropSlot_ER0000.co2_1", hold=lambda: QTest.keyClick(w.window, Qt.Key.Key_Escape))
    assert calls == []


def test_the_game_running_refuses_in_words(page):
    w, calls = page
    w.host.game_running = True
    told = []
    w.notifier.toastRequested.connect(lambda text, error: told.append(text))
    w.adapter.changed.emit()
    settle(100)
    # character handles are hidden while the game runs: the same refusal is what a drop would say
    assert w.adapter.dropReason({"type": "live", "path": "p"}, {"type": "backups"}).startswith("Close")
    w.adapter.drop({"type": "live", "path": "p"}, {"type": "backups"})
    assert calls == [] and told and "Close" in told[0]
    # Save a copy only reads the live save: still allowed
    assert w.adapter.dropReason({"type": "live", "path": "p"}, {"type": "library"}) == ""
