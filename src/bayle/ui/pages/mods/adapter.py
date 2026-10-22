"""The Mods page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). It holds no
decisions: the page is the session's snapshot (mods), and every change is one of its operations (mods.*), asked of
the session on the host's worker thread; what needs the player's answer comes back as a plan or a "needs
confirmation" error and is shown through the Notifier, and a job the session runs is followed on the host. Only
what the session sends reaches QML, on the GUI thread."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from bayle.platform.text import tr
from bayle.services.errors import OperationError
from bayle.session import Session
from bayle.session.ops.mods import ModsView
from bayle.ui.models import RowsModel, plain
from bayle.ui.notifications import Notifier
from bayle.ui.pages.calls import Calls
from bayle.ui.pages.mods import take_over
from bayle.ui.pages.mods.install_adapter import InstallAdapter
from bayle.ui.pages.undo import ask_undo
from bayle.ui.refresh import Refresher, stat_key
from bayle.views import load_order
from bayle.views.mods import BUSY, ModsPresenter, ModsState

ROW_KEYS = (  # the presenter's Row, with index and enabled renamed (both are built-in names in a QML delegate)
    "entry",
    "kind",
    "position",
    "name",
    "on",
    "locked",
    "tags",
    "more",
    "status",
    "status_error",
    "has_configs",
    "configs_tip",
    "path",
    "shared",
    "can_share",
)


def _row(row) -> dict:
    d = plain(row)
    d["entry"] = d.pop("index")
    d["on"] = d.pop("enabled")
    return d


class ModsHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell, S9)."""

    @property
    def busy(self) -> bool: ...
    @property
    def game_running(self) -> bool: ...
    @property
    def session(self) -> Session: ...
    @property
    def locations(self) -> Any: ...
    @property
    def profile(self) -> Path | None:
        """The profile the page shows (the current profile's), or None."""

    @property
    def settings(self) -> Any: ...
    @property
    def game(self) -> Any: ...
    def run_in_background(self, work, on_result) -> None: ...
    def follow_job(self, job_id: str, done) -> None:
        """A session job's end, for the page that started it: done(JobSnapshot) on the UI thread."""

    def profile_changed(self, note: str) -> None:
        """The page changed the profile: the host's other views read it again (and log the note)."""

    def install(self, from_folder: bool) -> None:
        """Open the launcher's install flow (today's install dialog; owner, D4)."""

    def install_paths(self, paths: list[Path]) -> None:
        """Install dropped files through the launcher's install flow, in turn."""

    def open_mod_configs(self, select: str = "") -> None:
        """Open the Mod Configs window, showing the mod called select."""

    def open_profile_transfer(self, mode: str) -> None:
        """Open the Export / Import profile window on its "export" or "import" view."""

    def profile_deleted(self, profile: Path, moved_to: Path) -> None:
        """The page deleted the profile: the host forgets it and picks another."""

    @property
    def launch_profile(self) -> Any:
        """The current profile (its file and kind), for the rules about deleting it."""

    def open_path(self, path: Path) -> None: ...

    def pick_folder(self, title: str) -> Path | None:
        """Ask for a folder (the overhaul's unpacked download, a mod to install); None when cancelled."""

    def pick_file(self, title: str, filters: str) -> Path | None:
        """Ask for a file (a mod archive or DLL to install); None when cancelled."""

    def profiles(self) -> list[str]:
        """The profiles the player can pick (the top bar's profile labels)."""
        ...

    def request_new_profile(self) -> None:
        """Ask the shell for its New profile dialog (the page's first-run button)."""


class ModsAdapter(QObject):
    changed = Signal()
    textChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, host: ModsHost, notifier: Notifier, presenter: ModsPresenter | None = None, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.presenter = presenter or ModsPresenter()
        self._view: ModsView | None = None  # the session's snapshot of the page
        self._drag: dict = {}
        self._picks: dict[str, Any] = {}  # an open tick list's key -> what runs with the ticked indexes
        self._hint: Any = None  # the Library disk hint (a Notice), worked out after the page shows
        self._calls = Calls(host, notifier)
        self._checked: tuple[str, str] = ("", "")  # the text the parse gate last judged, and its verdict
        self._state: ModsState = self.presenter.page(None)
        self._loading = False
        self._refresher = Refresher(
            host, self._snapshot, self._build, self._apply, key=self._read_key, busy=self._set_loading
        )
        self._show_all = False
        self._edit_text = False
        self._text = ""
        self._saved_text = ""
        self._crlf = False
        self._words = self.presenter.words()
        self._packages = RowsModel(ROW_KEYS, self)
        self._natives = RowsModel(ROW_KEYS, self)
        self._notices = RowsModel(("key", "severity", "text", "action", "closable"), self)
        self._install = InstallAdapter(host, notifier, self)

    # ---- what the page shows
    title = Property(str, lambda self: self._state.title, notify=changed)
    counts = Property(str, lambda self: self._state.counts, notify=changed)
    empty = Property(str, lambda self: self._state.empty, notify=changed)
    noProfiles = Property(bool, lambda self: self._state.empty != "" and not self.host.profiles(), notify=changed)
    health = Property(dict, lambda self: plain(self._state.health) or {}, notify=changed)
    packageGroup = Property(dict, lambda self: self._group("package"), notify=changed)
    nativeGroup = Property(dict, lambda self: self._group("native"), notify=changed)
    parameters = Property(dict, lambda self: plain(self._state.parameters), notify=changed)
    panel = Property(dict, lambda self: plain(self._panel()), notify=changed)
    rebuildUndo = Property(str, lambda self: self._undo_label(), notify=changed)
    words = Property(dict, lambda self: self._words, constant=True)
    packages = Property(QObject, lambda self: self._packages, constant=True)
    natives = Property(QObject, lambda self: self._natives, constant=True)
    notices = Property(QObject, lambda self: self._notices, constant=True)
    loading = Property(bool, lambda self: self._loading, notify=loadingChanged)
    showAll = Property(bool, lambda self: self._show_all, notify=changed)
    hasProfile = Property(bool, lambda self: self._view is not None and self._view.has_profile, notify=changed)
    overhaul = Property(dict, lambda self: plain(self._view.overhaul) if self._view else {}, notify=changed)
    installer = Property(QObject, lambda self: self._install, constant=True)

    @Slot()
    def createProfile(self) -> None:
        self.host.request_new_profile()

    def _group(self, kind: str) -> dict:
        group = next((g for g in self._state.groups if g.kind == kind), None)
        return plain(group) if group else {"title": "", "count": "", "empty": "", "lines": [], "rows": []}

    def _undo_label(self) -> str:
        return self._view.rebuild_undo.label if self._view and self._view.rebuild_undo else ""

    def _panel(self) -> load_order.LoadOrderPanel:
        empty = load_order.panel(None)
        return load_order.shown(self._view.load_order if self._view else empty, self._show_all)

    def state(self) -> ModsState:
        """What the page shows now (tests and the self-test)."""
        return self._state

    # ---- reading (on the job runner's worker thread)
    # ---- what the shell's menu and keys may ask of this page (ui/launcher/menu.py)
    COMMANDS = {
        "deleteProfile": "deleteProfile",
        "rename": "_ask_profile_rename",
        "duplicate": "duplicateProfile",
        "moveIn": "moveIntoLauncherFolder",
        "profileSettings": "openProfileSettings",
        "editText": "_edit_text_on",
        "fixOrder": "fixOrder",
        "versions": "openVersions",
        "saveUnsaved": "saveText",
        "discardUnsaved": "discardText",
        "back": "_back",
    }

    def command(self, name: str, args) -> bool:
        """Run a menu command; False when this page has none by that name."""
        method = self.COMMANDS.get(name)
        if method is None:
            return False
        getattr(self, method)(*args)
        return True

    def _edit_text_on(self) -> None:
        self.setEditText(True)

    def _back(self) -> None:
        pass

    def unsaved_words(self) -> list[str]:
        return [tr("The me3 profile (edited as text)")] if self._text != self._saved_text else []

    def load_order_broken(self) -> bool:
        """The mod that must stay last is not last and Fix order would change the file (Profile > Fix load order)."""
        stays = self._view.load_order.stays_last if self._view else None
        return bool(stays is not None and stays.can_fix)

    @Slot()
    def refresh(self) -> None:
        self._refresher.request()

    def refresh_if_changed(self) -> None:
        """The host's read after a job: nothing is built when the profile folder looks the same."""
        self._refresher.request(force=False)

    def _set_loading(self, on: bool) -> None:
        self._loading = on
        self.loadingChanged.emit()

    def _snapshot(self) -> dict:
        return {
            "profile": self.host.profile,
            "launch": self.host.launch_profile,
            "settings": self.host.settings,
            "busy": self.host.busy,  # a running job holds the folder: nothing of it is interrupted
            "no_profiles": not self.host.profiles(),
        }

    @staticmethod
    def _read_key(snap: dict) -> tuple | None:
        profile = snap["profile"]
        if profile is None:
            return None
        # shortcut: top-level entries of the profile folder only; a deeper change shows after the next job
        return (
            stat_key([profile, Path(profile).parent], children=True),
            repr(snap["settings"]),
            repr(snap["launch"]),
            snap["busy"],
        )

    def _build(self, snap: dict) -> ModsView:
        """On the worker: read the page. The snapshot writes nothing (the session's start-up puts interrupted changes
        right)."""
        session, profile, launch = self.host.session, snap["profile"], snap["launch"]
        scope = {
            "profile": "" if profile is None else str(profile),
            "kind": getattr(launch, "kind", "me3"),
            "source": str(getattr(launch, "source", "") or ""),
            "no_profiles": snap["no_profiles"],
        }
        return session.snapshot("mods", **scope)

    def _apply(self, view: ModsView) -> None:
        self._view = view
        self._render()
        if not self._edit_text:
            self._read_text()
        self._install.after_job()
        self._look_for_duplicates()

    def _render(self) -> None:
        view = self._view
        assert view is not None
        state = view.state
        notices = state.notices
        if self._hint is not None and len(notices) < self.presenter.notices_shown:
            notices = (*notices, self._hint)  # the disk hint comes last: it waits for a free bar
        self._state = state = ModsState(**{**state.__dict__, "notices": notices})
        groups = {g.kind: g for g in self._state.groups}
        self._packages.set_rows([_row(r) for r in (groups["package"].rows if "package" in groups else ())])
        self._natives.set_rows([_row(r) for r in (groups["native"].rows if "native" in groups else ())])
        self._notices.set_rows(self._state.notices)
        self.changed.emit()

    def _look_for_duplicates(self) -> None:
        """The disk hint: mods kept as the same Separate copy in several profiles, worked out after the page shows."""
        view = self._view
        if view is None or not view.has_profile:
            return
        session, profile = self.host.session, view.profile

        def got(found) -> None:
            hint = found.notice
            if hint != self._hint and self._view is not None and self._view.profile == profile:
                self._hint = hint
                self._render()

        self.host.run_in_background(lambda: session.run("mods.library_hint", {"profile": profile}), got)

    # ---- the Library (opt-in sharing of game-file mods between profiles)
    @Slot(int)
    def share(self, index: int) -> None:
        if self._ready() is None or self._entry(index) is None:
            return
        self._calls.plan("mods.share", self._ref(index=index))

    @Slot(int)
    def separate(self, index: int) -> None:
        if self._ready() is None or self._entry(index) is None:
            return
        self._calls.plan("mods.separate", self._ref(index=index))

    @Slot(int)
    def useInOthers(self, index: int) -> None:
        if self._ready() is None or self._entry(index) is None:
            return

        def chosen(ticked: list[int]) -> None:
            if ticked and not self.host.busy:
                self._calls.job(
                    "mods.library_use", self._ref(index=index, targets=ticked, name=self._entry(index)["name"])
                )

        self._calls.run(
            "mods.library_use_choices", self._ref(index=index), lambda got: self._show_pick(got.prompt, chosen)
        )

    @Slot(result=list)
    def libraryList(self) -> list:
        return self.host.session.run("mods.library", self._ref()).rows

    @Slot()
    def removeUnused(self) -> None:
        if self._ready() is None:
            return
        self._calls.plan("mods.remove_unused", self._ref(), destructive=True)

    # ---- small helpers for changes
    def _profile(self) -> Path | None:
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            self.notifier.toast(tr("Pick a profile first."), error=True)
            return None
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job to finish."), error=True)
            return None
        return Path(profile)

    def _entry(self, index: int) -> dict | None:
        return next((e for e in (self._view.entries if self._view else ()) if e["index"] == index), None)

    def _ref(self, **more: Any) -> dict:
        """The params of an operation on the current profile."""
        return {"profile": str(self.host.profile or ""), **more}

    def _launch_ref(self, **more: Any) -> dict:
        """The same, with the setup it is launched as (the rules about deleting and Seamless Co-op read it)."""
        launch = self.host.launch_profile
        return self._ref(kind=getattr(launch, "kind", "me3"), source=str(getattr(launch, "source", "") or ""), **more)

    def _fail(self, text: str, then=None):
        """An error toast in the page's words ("Could not undo: {why}"), then then()."""

        def failed(e: OperationError) -> None:
            self.notifier.toast(text.format(why=e.message), error=True)
            if then is not None:
                then()

        return failed

    def _changed(self, note: str, toast: str) -> None:
        """A change was written: tell the host, read the page again, offer Undo."""
        self.host.profile_changed(note)
        self.refresh()
        profile = self.host.profile
        self.notifier.toast_action(toast, self._words["undo"], lambda p=profile: self._undo_last(p))

    def _undo_last(self, profile) -> None:
        def undone(_got) -> None:
            self.host.profile_changed("profile: undid the last change")
            self.refresh()
            self.notifier.toast(tr("Undone"))

        self._calls.run("mods.undo_change", {"profile": str(profile)}, undone, self._fail(tr("Could not undo: {why}")))

    # ---- rows
    @Slot(int, bool)
    def setEnabled(self, index: int, on: bool) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            self.refresh()
            return

        def written(got) -> None:
            self._changed(
                got.note,
                (
                    tr("{name} is on again") if on else tr("{name} is off. It stays in the profile and me3 skips it.")
                ).format(name=got.name),
            )

        self._calls.run(
            "mods.set_enabled",
            self._ref(index=index, enabled=bool(on)),
            written,
            self._fail(tr("Could not change the profile: {why}"), self.refresh),
        )

    @Slot(int)
    def remove(self, index: int) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return
        name, asked = entry["name"], []

        def finished(ok: bool, data: dict) -> None:
            if not ok or asked:  # a confirm said Undo is in Activity; no confirm: Undo is right here
                return
            undo = data["result"]["undo"]
            self.notifier.toast_action(
                tr("Removed {name}").format(name=name), self._words["undo"], lambda: self._undo_removal(undo)
            )

        def failed(e: OperationError) -> None:
            self.notifier.toast(e.message, error=True)
            if e.code == "stale":
                self.refresh()

        def option(ticked: bool) -> dict:
            asked.append(1)
            return {"delete_folder": ticked}

        self._calls.job(
            "mods.remove", self._ref(index=index, name=name), finished, failed, retry=option, destructive=True
        )

    def _undo_removal(self, undo: dict) -> None:
        def undone(got) -> None:
            self.host.profile_changed(got.note)
            self.refresh()
            self.notifier.toast(tr("Undone"))

        self._calls.run("mods.undo_removal", {"undo": undo}, undone, self._fail(tr("Could not undo: {why}")))

    @Slot(int)
    def removeHolder(self, index: int) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return

        def finished(ok: bool, data: dict) -> None:
            if ok:
                name = data["result"]["name"]
                self._changed(
                    data["result"]["note"],
                    tr("{name} is out of the profile. Nothing in the game changes.").format(name=name),
                )

        self._calls.plan("mods.remove_holder", self._ref(index=index), done=finished)

    @Slot(int, int)
    def moveTo(self, index: int, to: int) -> None:
        """Move an entry to position `to` (0-based, among its kind as shown)."""
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return
        if self.host.busy:  # a running job holds the profile: say so, never a silent revert
            self.notifier.toast(self.presenter.move_busy().body, error=True)
            self.refresh()
            return

        def moved(got) -> None:
            if got.moved:
                self._changed(f"profile: moved {got.name}", tr("Load order changed"))
                return
            if got.problem:
                refusal = self.presenter.move_refused(got.problem)
                if got.decided_by >= 0:
                    by = got.decided_by
                    self.notifier.toast_action(
                        refusal.body,
                        self.presenter.edit_options_text(),
                        lambda: self.optionsRequested.emit(by),
                        error=True,
                    )
                else:
                    self.notifier.toast(refusal.body, error=True)
            self.refresh()

        self._calls.run(
            "mods.move",
            self._ref(index=index, to=to),
            moved,
            self._fail(tr("Could not change the load order: {why}"), self.refresh),
        )

    @Slot(int)
    def beginDrag(self, index: int) -> None:
        """A drag starts: the session sends the refusal for every drop spot once (mods.drag), so the spots are judged
        in memory as the pointer moves. The real check and the write happen on drop (moveTo)."""
        self._drag = {}
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None or self.host.busy:
            return
        mine = self._drag = {"index": index, "reasons": None}

        def got(table) -> None:
            mine["reasons"] = table.reasons  # not for a drag that has ended

        self._calls.run("mods.drag", self._ref(index=index), got, lambda _e: None)

    @Slot()
    def endDrag(self) -> None:
        self._drag = {}

    @Slot(int, int, result=str)
    def dropReason(self, index: int, to: int) -> str:
        """Why dropping entry `index` at position `to` would be refused (words for the drop spot), or "" when allowed.
        The same rules moveTo applies, over the table the session sent when the drag began."""
        if self.host.busy:
            return self.presenter.move_busy().body
        reasons = self._drag.get("reasons")
        return "" if reasons is None else reasons.get(to, "")

    @Slot(int, int)
    def moveBy(self, index: int, delta: int) -> None:
        """Ctrl+Up / Ctrl+Down and the row's Move menu: by delta places (a large delta: to the top or bottom)."""
        entry = self._entry(index)
        if entry is None or self._view is None:
            return
        order = [r["entry"] for r in (self._packages if entry["kind"] == "package" else self._natives).rows()]
        if index not in order:
            return
        to = max(0, min(len(order) - 1, order.index(index) + delta))
        if to != order.index(index):
            self.moveTo(index, to)

    optionsRequested = Signal(int)  # "Edit options" on a refused move: the page opens that entry's Mod options

    # ---- the Parameters card and the Load order panel
    @Slot()
    def rebuild(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        combine = True if self._state.parameters.state == "stacked" else None
        # a rebuild tool that is not allowed yet is asked about first (the session says so); the answer allows it
        self._calls.job("mods.rebuild", self._ref(combine=combine), retry=lambda _option: {"allow": True})

    @Slot()
    def allowTool(self) -> None:
        """The InfoBar's Allow (owner, D2): what the tool runs, then remembered once the player confirms."""
        if self.host.profile is None or self._view is None:
            return
        label = self._view.tool_label

        def allowed(_got) -> None:
            self.notifier.toast(tr("{tool} is allowed to run").format(tool=label))
            self.refresh()

        self._calls.plan("mods.allow_tool", self._ref(), after=allowed)

    @Slot()
    def undoRebuild(self) -> None:
        rec = self._view.rebuild_undo if self._view else None
        if rec:
            ask_undo(self.host, self.notifier, rec.id)

    @Slot()
    def trimBackups(self) -> None:
        profile = self._profile()
        if profile is None:
            return

        def finished(ok: bool, data: dict) -> None:
            if ok:
                n = data["result"]["moved"]
                self.notifier.toast(tr("{n} older rebuild backups moved to the Recycle Bin.").format(n=n))
                self.refresh()

        self._calls.plan("mods.trim_backups", self._ref(), done=finished)

    @Slot()
    def fixOrder(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        self._calls.run(
            "mods.fix_order",
            self._ref(),
            lambda got: self._changed(got.note, tr("Load order fixed")),
            self._fail(tr("The order could not be fixed: {why}")),
        )

    @Slot(bool)
    def setShowAll(self, on: bool) -> None:
        self._show_all = on
        self.changed.emit()

    # ---- InfoBars
    @Slot(str)
    def closeNotice(self, key: str) -> None:
        if self._view is None:
            return
        if key == "library-hint":
            self._hint = None
        self._calls.run("mods.close_notice", self._ref(key=key), lambda _got: self.refresh())

    @Slot(str)
    def noticeAction(self, key: str) -> None:
        if key == "stale":
            self.rebuild()
        elif key == "allow-tool":
            self.allowTool()
        elif key == "online":
            self.setSetting("start_online", 2)  # Online matchmaking off: a Version, with Undo
        elif key == "seamless":
            self._seamless_action()
        elif key == "folder":
            self._folder_action()
        elif key == "dll-folders":
            self._dll_folders_action()
        elif key == "outside":
            self.moveIntoLauncherFolder()
        elif key == "library-hint":
            self.dialogRequested.emit("library", -1)

    def _folder_action(self) -> None:
        """Rename the profile's folder to its name, or split a crowded folder (a logged job, Undo in Activity)."""
        if self.host.profile is None or self._view is None or self.host.busy:
            return
        kind = self._view.folder_kind
        if kind == "misnamed":
            self._calls.job("mods.rename_folder", self._ref())
        elif kind == "crowded":
            self._calls.plan("mods.split_folder", self._ref(), plain=True)

    def _dll_folders_action(self) -> None:
        """Give each loose DLL mod a folder of its own, after a confirmation (a logged job, Undo in Activity)."""
        if self.host.profile is None or self.host.busy:
            return
        self._calls.plan("mods.dll_folders", self._ref(), plain=True)

    def _seamless_action(self) -> None:
        """Move Seamless Co-op from the game folder into this profile, or clean up what it left there (a job; the
        files go to the Recycle Bin, the profile's own copy and the settings file in use are never touched)."""
        if self.host.launch_profile is None or self.host.busy or self.host.game_running:
            return
        self._calls.plan("mods.seamless", self._launch_ref(), plain=True)

    @Slot()
    def copyFingerprint(self) -> None:
        from PySide6.QtGui import QGuiApplication

        text = self._state.parameters.fingerprint
        if not text:
            return
        QGuiApplication.clipboard().setText(text)
        self.notifier.toast(tr("Fingerprint copied"))

    # ---- overhauls installed with the launcher (preview; owner, D4 A: shown while the switch is on)
    pickRequested = Signal(str, dict, list)  # a tick list: its key, its words (the Pick), the rows' labels

    def _ready(self) -> Path | None:
        """The profile to change, or None (with the reason said) while a job runs."""
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job to finish."), error=True)
            return None
        return self._profile()

    def _show_pick(self, prompt: dict, then) -> None:
        """A tick list the session sent (a Pick prompt with its rows): the page shows it; then(ticked indexes) runs
        with what the player ticked."""
        key = f"pick-{len(self._picks) + 1}"
        self._picks[key] = then
        words = {k: v for k, v in prompt.items() if k not in ("kind", "rows")}
        self.pickRequested.emit(key, words, list(prompt["rows"]))

    @Slot(str, list)
    def picked(self, key: str, indexes: list) -> None:
        then = self._picks.pop(key, None)
        if then is not None:
            then([int(i) for i in indexes])

    @Slot(str)
    def pickCancelled(self, key: str) -> None:
        self._picks.pop(key, None)

    @Slot()
    def installOverhaul(self) -> None:
        if self._ready() is None:
            return
        folder = self.host.pick_folder(self.presenter.overhaul_folder_title())
        if folder is None:
            return
        self._calls.plan("mods.overhaul_install", self._ref(folder=str(folder)))

    @Slot()
    def removeOverhaul(self) -> None:
        profile, has = self._ready(), self._view.overhaul_info if self._view else None
        if profile is None or not has:
            return
        label, legacy = has.label, has.legacy

        def later(_got) -> None:
            if legacy:  # what its installer left is cleaned up once the removal is done
                note = self.presenter.overhaul_leftovers_later(label)
                self.notifier.toast(f"{note.title}. {note.body}")

        def ask(chosen: list) -> None:
            self._calls.plan("mods.overhaul_remove", self._ref(chosen=chosen), destructive=True, after=later)

        if not legacy:
            ask([])
            return
        # what its installer changed is offered unticked (owner, 3.22-A)
        self._calls.run(
            "mods.overhaul_remove_choices",
            self._ref(),
            lambda got: self._show_pick(got.prompt, ask) if got.prompt else ask([]),
        )

    @Slot()
    def takeOverOverhaul(self) -> None:
        take_over.start(self)

    @Slot()
    def cleanLeftovers(self) -> None:
        if self._ready() is None:
            return

        def offered(got) -> None:
            def clean(folders: list, confirmed: list) -> None:
                if (folders or confirmed) and not self.host.busy:
                    self._calls.job("mods.leftovers_clean", self._ref(folders=folders, backups=confirmed))

            def ask_backups(folders: list) -> None:  # last, and one at a time: the only copy from before the overhaul
                self._calls.ask_each(got.backups, lambda confirmed: clean(folders, confirmed), destructive=True)

            if got.folders:
                self._show_pick(got.folders, ask_backups)
            else:
                ask_backups([])

        self._calls.run("mods.leftovers", self._ref(), offered)

    # ---- the header
    @Slot()
    def openProfileFolder(self) -> None:
        profile = self.host.profile
        if profile is not None:
            self.host.open_path(Path(profile).parent)

    @Slot(bool)
    def install(self, from_folder: bool) -> None:
        self._install.pick(from_folder)

    @Slot(list)
    def installDropped(self, urls: list) -> None:
        """Files dropped from Explorer: the Install mod dialog takes them in turn."""
        self._install.dropped(urls)

    # ---- the dialogs (Mod options, Profile settings, Versions, Add existing, attaching a config file)
    dialogRequested = Signal(str, int)  # which dialog, the entry it is about (-1: none)

    @Slot(int)
    def openOptions(self, index: int) -> None:
        if self._entry(index) is not None:
            self.dialogRequested.emit("options", index)

    @Slot(int, result=str)
    def renameCurrent(self, index: int) -> str:
        """The name the Rename dialog starts from: the entry's folder name (empty when the entry is gone)."""
        return self._view.folders.get(index, "") if self._view else ""

    renamePreviewReady = Signal(dict)

    @Slot(int, str)
    def requestRenamePreview(self, index: int, name: str) -> None:
        """Whether renaming to `name` is allowed and what it would change: {ok, lines, refusals, name}, on
        renamePreviewReady."""
        if self._entry(index) is None or self.host.profile is None:
            self.renamePreviewReady.emit({"ok": False, "lines": [], "refusals": [], "name": name})
            return
        self._calls.run(
            "mods.rename_preview",
            self._ref(index=index, name=name),
            lambda got: self.renamePreviewReady.emit({**got.model_dump(), "name": name}),
        )

    @Slot(int, str)
    def rename(self, index: int, name: str) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None or self.host.busy:
            return
        self._calls.job("mods.rename", self._ref(index=index, name=name))

    @Slot(int)
    def openRename(self, index: int) -> None:
        if self._entry(index) is not None:
            self.dialogRequested.emit("rename", index)

    @Slot()
    def openProfileSettings(self) -> None:
        if self.host.profile is not None:
            self.dialogRequested.emit("profile-settings", -1)

    @Slot(str)
    def openProfileTransfer(self, mode: str) -> None:
        self.host.open_profile_transfer(mode)

    @Slot()
    def openVersions(self) -> None:
        if self.host.profile is not None:
            self.dialogRequested.emit("versions", -1)

    @Slot(str)
    def addExisting(self, kind: str) -> None:
        if self._profile() is not None:
            self.dialogRequested.emit("add-existing-" + kind, -1)

    @Slot(int)
    def attachConfig(self, index: int) -> None:
        """A DLL's config files: the Mod Configs window, on that mod (attach, open, edit)."""
        entry = self._entry(index)
        if entry is not None and self._profile() is not None:
            self.host.open_mod_configs(entry["name"])

    # ---- Mod options
    @Slot(int, result=dict)
    def optionsFor(self, index: int) -> dict:
        """What the Mod options dialog shows for one entry (empty when the entry is gone)."""
        if self._entry(index) is None or self.host.profile is None:
            return {}
        try:
            v = self.host.session.run("mods.options", self._ref(index=index))
        except OperationError:
            return {}
        return {
            "index": v.index,
            "name": v.name,
            "kind": v.kind,
            "enabled": v.enabled,
            "id": v.id,
            "loadAfter": [d.model_dump() for d in v.load_after],
            "loadBefore": [d.model_dump() for d in v.load_before],
            "optional": v.optional,
            "loadEarly": v.load_early,
            "initKind": v.init_kind,
            "initValue": v.init_value,
            "finalizer": v.finalizer,
            "others": v.others,
            "overlay": v.overlay,
            "rebuildFile": v.rebuild_file,
            "configs": list(self._view.configs.get(index, ())) if self._view else [],
        }

    @Slot(int, dict)
    def saveOptions(self, index: int, chosen: dict) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return

        def deps(key: str) -> list[dict]:
            return [{"id": d["id"], "optional": bool(d.get("optional"))} for d in chosen.get(key) or []]

        overlay = chosen.get("overlay")
        params = self._ref(
            index=index,
            enabled=bool(chosen.get("enabled", True)),
            id=str(chosen.get("id") or ""),
            load_after=deps("loadAfter"),
            load_before=deps("loadBefore"),
            optional=bool(chosen.get("optional")),
            load_early=bool(chosen.get("loadEarly")),
            finalizer=str(chosen.get("finalizer") or ""),
            init_kind=int(chosen.get("initKind") or 0),
            init_value=str(chosen.get("initValue") or ""),
            overlay=-1 if overlay in (None, -1) else int(bool(overlay)),
            rebuild_file=str(chosen.get("rebuildFile") or ""),
        )

        def failed(e: OperationError) -> None:
            if e.code == "invalid_wait":
                self.notifier.toast(e.message, error=True)
                return
            self.notifier.toast(tr("Could not save the options: {why}").format(why=e.message), error=True)
            self.refresh()

        self._calls.run(
            "mods.save_options",
            params,
            lambda got: self._changed(got.note, tr("{name}: options saved").format(name=got.name)),
            failed,
        )

    # ---- Profile settings
    @Slot(result=dict)
    def settingsFor(self) -> dict:
        if self.host.profile is None:
            return {}
        v = self.host.session.run("mods.settings", self._ref())
        return {
            "savefile": v.savefile,
            "start_online": v.start_online,
            "disable_arxan": v.disable_arxan,
            "mem_patch": v.mem_patch,
            "mem_patch_heap_size": v.mem_patch_heap_size,
            "heapApplies": v.heap_applies,
            "heapShown": v.heap_shown,
        }

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value) -> None:
        """One me3 option; the three-way ones come as 0 (me3 default) / 1 (on) / 2 (off). Turning online matchmaking
        on asks first (the session says so)."""
        profile = self._profile()
        if profile is None:
            return

        def written(got) -> None:
            if got.changed:
                self._changed(got.note, self.presenter.setting_changed(key))

        self._calls.run(
            "mods.set_setting",
            self._ref(key=key, value=value),
            written,
            self._fail(tr("Could not write the profile: {why}")),
            retry=lambda _option: {},
            declined=self.refresh,
        )

    # ---- Versions
    @Slot(result=list)
    def versionsList(self) -> list:
        if self.host.profile is None:
            return []
        got = self.host.session.run("mods.versions", self._ref())
        return [
            {
                "path": v.path,
                "when": datetime.datetime.fromisoformat(v.when).strftime("%Y-%m-%d %H:%M"),
                "why": v.why,
            }
            for v in got.versions
        ]

    @Slot(str)
    def restoreVersion(self, path: str) -> None:
        profile = self._profile()
        if profile is None:
            return

        def restored(got) -> None:
            self.host.profile_changed("profile: restored an earlier version")
            self.refresh()
            if got.before is not None:
                before = got.before

                def undone(_got) -> None:
                    self.host.profile_changed("profile: undid a restore")
                    self.refresh()

                def undo() -> None:
                    self._calls.run("mods.restore_version", self._ref(path=before), undone)

                self.notifier.toast_action(tr("The earlier version is back"), self._words["undo"], undo)

        self._calls.run(
            "mods.restore_version", self._ref(path=path), restored, self._fail(tr("Could not restore: {why}"))
        )

    # ---- Add existing
    @Slot(str, result=list)
    def unlistedFor(self, kind: str) -> list:
        if self.host.profile is None:
            return []
        return list(self.host.session.run("mods.unlisted", self._ref(kind=kind)).folders)

    @Slot(str, list)
    def addPaths(self, kind: str, paths: list) -> None:
        profile = self._profile()
        if profile is None or not paths:
            return

        def added(got) -> None:
            names = ", ".join(got.names)
            self._changed(
                f"profile: added {names}", tr("Added {names}: they load at the next launch").format(names=names)
            )
            if got.loose_dlls:
                self._dll_folders_action()  # the same move the notice offers, asked right away

        self._calls.run(
            "mods.add_existing",
            self._ref(kind=kind, paths=[str(p) for p in paths]),
            added,
            self._fail(tr("Could not add: {why}")),
        )

    @Slot()
    def deleteProfile(self) -> None:
        profile = self.host.profile
        if profile is None:
            self.notifier.toast(tr("Pick a profile first."), error=True)
            return
        name = Path(profile).stem

        def finished(ok: bool, data: dict) -> None:
            if not ok:
                return
            self.host.profile_deleted(Path(profile), Path(data["result"]["moved_to"]))
            self.notifier.toast(tr("Profile {name} deleted. It is in Deleted profiles.").format(name=name))
            self.refresh()

        self._calls.plan("mods.delete_profile", self._launch_ref(), destructive=True, done=finished)

    # ---- renaming and duplicating the profile (click its name in the header, or Profile > Rename / Duplicate)
    profileRenameRequested = Signal()  # the menu asked: the header opens its name field

    def _ask_profile_rename(self) -> None:
        QTimer.singleShot(0, self.profileRenameRequested.emit)  # the page may only just have been shown

    @Slot(result=str)
    def profileRenameBlock(self) -> str:
        """Why the profile can't be renamed or copied now ("" when it can): no profile, run by an installer, a job or
        the game running. The profile's own part comes with the page; a running job is asked of the host."""
        profile = self.host.profile
        if profile is None or self._view is None or not self._view.has_profile:
            return tr("Pick a profile first.")
        code = self._view.rename_code or (BUSY if self.host.busy else None)
        return self.presenter.rename_block(code, Path(profile).stem, self.host.game_running)

    @Slot(str, result=str)
    def profileNameCheck(self, name: str) -> str:
        """Why `name` can't be the profile's new name ("" when it can). Reads the profile's folder only."""
        if self.host.profile is None:
            return tr("Pick a profile first.")
        return self.host.session.run("mods.profile_name_check", self._launch_ref(name=name)).problem

    @Slot(str, result=str)
    def renameProfile(self, name: str) -> str:
        """Rename the profile as a logged job (its Undo is in Activity). Returns why not ("" when it started)."""
        block = self.profileRenameBlock()
        if block or self.host.profile is None:
            return block
        why = self.profileNameCheck(name)
        if why:
            return why
        self._calls.job("mods.rename_profile", self._launch_ref(name=name))
        return ""

    @Slot()
    def duplicateProfile(self) -> None:
        block = self.profileRenameBlock()
        if block or self.host.profile is None:
            self.notifier.toast(block, error=True)
            return
        # packages can be shared: the session asks, never forces; the check box is the answer
        self._calls.job("mods.duplicate_profile", self._launch_ref(), retry=lambda option: {"share": option})

    def profile_outside(self) -> bool:
        """The profile is not in Bayle's folder, so the menu offers Move into Bayle's folder."""
        return self._view is not None and self._view.has_profile and self._view.outside

    @Slot()
    def moveIntoLauncherFolder(self) -> None:
        """Ask, then move the profile into Bayle's folder as a logged job (its Undo is in Activity)."""
        block = self.profileRenameBlock()
        if block or self.host.profile is None:
            self.notifier.toast(block, error=True)
            return
        self._calls.plan("mods.move_in", self._launch_ref(), plain=True)

    # ---- Edit as text
    editText = Property(bool, lambda self: self._edit_text, notify=textChanged)
    me3Text = Property(str, lambda self: self._text, notify=textChanged)
    textDirty = Property(bool, lambda self: self._text != self._saved_text, notify=textChanged)
    me3Error = Property(str, lambda self: self._parse_error(), notify=textChanged)

    def _read_text(self) -> None:
        profile = self.host.profile

        def got(view) -> None:
            self._crlf = view.crlf
            self._text = self._saved_text = view.text
            self.textChanged.emit()

        if profile is None:
            self._crlf, self._text, self._saved_text = False, "", ""
            self.textChanged.emit()
            return
        self._calls.run("mods.text", self._ref(), got)

    def _parse_error(self) -> str:
        """Why the text does not parse ("" when it does): the session's gate, asked once per text."""
        if self._checked[0] != self._text:
            problem = self.host.session.run("mods.check_text", {"text": self._text}).problem
            self._checked = (self._text, problem)
        return self._checked[1]

    @Slot(bool)
    def setEditText(self, on: bool) -> None:
        if not on and self._text != self._saved_text:
            return  # the page asks first (Save / Discard / Cancel)
        self._edit_text = on
        if on:
            self._read_text()
        self.textChanged.emit()

    @Slot(str)
    def edit(self, text: str) -> None:
        if text != self._text:
            self._text = text
            self.textChanged.emit()

    @Slot()
    def saveText(self) -> None:
        profile = self._profile()
        if profile is None or self._parse_error():
            return
        text = self._text

        def saved(got) -> None:
            self._saved_text = text
            self.textChanged.emit()
            self._changed(got.note, tr(".me3 saved  ·  a Version was kept"))

        self._calls.run(
            "mods.save_text",
            self._ref(text=text, crlf=self._crlf),
            saved,
            self._fail(tr("Could not save the profile: {why}")),
        )

    @Slot()
    def discardText(self) -> None:
        self._text = self._saved_text
        self.textChanged.emit()
