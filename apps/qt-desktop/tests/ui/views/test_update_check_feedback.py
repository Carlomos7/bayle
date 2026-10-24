"""Check for updates always answers: the line changes and a toast reaches a Notifier the shell's Overlays listen to."""

import time

import pytest
from PySide6.QtCore import QCoreApplication

from bayle_qt.launcher.adapter import ShellAdapter
from bayle_qt.launcher.host import ShellHost
from bayle_qt.shell import updates as updates_mod
from bayle_qt.updater import feed

# known stall: a whole shell or the Mods rows (every delegate built in one model reset, see perf/ui-thread.md) is built in one turn
pytestmark = pytest.mark.ui_stall_ok


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
def test_a_forced_check_shows_a_line_and_a_toast_on_a_listened_notifier(qt_app, shell_host, monkeypatch, check, error):
    monkeypatch.setattr(updates_mod.feed, "check_launcher_update", lambda force=False: check)
    monkeypatch.setattr(updates_mod.feed, "check_advisory", lambda force=False: None)
    host = shell_host
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


def _settle_until(cond, ms=4000):
    end = time.time() + ms / 1000
    while not cond() and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


def _toast(w) -> str:
    """The text of the toast the shell's Overlays show right now ("" when none is on show)."""
    win = w.window  # kept: the item wrappers die with a window wrapper that was only a temporary
    todo = [win.contentItem()]
    while todo:
        item = todo.pop()
        try:
            if item.objectName() == "overlays":
                return str(item.property("toastText")) if item.property("toastShown") else ""
            todo.extend(item.childItems())
        except RuntimeError:  # an item that went away while looking
            continue
    return ""


def test_the_real_shell_renders_the_check_toast_and_other_pages_toasts(qt_app, shell_host, monkeypatch):
    from bayle_qt.launcher.window import ShellWindow

    monkeypatch.setattr(updates_mod.feed, "check_launcher_update", lambda force=False: feed.UpdateCheck("fresh"))
    monkeypatch.setattr(updates_mod.feed, "check_advisory", lambda force=False: None)
    # the Settings page asks me3 on a thread that outlives the test: no real me3, network or settings write
    monkeypatch.setattr(ShellHost, "me3_facts", lambda self: {})
    host = shell_host
    w = ShellWindow(host)
    try:
        assert w.build() and w.window is not None
        w.window.resize(1100, 760)
        w.window.show()
        w.adapter.open_page("settings")
        assert _settle_until(lambda: w.page_item("settings") is not None)
        adapter = w.adapter.adapterFor("settings")
        host.check_for_updates()
        assert adapter.launcherLine.startswith("Checking for updates")
        assert _settle_until(lambda: "Up to date" in _toast(w)), "the check toast never showed"
        assert not adapter.launcherLine.startswith("Checking")
        w.adapter.open_page("mods")
        w.adapter.notifierFor("mods").toast("Hello from Mods")
        assert _settle_until(lambda: "Hello from Mods" in _toast(w)), "a page's toast never showed"
    finally:
        w.dispose()
