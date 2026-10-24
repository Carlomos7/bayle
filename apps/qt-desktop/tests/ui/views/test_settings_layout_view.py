"""The Settings page's Locations section renders the profiles folder and the Folder names under More, off-screen."""

import os
from pathlib import Path

from bayle.services.settings import SettingsService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from page_window import PageWindow
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from bayle_qt.pages.registry import QmlPage
from bayle_qt.pages.settings.adapter import SettingsAdapter


class SettingsHost:
    busy = False

    def __init__(self):
        self.job_manager = JobManager(EventBus())
        self.settings_service = SettingsService(self.job_manager, lambda: None)

    def run_job(self, job, status, on_done=None):
        pass

    def run_in_background(self, work, on_result):
        on_result(work())

    def settings_changed(self, key):
        pass

    def update_state(self):
        return {"line": "", "tone": "muted", "notices": []}

    def watch_updates(self, call):
        pass

    def me3_facts(self):
        return {}

    def pick_folder(self, title):
        return None


def settle(ms=80):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QGuiApplication.processEvents()


def find(w, name):
    todo = [w.window.contentItem()]
    while todo:
        item = todo.pop()
        if item.objectName() == name:
            return item
        todo.extend(item.childItems())
    raise AssertionError(f"no item named {name}")


def test_locations_show_the_profiles_folder_and_the_folder_names_open_under_more(qt_app, shots):
    entry = QmlPage("settings", "Pages/SettingsPage.qml", lambda host, n: SettingsAdapter(host, n))
    w = PageWindow(entry, SettingsHost(), "dark")
    assert w.build(), w.warnings
    win = w.window
    win.resize(1100, 900)
    win.show()
    settle(300)
    try:
        assert find(w, "profilesFolderRow").isVisible()
        assert find(w, "changeProfilesFolder").isVisible() and find(w, "moveAll").isVisible()
        assert not find(w, "nameRow_pattern").isVisible()
        w.adapter.editLayout("pattern", "oops")  # no {game}: the row shows the problem and Apply stays off
        assert not w.adapter.layoutValid
        w.adapter.editLayout("pattern", "x-{game}")
        assert w.adapter.layoutValid and w.adapter.layoutDirty and w.adapter.gamePreview == "x-eldenring"
        btn = find(w, "moreButton")
        p = btn.mapToScene(btn.boundingRect().center())
        QTest.mouseClick(
            win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(p.x()), round(p.y()))
        )
        settle(200)
        assert find(w, "nameRow_pattern").isVisible() and find(w, "applyLayout").isVisible()
        out = Path(os.environ.get("S5_SHOTS") or shots)
        win.grabWindow().save(str(out / "settings-locations.png"))
        assert w.warnings == []
    finally:
        w.dispose()
