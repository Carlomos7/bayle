"""The Mods page in its own window, off-screen, over a synthetic profile on disk: it loads with no QML warning in every
theme at the narrow and wide sizes; real clicks switch a mod off (the profile is written, Undo is offered), a drag the
dependencies would undo is refused with the reason, removing asks first and runs as a job, and Edit as text saves
through the profile writer."""

from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QObject, QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game import catalog as games
from roundtable_souls.services.mods import profile_entries
from roundtable_souls.ui.page_window import PageWindow
from roundtable_souls.ui.pages.registry import page as registered
from support import er

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    '[[packages]]\nid = "cloud"\npath = \'mod/cloud\'\nload_after = [{ id = "flora", optional = false }]\n\n'
    "[[natives]]\npath = 'natives/a.dll'\n"
)


class Host:
    """The window that hosts the page, without one: jobs and hand-offs are recorded, reads run at once."""

    def __init__(self, profile: Path):
        self.profile = profile
        self.busy = False
        self.game_running = False
        self.locations = er()
        self.settings = LauncherSettings()
        self.game = games.ELDEN_RING
        self.setup = type("Setup", (), {"profile": str(profile), "kind": "me3"})()
        self.jobs: list[str] = []
        self.changes: list[str] = []
        self.installs: list = []

    def run_job(self, job, status):
        self.jobs.append(status)

    def run_in_background(self, work, on_result):
        on_result(work())

    def profile_changed(self, note):
        self.changes.append(note)

    def profile_deleted(self, profile, moved_to):
        self.changes.append(f"deleted {profile.name}")

    def install(self, from_folder):
        self.installs.append(from_folder)

    def install_paths(self, paths):
        self.installs.extend(paths)

    def open_path(self, path):
        pass

    def pick_folder(self, title):
        self.changes.append(f"asked: {title}")
        return self.folder

    def pick_file(self, title, filters):
        return None

    def save_file(self, title, name):
        return None

    def open_mod_configs(self, select=""):
        self.changes.append(f"mod configs: {select}")

    def profiles(self):
        return [self.profile.name]

    def profile_index(self):
        return 0

    def pick_profile(self, index):
        self.changes.append(f"picked profile {index}")

    folder = None


@pytest.fixture
def profile(tmp_path) -> Path:
    p = tmp_path / "main.me3"
    p.write_text(PROFILE, encoding="utf-8")
    for d in ("mod/flora/parts", "mod/cloud/parts", "natives"):
        (tmp_path / d).mkdir(parents=True)
    (tmp_path / "natives" / "a.dll").write_bytes(b"d")
    return p


def settle(ms: int = 80) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QApplication.processEvents()


def opened(host: Host, theme: str = "dark", width: int = 1100) -> PageWindow:
    w = PageWindow(registered("mods"), host, theme)
    assert w.build(), w.warnings
    win = w.window
    assert win is not None
    win.resize(width, 820)
    win.show()
    settle(300)
    return w


def closed(w: PageWindow) -> None:
    warnings = list(w.warnings)
    w.dispose()
    settle()
    assert warnings == []


def find(w: PageWindow, name: str):
    win = w.window
    assert win is not None
    root = win.contentItem()
    todo = [root.parentItem() or root]  # from the window's root: dialogs live in its overlay layer
    while todo:
        item = todo.pop()
        if item.objectName() == name:
            return item
        todo.extend(item.childItems())
    popup = win.findChild(QObject, name)  # a dialog itself is a QObject, not an item
    if popup is not None:
        return popup
    raise AssertionError(f"no item named {name}")


def centre(item) -> QPoint:
    p = item.mapToScene(item.boundingRect().center())
    return QPoint(round(p.x()), round(p.y()))


def click(w: PageWindow, item) -> None:
    win = w.window
    assert win is not None
    QTest.mouseClick(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre(item))
    settle(200)


@pytest.mark.parametrize("width", (740, 1100))
@pytest.mark.parametrize("theme", ("dark", "tarnished", "light"))
def test_the_page_renders_in_every_theme_at_both_sizes(qt_app, profile, shots, theme, width):
    w = opened(Host(profile), theme, width)
    try:
        win = w.window
        assert win is not None
        win.grabWindow().save(str(shots / f"mods-{theme}-{width}.png"))
        state = w.adapter.state()
        assert [r.name for r in state.groups[0].rows] == ["flora", "cloud"]
        assert [r.name for r in state.groups[1].rows] == ["a.dll"]
        assert w.page_item() is not None
    finally:
        closed(w)


def test_switching_a_mod_off_writes_the_profile_and_offers_undo(qt_app, profile):
    host = Host(profile)
    w = opened(host)
    try:
        undos = []
        w.notifier.toastActionRequested.connect(lambda text, error, action, token: undos.append((text, action, token)))
        click(w, find(w, "toggle_flora"))
        flora = next(e for e in profile_entries(profile) if e["name"] == "flora")
        assert flora["enabled"] is False
        assert host.changes == ["profile: flora off"]
        assert undos and undos[0][1] == "Undo"
        w.notifier.toastAction(undos[0][2])  # Undo puts the profile back
        settle()
        assert next(e for e in profile_entries(profile) if e["name"] == "flora")["enabled"] is True
    finally:
        closed(w)


def test_an_interrupted_change_is_put_right_as_the_page_reads_the_profile(qt_app, profile, monkeypatch):
    from roundtable_souls.services import mods as mod_service

    calls = []

    def recover(prof, timeout=30.0):
        calls.append(prof)
        return ["the removal of flora was undone"] if len(calls) == 1 else []

    monkeypatch.setattr(mod_service, "recover_interrupted", recover)
    host = Host(profile)
    w = opened(host)
    try:
        assert [n.key for n in w.adapter.state().notices] == ["recovered"]
        host.busy = True  # a job holds the folder: it is not looked at then
        w.adapter.refresh()
        settle()
        assert len(calls) == 1 and [n.key for n in w.adapter.state().notices] == ["recovered"]
    finally:
        closed(w)


def test_online_with_a_packages_parameters_warns_and_play_offline_turns_it_off(qt_app, profile):
    from roundtable_souls.services.mods import read_profile_settings

    profile.write_text(PROFILE.replace('profileVersion = "v1"\n', 'profileVersion = "v1"\nstart_online = true\n'))
    (profile.parent / "mod/flora/regulation.bin").write_bytes(b"params")
    host = Host(profile)
    w = opened(host)
    try:
        bar = find(w, "notice_online")
        todo, button = [bar], None
        while todo and button is None:
            item = todo.pop()
            if item.property("text") == "Play offline":
                button = item
            todo.extend(item.childItems())
        assert button is not None
        assert find(w, "fingerprintRow").isVisible()
        undos = []
        w.notifier.toastActionRequested.connect(lambda text, error, action, token: undos.append((text, action, token)))
        click(w, button)
        assert read_profile_settings(profile).get("start_online") is not True
        assert undos and undos[0][1] == "Undo"
        assert "online" not in [n.key for n in w.adapter.state().notices]
    finally:
        closed(w)


def test_a_move_the_dependencies_would_undo_is_refused_with_the_reason(qt_app, profile):
    w = opened(Host(profile))
    try:
        refusals = []
        w.notifier.toastActionRequested.connect(lambda text, error, action, token: refusals.append((text, action)))
        cloud = next(e for e in profile_entries(profile) if e["name"] == "cloud")
        w.adapter.moveTo(cloud["index"], 0)  # what the grip's drop asks for
        settle()
        assert refusals == [("cloud must load after flora (set in its options)", "Edit options")]
        assert [e["name"] for e in profile_entries(profile)][:2] == ["flora", "cloud"]  # unchanged
    finally:
        closed(w)


def test_removing_asks_first_then_runs_as_a_job(qt_app, profile):
    host = Host(profile)
    w = opened(host)
    try:
        asked = []
        w.notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
        click(w, find(w, "remove_a.dll"))
        assert [a[1]["title"] for a in asked] == ["Remove a.dll from the profile"]
        assert host.jobs == []
        w.notifier.answerWith(asked[0][0], True, False)
        assert host.jobs == ["Removing a.dll..."]
    finally:
        closed(w)


class Effect:
    entry = "ersc.dll"


def overhaul_services(monkeypatch, legacy=True, on=True):
    """The overhaul services faked: a profile with an overhaul its installer made, one change to put back."""
    from roundtable_souls.services import mods as mod_service

    calls: dict = {"previews": [], "removed": []}

    def preview(profile, *, loc, revert_asked=False, legacy_choices=()):
        calls["previews"].append((revert_asked, list(legacy_choices)))
        return type(
            "Preview",
            (),
            {"ok": True, "refusals": [], "lines": ["toy.me3 loses Toy's entries"], "asked": [Effect()]},
        )()

    monkeypatch.setattr(mod_service, "overhaul_preview_on", lambda loc: on)
    monkeypatch.setattr(
        mod_service, "profile_overhaul", lambda p, loc: {"label": "Toy", "short_label": "Toy", "legacy": legacy}
    )
    monkeypatch.setattr(mod_service, "overhaul_leftovers", lambda p, loc: [])
    monkeypatch.setattr(mod_service, "legacy_overhaul_choices", lambda p, loc: [("start_online: back to on", "E")])
    monkeypatch.setattr(mod_service, "preview_overhaul_removal", preview)
    return calls


def test_the_overhaul_entries_follow_the_preview_switch(qt_app, profile, monkeypatch):
    overhaul_services(monkeypatch, on=False)
    w = opened(Host(profile))
    try:
        assert w.adapter.property("overhaul")["visible"] is False
    finally:
        closed(w)
    overhaul_services(monkeypatch, on=True)
    w = opened(Host(profile))
    try:
        menu = w.adapter.property("overhaul")
        assert (menu["visible"], menu["remove"], menu["can_remove"], menu["can_clean"]) == (
            True,
            "Remove Toy...",
            True,
            False,
        )
    finally:
        closed(w)


def test_removing_an_installer_made_overhaul_asks_what_to_put_back_then_confirms(qt_app, profile, monkeypatch):
    calls = overhaul_services(monkeypatch)
    host = Host(profile)
    w = opened(host)
    try:
        asked = []
        w.notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
        picks = []
        w.adapter.pickRequested.connect(lambda key, words, rows: picks.append((words["title"], rows)))
        w.adapter.removeOverhaul()
        settle()
        assert picks == [("Put back what Toy's installer changed?", ["start_online: back to on"])]
        click(w, find(w, "pickRow_0"))
        click(w, find(w, "pickApply"))
        assert calls["previews"] == [(False, ["E"])]  # the ticked change goes to the preview
        [(token, words)] = asked
        assert words["title"] == "Remove Toy from main.me3"
        assert words["option"] == "Also switch ersc.dll back off, as it was before the install"
        w.notifier.answerWith(token, True, True)  # the switch-back ticked: previewed again with it
        assert calls["previews"][-1] == (True, ["E"]) and host.jobs == ["Removing Toy..."]
    finally:
        closed(w)


def test_edit_as_text_saves_through_the_profile_writer(qt_app, profile):
    host = Host(profile)
    w = opened(host)
    try:
        w.adapter.setEditText(True)
        settle()
        text = w.adapter.me3Text.replace('id = "cloud"', 'id = "cloud"\n# a note')
        w.adapter.edit(text)
        assert w.adapter.textDirty and w.adapter.me3Error == ""
        w.adapter.edit("profileVersion = ")  # does not parse: Save is off
        assert w.adapter.me3Error.startswith("Does not parse as a profile")
        w.adapter.edit(text)
        w.adapter.saveText()
        settle()
        assert "# a note" in profile.read_text(encoding="utf-8")
        assert not w.adapter.textDirty and host.changes == ["profile: saved as text"]
    finally:
        closed(w)


def test_mod_options_open_from_the_gear_and_save_the_entry(qt_app, profile):
    host = Host(profile)
    w = opened(host)
    try:
        click(w, find(w, "options_cloud"))
        save = find(w, "saveOptions")  # in the window's overlay layer only while the dialog is open
        data = w.adapter.optionsFor(next(e["index"] for e in profile_entries(profile) if e["name"] == "cloud"))
        assert data["loadAfter"] == [{"id": "flora", "optional": False}] and data["others"] == ["flora"]
        click(w, save)
        assert host.changes == ["profile: options saved for cloud"]
        assert next(e for e in profile_entries(profile) if e["name"] == "cloud")["load_after"] == [
            {"id": "flora", "optional": False}
        ]
    finally:
        closed(w)


def test_profile_settings_versions_and_add_existing(qt_app, profile):
    host = Host(profile)
    (profile.parent / "mod" / "extra" / "parts").mkdir(parents=True)
    (profile.parent / "mod" / "extra" / "parts" / "x.partsbnd.dcx").write_bytes(b"x")
    w = opened(host)
    try:
        w.adapter.setSetting("disable_arxan", 1)
        settle()
        assert "disable_arxan = true" in profile.read_text(encoding="utf-8")
        assert w.adapter.settingsFor()["disable_arxan"] == 1
        asked = []
        w.notifier.confirmFullRequested.connect(lambda token, words: asked.append(words["title"]))
        w.adapter.setSetting("start_online", 1)  # online asks first
        assert asked == ["Turn online matchmaking on"]
        versions = w.adapter.versionsList()
        assert versions and versions[0]["path"]
        unlisted = w.adapter.unlistedFor("package")
        assert [u["label"] for u in unlisted] == ["extra"]
        w.adapter.addPaths("package", [unlisted[0]["path"]])
        settle()
        assert "extra" in [e["name"] for e in profile_entries(profile)]
    finally:
        closed(w)
