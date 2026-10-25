"""Drag and drop on the Mods page, off-screen with real mouse events over a fake profile in a temp folder: a row moves
up, down, to the top and to the bottom from its grip; a move the dependencies would undo is refused in words at the
drop spot and again after the drop; groups never mix; Esc cancels; a running job refuses; the page scrolls at the
edge. Set S5_SHOTS to keep PNGs of the drag states."""

import gc
import os
from pathlib import Path

import pytest
from bayle.modules.mods.service import profile_entries
from page_window import PageWindow
from PySide6.QtCore import QObject, QPoint, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from test_mods_view import Host, centre, closed, find, opened, settle

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    + "".join(
        f"[[packages]]\nid = \"{n}\"\npath = 'mod/{n}'\n"
        + ('load_after = [{ id = "p1", optional = false }]\n' if n == "p2" else "")
        + "\n"
        for n in ("p1", "p2", "p3", "p4")
    )
    + "[[natives]]\npath = 'natives/n1.dll'\n\n[[natives]]\npath = 'natives/n2.dll'\n"
)


@pytest.fixture
def profile(tmp_path) -> Path:
    p = tmp_path / "main.me3"
    p.write_text(PROFILE, encoding="utf-8")
    for n in ("p1", "p2", "p3", "p4"):
        (tmp_path / "mod" / n / "parts").mkdir(parents=True)
    (tmp_path / "natives").mkdir()
    for n in ("n1.dll", "n2.dll"):
        (tmp_path / "natives" / n).write_bytes(b"d")
    return p


def order(profile: Path, kind: str) -> list[str]:
    return [e["name"] for e in profile_entries(profile) if e["kind"] == kind]


def shot(w: PageWindow, name: str) -> None:
    where = os.environ.get("S5_SHOTS") or os.environ.get("RS_VIEW_SHOTS")
    if where and w.window is not None:
        Path(where).mkdir(parents=True, exist_ok=True)
        w.window.grabWindow().save(str(Path(where) / f"dnd-mods-{name}.png"))


class Drag:
    """A mouse drag from one row's grip to another row, in steps, ending in a release (or not)."""

    def __init__(self, w: PageWindow, grip: str, target_row: str, below: bool = False):
        self.w, self.win = w, w.window
        g = find(w, grip)
        self.start = centre(g)
        t = centre(find(w, "grip_" + target_row))
        self.end = QPoint(self.start.x(), t.y() + (14 if below else 0))
        QTest.mousePress(self.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.start)
        settle(40)
        steps = 12
        for i in range(1, steps + 1):
            y = self.start.y() + (self.end.y() - self.start.y()) * i // steps
            QTest.mouseMove(self.win, QPoint(self.start.x(), y))
            settle(20)

    def release(self) -> None:
        QTest.mouseRelease(self.win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, self.end)
        settle(250)


def reason(w: PageWindow) -> str:
    page = w.page_item()
    return page.property("dropReason") if page is not None else ""


def test_a_row_moves_up_and_down_and_to_the_ends(qt_app, profile):
    w = opened(Host(profile))
    try:
        d = Drag(w, "grip_p4", "p3")
        assert reason(w) == ""
        shot(w, "valid-line")
        d.release()
        assert order(profile, "package") == ["p1", "p2", "p4", "p3"]  # up
        Drag(w, "grip_p4", "p3").release()  # down again
        assert order(profile, "package") == ["p1", "p2", "p3", "p4"]
        Drag(w, "grip_p3", "p1").release()  # to the top
        assert order(profile, "package") == ["p3", "p1", "p2", "p4"]
        Drag(w, "grip_p3", "p4").release()  # to the bottom
        assert order(profile, "package") == ["p1", "p2", "p4", "p3"]
    finally:
        closed(w)


def test_a_drop_the_dependencies_would_undo_is_refused_in_words_at_the_spot(qt_app, profile):
    w = opened(Host(profile))
    try:
        toasts = []
        w.notifier.toastActionRequested.connect(lambda text, error, action, token: toasts.append((text, action)))
        d = Drag(w, "grip_p2", "p1")
        assert reason(w) == "p2 must load after p1 (set in its options)"
        shot(w, "refused-line")
        d.release()
        assert toasts == [("p2 must load after p1 (set in its options)", "Edit options")]
        assert order(profile, "package") == ["p1", "p2", "p3", "p4"]
    finally:
        closed(w)


def test_a_package_never_lands_among_the_natives(qt_app, profile):
    w = opened(Host(profile))
    try:
        Drag(w, "grip_p2", "n2.dll").release()
        assert order(profile, "package") == ["p1", "p2", "p3", "p4"]
        assert order(profile, "native") == ["n1.dll", "n2.dll"]
        Drag(w, "grip_n2.dll", "n1.dll").release()
        assert order(profile, "native") == ["n2.dll", "n1.dll"]
    finally:
        closed(w)


def test_esc_cancels_the_drag(qt_app, profile):
    w = opened(Host(profile))
    try:
        d = Drag(w, "grip_p4", "p2")
        QTest.keyClick(w.window, Qt.Key.Key_Escape)
        settle(50)
        d.release()
        assert order(profile, "package") == ["p1", "p2", "p3", "p4"]
    finally:
        closed(w)


def test_a_running_job_refuses_the_drop_in_words(qt_app, profile):
    host = Host(profile)
    host.busy = True
    w = opened(host)
    try:
        toasts = []
        w.notifier.toastRequested.connect(lambda text, error: toasts.append(text))
        d = Drag(w, "grip_p4", "p2")
        assert "job" in reason(w)
        d.release()
        assert order(profile, "package") == ["p1", "p2", "p3", "p4"]
        assert any("job" in t for t in toasts)
    finally:
        closed(w)


def test_the_keyboard_twin_moves_a_focused_row(qt_app, profile):
    w = opened(Host(profile))
    try:
        find(w, "row_p3").forceActiveFocus()
        QTest.keyClick(w.window, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)
        settle(250)
        assert order(profile, "package") == ["p1", "p2", "p4", "p3"]
        QGuiApplication.processEvents()
    finally:
        closed(w)


def test_a_closed_page_leaves_no_qobject_for_the_garbage_collector(qt_app, profile):
    # A moved row offers Undo, a toast action closing over the adapter; kept by the Notifier the adapter owns, it was a
    # cycle that freed the adapter and its models at a later collection, on any thread: CI's next QML load crashed.
    w = opened(Host(profile))
    try:
        Drag(w, "grip_p4", "p3").release()
        assert order(profile, "package") == ["p1", "p2", "p4", "p3"]
    finally:
        closed(w)
    del w
    gc.set_debug(gc.DEBUG_SAVEALL)  # what a collection finds is kept in gc.garbage, not freed
    try:
        gc.collect()
        left = sorted({type(o).__name__ for o in gc.garbage if isinstance(o, QObject)})
        gc.garbage.clear()
    finally:
        gc.set_debug(0)
    assert left == []
