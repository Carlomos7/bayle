"""Check for updates always answers: the line changes and a toast reaches a Notifier the shell's Overlays listen to."""

import time

import pytest
from PySide6.QtCore import QCoreApplication

from roundtable_souls.ui import self_test
from roundtable_souls.ui.launcher import updates as updates_mod
from roundtable_souls.ui.launcher.adapter import ShellAdapter
from roundtable_souls.ui.launcher.host import ShellHost
from roundtable_souls.updates import feed


def _wait(cond):
    end = time.time() + 5
    while not cond() and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert cond()


@pytest.mark.parametrize(
    "check,error",
    [
        (feed.UpdateCheck("fresh"), False),
        (feed.UpdateCheck("offline", reason="No network"), True),
        (feed.UpdateCheck("fresh", offer={"version": "99.0.0", "url": "u", "assets": {}, "notes": ""}), False),
    ],
)
def test_a_forced_check_shows_a_line_and_a_toast_on_a_listened_notifier(qt_app, tmp_path, monkeypatch, check, error):
    monkeypatch.setattr(updates_mod.feed, "check_launcher_update", lambda force=False: check)
    monkeypatch.setattr(updates_mod.feed, "check_advisory", lambda force=False: None)
    host = ShellHost(self_test._Context(tmp_path, "dark"))  # type: ignore[arg-type]
    shell = ShellAdapter(host)
    seen = []
    for n in shell._all_notifiers():
        n.toastRequested.connect(lambda text, is_error: seen.append((text, is_error)))
    lines = []
    host.watch_updates(lambda: lines.append(host.update_state()["line"]))
    host.check_for_updates()
    assert host.update_state()["line"].startswith("Checking")  # at once, before the answer
    _wait(lambda: len(lines) >= 1 and seen)
    assert lines[-1] and not lines[-1].startswith("Checking")
    assert seen[-1][1] is error and seen[-1][0]
    assert host.update_state()["checking"] is False
