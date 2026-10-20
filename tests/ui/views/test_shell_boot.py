"""The shell's start and the updater's watchdog (S9-Shell test T6): the version is reported ready only after Main.qml
and its first page loaded; when either fails, nothing is reported (the watchdog then rolls back) and the fallback
window opens."""

import pytest

from roundtable_souls.platform import instance
from roundtable_souls.ui import self_test
from roundtable_souls.ui.launcher import window
from roundtable_souls.ui.launcher.host import ShellHost
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import inno as migration


class Hold:
    def release(self):
        pass


@pytest.fixture
def boot(qt_app, tmp_path, monkeypatch):
    ready = []
    monkeypatch.setattr(instance, "acquire", lambda name: Hold())
    monkeypatch.setattr(ShellHost, "start_background", lambda self: None)  # no game watch, no update check
    monkeypatch.setattr(updates, "mark_ready", lambda how="window", **k: ready.append(how))
    monkeypatch.setattr(updates, "update_outcome", lambda *a, **k: None)
    monkeypatch.setattr(updates, "clean_downloads", lambda *a, **k: None)
    monkeypatch.setattr(migration, "migrate_from_inno", lambda: {})
    monkeypatch.setattr(window.ShellHost, "shutdown", lambda self: None)
    monkeypatch.setattr(window, "FIRST_PAGE_WAIT", 0.5)
    ctx = self_test._Context(tmp_path, "dark")

    def run():
        from PySide6.QtCore import QEventLoop, QTimer

        loop = QEventLoop()
        QTimer.singleShot(300, loop.quit)  # the after-show tasks run in this time
        loop.exec()
        return 0

    return ctx, ready, run


def test_ready_is_reported_once_after_main_and_the_first_page_loaded(boot):
    ctx, ready, run = boot
    assert window.main(ctx, fallback=lambda c: 9, run=run) == 0
    assert ready == ["window"]


def test_a_shell_that_does_not_load_reports_nothing_and_opens_the_fallback(boot, monkeypatch):
    ctx, ready, run = boot
    monkeypatch.setattr(window.ShellWindow, "build", lambda self: False)
    opened = []
    assert window.main(ctx, fallback=lambda c: opened.append(c) or 9, run=run) == 9
    assert opened == [ctx] and ready == []


def test_a_first_page_that_does_not_show_reports_nothing_either(boot, monkeypatch):
    ctx, ready, run = boot
    monkeypatch.setattr(window.ShellWindow, "page_item", lambda self, name: None)
    assert window.main(ctx, fallback=lambda c: 9, run=run) == 9
    assert ready == []
