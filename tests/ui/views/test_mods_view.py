"""The Mods page in its own window, off-screen, over a synthetic profile on disk: it loads with no QML warning in every
theme at the narrow and wide sizes; real clicks switch a mod off (the profile is written, Undo is offered), a drag the
dependencies would undo is refused with the reason, removing asks first and runs as a job, and Edit as text saves
through the profile writer."""

from pathlib import Path

import pytest
from page_window import PageWindow
from PySide6.QtCore import QEventLoop, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from shiboken6 import delete

from bayle.config.settings import LauncherSettings
from bayle.game import catalog as games
from bayle.services import features
from bayle.services.mods import profile_entries
from bayle.services.saves_page import SavesService
from bayle.services.settings import SettingsService
from bayle.session import Session
from bayle.session import ops as _registered_operations  # noqa: F401
from bayle.ui.host import Host as HostContract
from bayle.ui.pages.registry import page as registered
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore
from support import FakeActivityFacts, er

# known stall: a whole shell or the Mods rows (every delegate built in one model reset, see perf/ui-thread.md) is built in one turn
pytestmark = pytest.mark.ui_stall_ok

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
        self.launch_profile = type("Setup", (), {"profile": str(profile), "kind": "me3"})()
        self.legacy_jobs: list[str] = []  # jobs the host itself ran (the pages not behind the session yet)
        self.changes: list[str] = []
        self.installs: list = []
        self.ran = None
        self.session = Session(  # the session runs its jobs at once, over the same disk the test sets up
            JobManager(
                EventBus(),
                spawn=lambda run, name=None: run(),
                game_running=lambda: self.game_running,
                external_busy=lambda: self.busy,
            ),
            plans=PlanStore(),
            locations=lambda: self.locations,
        )
        self.activity = FakeActivityFacts(manager=self.session.jobs)
        self.settings_service = SettingsService(self.session.jobs, lambda: self.locations)
        self.saves_service = SavesService(self.session.jobs, lambda: self.locations)
        self.features = features.build(self.session.jobs, None, lambda: self.locations)

    @property
    def jobs(self) -> list[str]:
        """The titles of the jobs started, in order: the session's (they run at once) and the host's own."""
        mine = (self.session.jobs.get(f"j{i}") for i in range(1, 30))
        return [*[s.title for s in mine if s], *self.legacy_jobs]

    def run_job(self, job, status, on_done=None):
        self.legacy_jobs.append(status)
        self.ran = (job, on_done)

    def follow_job(self, job_id, done):
        done(self.session.jobs.get(job_id))  # the session ran it at once

    def mark_seen(self):
        pass

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

    def open_profile_transfer(self, mode):
        self.changes.append(f"profile transfer: {mode}")

    def open_profile_import(self, unpacked, profiles, staging=None):
        self.changes.append(f"profile import: {profiles}")

    def saves_in_use(self):
        return {}

    def settings_changed(self, key):
        self.changes.append(f"setting: {key}")

    def set_appearance(self):
        pass

    def check_for_updates(self):
        raise RuntimeError("no updates here")

    def update_state(self):
        return {"line": "", "tone": "muted", "notices": []}

    def watch_updates(self, call):
        pass

    def notice_action(self, notice_id, key):
        raise RuntimeError("no updates here")

    def dismiss_notice(self, notice_id):
        pass

    def point_steam_shortcuts(self):
        raise RuntimeError("no Steam shortcuts here")

    def save_logs_for_support(self):
        raise RuntimeError("no logs here")

    def open_logs_folder(self):
        pass

    def me3_facts(self):
        return {}

    def profiles(self):
        return [self.profile.name]

    def profile_index(self):
        return 0

    def pick_profile(self, index):
        self.changes.append(f"picked profile {index}")

    def request_new_profile(self):
        self.changes.append("new profile asked")

    folder = None


def _declares_host(host: Host) -> HostContract:  # pyright checks the fake against the one host contract
    return host


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
    QGuiApplication.processEvents()


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
    delete(
        w
    )  # now, with its adapter and Notifier: a reference cycle through them would free them at a later collection
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


def test_the_page_does_not_recover_interrupted_changes_itself(qt_app, profile, monkeypatch):
    from bayle.services import mods as mod_service

    calls = []

    def recover(prof, timeout=30.0):
        calls.append(prof)
        return ["the removal of flora was undone"]

    monkeypatch.setattr(mod_service, "recover_interrupted", recover)
    host = Host(profile)
    w = opened(host)
    try:
        w.adapter.refresh()
        settle()
        assert calls == []  # reads never write: the session's start-up does the recovery
        assert "recovered" not in [n.key for n in w.adapter.state().notices]
    finally:
        closed(w)


@pytest.mark.parametrize("theme", ("dark", "tarnished", "light"))
def test_every_notice_bar_shows_its_text(qt_app, profile, theme):
    profile.write_text(PROFILE.replace('profileVersion = "v1"\n', 'profileVersion = "v1"\nstart_online = true\n'))
    (profile.parent / "mod/flora/regulation.bin").write_bytes(b"params")
    w = opened(Host(profile), theme)
    try:
        bar = find(w, "notice_online")
        assert bar.property("text").strip() != ""  # a delegate role named `text` once bound to itself and left it empty
    finally:
        closed(w)


def test_a_profile_outside_bayles_folder_gets_a_notice_with_a_move_in_button(qt_app, profile, monkeypatch):
    from bayle.services import profile_mods

    monkeypatch.setattr(profile_mods, "_outside", lambda prof, loc: True)
    w = opened(Host(profile))
    try:
        bar = find(w, "notice_outside")
        assert "outside Bayle's folder" in bar.property("text")
        moved = []
        monkeypatch.setattr(w.adapter, "moveIntoLauncherFolder", lambda: moved.append(1))
        w.adapter.noticeAction("outside")
        assert moved == [1]
    finally:
        closed(w)


def test_online_with_a_packages_parameters_warns_and_play_offline_turns_it_off(qt_app, profile):
    from bayle.services.mods import read_profile_settings

    profile.write_text(PROFILE.replace('profileVersion = "v1"\n', 'profileVersion = "v1"\nstart_online = true\n'))
    (profile.parent / "mod/flora/regulation.bin").write_bytes(b"params")
    host = Host(profile)
    w = opened(host)
    try:
        bar = find(w, "notice_online")
        todo, button = [bar], None
        while todo and button is None:
            item = todo.pop()
            if item.property("text") == "Launch Offline":
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


def test_removing_a_folder_another_entry_uses_still_asks_first(qt_app, profile):
    profile.write_text(PROFILE + "[[natives]]\npath = 'natives/b.dll'\n", encoding="utf-8")
    (profile.parent / "natives" / "b.dll").write_bytes(b"d")
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


def _removed_with_toast(w, host):
    """Click Remove on a.dll (no confirm), run the job it started, and give back the toast's Undo token."""
    asked, toasts = [], []
    w.notifier.confirmFullRequested.connect(lambda token, words: asked.append(words))
    w.notifier.toastActionRequested.connect(lambda text, error, action, token: toasts.append((text, action, token)))
    click(w, find(w, "remove_a.dll"))
    assert asked == [] and host.jobs == ["Removing a.dll..."]  # the session ran it at once
    assert [t[:2] for t in toasts] == [("Removed a.dll", "Undo")]
    return toasts[0][2]


def test_removing_without_a_confirm_then_the_toast_undo_is_byte_exact(qt_app, profile):
    before = profile.read_bytes()
    folder = profile.parent / "natives"
    host = Host(profile)
    w = opened(host)
    try:
        token = _removed_with_toast(w, host)
        assert profile.read_bytes() != before and not folder.exists()
        w.notifier.toastAction(token)
        assert profile.read_bytes() == before and (folder / "a.dll").read_bytes() == b"d"
    finally:
        closed(w)


def test_the_toast_undo_keeps_a_later_unrelated_edit(qt_app, profile):
    host = Host(profile)
    w = opened(host)
    try:
        token = _removed_with_toast(w, host)
        profile.write_text(
            profile.read_text(encoding="utf-8").replace('id = "flora"', 'id = "flora2"'), encoding="utf-8"
        )
        w.notifier.toastAction(token)
        text = profile.read_text(encoding="utf-8")
        assert 'id = "flora2"' in text and "natives/a.dll" in text
        assert (profile.parent / "natives" / "a.dll").is_file()
    finally:
        closed(w)


def test_the_toast_undo_refuses_when_the_bin_item_is_gone(qt_app, profile, monkeypatch):
    from bayle.platform import trash

    sent, real = [], trash.send
    monkeypatch.setattr(trash, "send", lambda path: sent.append(real(path)) or sent[-1])
    host = Host(profile)
    w = opened(host)
    try:
        errors = []
        w.notifier.toastRequested.connect(lambda text, error: errors.append(text) if error else None)
        token = _removed_with_toast(w, host)
        trash.purge(sent[0])
        after = profile.read_bytes()
        w.notifier.toastAction(token)
        assert errors and "no longer in the Recycle Bin" in errors[-1]
        assert profile.read_bytes() == after and not (profile.parent / "natives").exists()
    finally:
        closed(w)


class Effect:
    entry = "ersc.dll"


def overhaul_services(monkeypatch, legacy=True, on=True):
    """The overhaul services faked: a profile with an overhaul its installer made, one change to put back."""
    from bayle.services import mods as mod_service

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
    from bayle.services import mods as mod_service

    monkeypatch.setattr(mod_service, "remove_overhaul", lambda p: calls["removed"].append(p))
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
        assert len(calls["removed"]) == 1  # what was previewed with the switch-back is what ran
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


def typed(win, text: str) -> None:
    for ch in text:
        QTest.keyClick(win, ch)


def _text(w: PageWindow, name: str):
    return find(w, name).property("text")


def test_clicking_the_profile_name_edits_it_in_place(qt_app, profile, shots):
    host = Host(profile)
    w = opened(host)
    try:
        win = w.window
        assert win is not None
        assert not find(w, "profileNameEdit").property("visible")
        click(w, find(w, "profileTitle"))
        edit = find(w, "profileNameEdit")
        assert edit.property("visible") and edit.property("activeFocus") and edit.property("text") == "main"
        typed(win, "x:y")  # selected text is replaced; ":" is not a name Windows allows
        settle(450)  # the check runs once typing pauses
        assert "Windows doesn't allow" in _text(w, "profileNameProblem")
        win.grabWindow().save(str(shots / "mods-profile-rename.png"))
        QTest.keyClick(win, Qt.Key.Key_Return)
        settle()
        assert host.jobs == [] and edit.property("visible")  # a refused name starts nothing and stays open
        QTest.keyClick(win, Qt.Key.Key_Escape)
        settle()
        assert not find(w, "profileNameEdit").property("visible") and host.jobs == []
        click(w, find(w, "profileTitle"))
        typed(win, "Renamed")
        QTest.keyClick(win, Qt.Key.Key_Return)
        settle()
        assert host.jobs == ["Renaming main..."] and not find(w, "profileNameEdit").property("visible")
        host.busy = True  # while a job runs the field does not open; the reason is shown
        click(w, find(w, "profileTitle"))
        assert not find(w, "profileNameEdit").property("visible")
        assert "Wait for the current job" in _text(w, "profileNameProblem")
    finally:
        closed(w)


def test_the_profile_menu_commands_reach_the_page(qt_app, profile):
    w = opened(Host(profile))
    try:
        assert {"rename", "duplicate"} <= set(registered("mods").commands)
        w.adapter.command("rename", [])
        settle()
        assert find(w, "profileNameEdit").property("visible")
    finally:
        closed(w)


def test_take_over_is_enabled_only_for_an_installer_made_setup_and_offers_to_install_again(
    qt_app, profile, monkeypatch
):
    from bayle.services import mods as mod_service

    overhaul_services(monkeypatch)
    for takeover, enabled in ((False, False), (True, True)):
        monkeypatch.setattr(
            mod_service,
            "profile_overhaul",
            lambda p, loc, takeover=takeover: {
                "label": "Toy",
                "short_label": "Toy",
                "legacy": True,
                "takeover": takeover,
            },
        )
        w = opened(Host(profile))
        try:
            menu = w.adapter.property("overhaul")
            assert (menu["take_over"], menu["can_take_over"]) == ("Take over Toy...", enabled)
        finally:
            closed(w)
    chosen = []
    monkeypatch.setattr(mod_service, "take_over_choices", lambda p, loc: [])

    def preview(p, *, loc, chosen=(), revert_asked=False):
        return type(
            "Preview", (), {"ok": True, "refusals": [], "lines": ["main.me3 loses Toy's entries"], "asked": []}
        )()

    monkeypatch.setattr(mod_service, "preview_take_over", preview)
    monkeypatch.setattr(mod_service, "remove_overhaul", lambda p: chosen.append(p))
    host = Host(profile)
    w = opened(host)
    try:
        asked = []
        w.notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
        w.adapter.takeOverOverhaul()
        settle()
        [(token, words)] = asked
        assert words["title"] == "Take over Toy in main.me3" and words["apply"] == "Take over"
        w.notifier.answerWith(token, True, False)
        assert host.jobs == ["Taking over Toy..."] and len(chosen) == 1  # the session ran the job at once
        settle()  # the job is done: asks about installing again
        assert asked[-1][1]["title"] == "Install Toy with the launcher now?" and host.installs == []
        w.notifier.answerWith(asked[-1][0], True, False)
        assert host.installs == [True]  # opens Install mod; nothing installs by itself
    finally:
        closed(w)


def test_take_over_ticks_the_entries_the_installer_copied(qt_app, profile, monkeypatch):
    from bayle.mods.overhaul_takeover import EntryChoice
    from bayle.services import mods as mod_service

    overhaul_services(monkeypatch)
    monkeypatch.setattr(
        mod_service,
        "profile_overhaul",
        lambda p, loc: {"label": "Toy", "short_label": "Toy", "legacy": True, "takeover": True},
    )
    monkeypatch.setattr(
        mod_service,
        "take_over_choices",
        lambda p, loc: [EntryChoice("native", "a.dll", False), EntryChoice("native", "toy.dll", True)],
    )
    w = opened(Host(profile))
    try:
        picks = []
        w.adapter.pickRequested.connect(lambda key, words, rows: picks.append((words["ticked"], rows)))
        w.adapter.takeOverOverhaul()
        settle()
        [(ticked, rows)] = picks
        assert ticked == [1] and "copied by the installer" in rows[1] and "not in the profile" in rows[0]
    finally:
        closed(w)


def test_cleaning_installer_leftovers_picks_the_folders_then_asks_about_each_backup(qt_app, profile, monkeypatch):
    from types import SimpleNamespace

    from bayle.services import mods as mod_service

    overhaul_services(monkeypatch)
    left = [
        SimpleNamespace(path=Path("C:/x/Old Mod"), label="Old Mod (3 MB)", backups=False),
        SimpleNamespace(path=Path("C:/x/Old Backups"), label="Old Backups (2 MB)", backups=True),
    ]
    monkeypatch.setattr(mod_service, "overhaul_leftovers", lambda p, loc: left)
    removed: list = []
    monkeypatch.setattr(mod_service, "remove_overhaul_leftovers", lambda paths: removed.append(list(paths)) or [])
    host = Host(profile)
    w = opened(host)
    try:
        picks, asked = [], []
        w.adapter.pickRequested.connect(lambda key, words, rows: picks.append((key, words["title"], rows)))
        w.notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words["title"])))
        w.adapter.cleanLeftovers()
        settle()
        [(key, title, rows)] = picks
        assert (title, rows) == ("Clean up installer leftovers", ["Old Mod (3 MB)"])
        w.adapter.picked(key, [0])  # the folder ticked: the backups are asked last
        settle()
        assert [t for _tok, t in asked] == ["Also remove Old Backups?"] and removed == []
        w.notifier.answerWith(asked[0][0], True, False)
        assert host.jobs == ["Moving leftovers to the Recycle Bin..."]
        assert removed == [[Path("C:/x/Old Mod"), Path("C:/x/Old Backups")]]
    finally:
        closed(w)
