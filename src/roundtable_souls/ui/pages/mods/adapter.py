"""The Mods page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). It holds no
decisions: what to show comes from the presenter, what a change does from services/profile_mods.py. Reading the
profile and the Load order scan runs on the job runner's worker thread and only the presenter's output reaches QML,
on the GUI thread; rebuilds and removals run as logged jobs of the host (the window that owns the job runner);
results reach the user through the Notifier."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from roundtable_souls.mods import conflicts as mod_overview
from roundtable_souls.mods import profile_edit
from roundtable_souls.services import mods as mod_service
from roundtable_souls.services import profile_mods
from roundtable_souls.ui.models import RowsModel, plain
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.activity.presenter import ActivityPresenter
from roundtable_souls.ui.pages.activity.presenter import Refusal as UndoRefusal
from roundtable_souls.ui.pages.mods import load_order
from roundtable_souls.ui.pages.mods.presenter import ModsPresenter, ModsState
from roundtable_souls.ui.text import tr

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
    def locations(self) -> Any: ...
    @property
    def profile(self) -> Path | None:
        """The profile the page shows (the current setup's), or None."""

    @property
    def settings(self) -> Any: ...
    @property
    def game(self) -> Any: ...
    def run_job(self, job, status: str) -> None: ...
    def run_in_background(self, work, on_result) -> None: ...
    def profile_changed(self, note: str) -> None:
        """The page changed the profile: the host's other views read it again (and log the note)."""

    def install(self, from_folder: bool) -> None:
        """Open the launcher's install flow (today's install dialog; owner, D4)."""

    def install_paths(self, paths: list[Path]) -> None:
        """Install dropped files through the launcher's install flow, in turn."""

    def profile_deleted(self, profile: Path, moved_to: Path) -> None:
        """The page deleted the profile: the host forgets it and picks another."""

    @property
    def setup(self) -> Any:
        """The current setup (its profile and kind), for the rules about deleting it."""

    def open_path(self, path: Path) -> None: ...


class ModsAdapter(QObject):
    changed = Signal()
    textChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, host: ModsHost, notifier: Notifier, presenter: ModsPresenter | None = None, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.presenter = presenter or ModsPresenter()
        self._facts: profile_mods.PageFacts | None = None
        self._scan: dict | None = None
        self._tool: Any = None
        self._rebuild_undo: dict | None = None
        self._state: ModsState = self.presenter.page(None)
        self._loading = False
        self._again = False
        self._show_all = False
        self._edit_text = False
        self._text = ""
        self._saved_text = ""
        self._crlf = False
        self._words = self.presenter.words()
        self._packages = RowsModel(ROW_KEYS, self)
        self._natives = RowsModel(ROW_KEYS, self)
        self._notices = RowsModel(("key", "severity", "text", "action", "closable"), self)

    # ---- what the page shows
    title = Property(str, lambda self: self._state.title, notify=changed)
    counts = Property(str, lambda self: self._state.counts, notify=changed)
    empty = Property(str, lambda self: self._state.empty, notify=changed)
    health = Property(dict, lambda self: plain(self._state.health) or {}, notify=changed)
    packageGroup = Property(dict, lambda self: self._group("package"), notify=changed)
    nativeGroup = Property(dict, lambda self: self._group("native"), notify=changed)
    parameters = Property(dict, lambda self: plain(self._state.parameters), notify=changed)
    panel = Property(dict, lambda self: plain(load_order.panel(self._scan, self._show_all)), notify=changed)
    rebuildUndo = Property(str, lambda self: self._undo_label(), notify=changed)
    words = Property(dict, lambda self: self._words, constant=True)
    packages = Property(QObject, lambda self: self._packages, constant=True)
    natives = Property(QObject, lambda self: self._natives, constant=True)
    notices = Property(QObject, lambda self: self._notices, constant=True)
    loading = Property(bool, lambda self: self._loading, notify=loadingChanged)
    showAll = Property(bool, lambda self: self._show_all, notify=changed)
    hasProfile = Property(bool, lambda self: self._facts is not None and not self._facts.error, notify=changed)

    def _group(self, kind: str) -> dict:
        group = next((g for g in self._state.groups if g.kind == kind), None)
        return plain(group) if group else {"title": "", "count": "", "empty": "", "lines": [], "rows": []}

    def _undo_label(self) -> str:
        if not self._rebuild_undo:
            return ""
        from roundtable_souls.mods import undo as mod_undo

        return tr(mod_undo.label(self._rebuild_undo.get("undo")))

    def state(self) -> ModsState:
        """What the page shows now (tests and the self-test)."""
        return self._state

    # ---- reading (on the job runner's worker thread)
    @Slot()
    def refresh(self) -> None:
        if self._loading:
            self._again = True
            return
        profile = self.host.profile
        self._loading = True
        self.loadingChanged.emit()
        loc, settings, game = self.host.locations, self.host.settings, self.host.game

        def work():
            if profile is None or not Path(profile).is_file():
                return None, None, None, None
            facts = profile_mods.page_facts(profile, loc=loc, settings=settings)
            try:
                scan = mod_overview.overview(Path(profile), loc=loc)
            except Exception as e:  # a broken profile or record: the page shows what it has
                scan = {"profile": str(profile), "scan": {"error": str(e)}}
            tool = profile_mods.tool_to_offer(profile, game, loc=loc)
            try:
                undo = profile_mods.last_rebuild_undo(profile)
            except Exception:
                undo = None
            return facts, scan, tool, undo

        self.host.run_in_background(work, self._apply)

    def _apply(self, got) -> None:
        self._loading = False
        self.loadingChanged.emit()
        if self._again:
            self._again = False
            self.refresh()
            return
        self._facts, self._scan, self._tool, self._rebuild_undo = got
        self._render()
        if not self._edit_text:
            self._read_text()

    def _render(self) -> None:
        self._state = self.presenter.page(
            self._facts, self._scan, game_running=self.host.game_running, tool_to_allow=self._tool
        )
        groups = {g.kind: g for g in self._state.groups}
        self._packages.set_rows([_row(r) for r in (groups["package"].rows if "package" in groups else ())])
        self._natives.set_rows([_row(r) for r in (groups["native"].rows if "native" in groups else ())])
        self._notices.set_rows(self._state.notices)
        self.changed.emit()

    # ---- small helpers for changes
    def _profile(self) -> Path | None:
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            self.notifier.toast(tr("Pick a profile first."), error=True)
            return None
        if self.host.busy:
            self.notifier.toast(
                tr("Wait for the current job. The profile is not changed while something runs."), error=True
            )
            return None
        return Path(profile)

    def _entry(self, index: int) -> dict | None:
        return next((e for e in (self._facts.entries if self._facts else ()) if e["index"] == index), None)

    def _changed(self, note: str, toast: str) -> None:
        """A change was written: tell the host, read the page again, offer Undo."""
        self.host.profile_changed(note)
        self.refresh()
        profile = self.host.profile
        self.notifier.toast_action(toast, self._words["undo"], lambda p=profile: self._undo_last(p))

    def _undo_last(self, profile) -> None:
        try:
            profile_mods.undo_last_change(profile)
        except Exception as e:
            self.notifier.toast(tr("Could not undo: {why}").format(why=e), error=True)
            return
        self.host.profile_changed("profile: undid the last change")
        self.refresh()
        self.notifier.toast(tr("Undone"))

    # ---- rows
    @Slot(int, bool)
    def setEnabled(self, index: int, on: bool) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            self.refresh()
            return
        try:
            mod_service.set_mod_options(profile, index, {"enabled": bool(on)}, loc=self.host.locations)
        except Exception as e:
            self.notifier.toast(tr("Could not change the profile: {why}").format(why=e), error=True)
            self.refresh()
            return
        name = entry["name"]
        self._changed(
            f"profile: {name} {'on' if on else 'off'}",
            (tr("{name} is loaded again") if on else tr("{name} is off: kept in the profile, me3 skips it")).format(
                name=name
            ),
        )

    @Slot(int)
    def remove(self, index: int) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return
        plan = profile_mods.removal(profile, entry, loc=self.host.locations, scan=self._scan)
        words = self.presenter.removal(profile, plan)

        def answered(ok: bool, recycle: bool) -> None:
            if not ok or self.host.busy:
                return
            fresh = self._entry(index)
            if fresh is None or fresh["name"] != entry["name"]:
                self.notifier.toast(tr("The profile changed; look again before removing."), error=True)
                self.refresh()
                return
            name = entry["name"]

            def job(_setup, loc):
                from roundtable_souls.platform import logging as run_logging

                run_logging.start_log(f"launcher: remove {name}", loc.game.key)
                profile_mods.remove_entry(profile, index, plan, delete_folder=recycle, loc=self.host.locations)

            self.host.run_job(job, tr("Removing {name}...").format(name=name))

        self.notifier.ask(words, answered, destructive=True)

    @Slot(int)
    def removeHolder(self, index: int) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return
        needs = profile_mods.holder_dependents(profile, entry)

        def answered(ok: bool, _option: bool) -> None:
            if not ok:
                return
            try:
                profile_mods.remove_holder(profile, index, entry, needs, loc=self.host.locations)
            except Exception as e:
                self.notifier.toast(tr("Could not remove: {why}").format(why=e), error=True)
                return
            self._changed(
                f"profile: removed {entry['name']} (a folder of mods)",
                tr("'{name}' is out of the profile. Nothing in the game changes.").format(name=entry["name"]),
            )

        self.notifier.ask(self.presenter.holder(profile, entry["name"], needs), answered)

    @Slot(int, int)
    def moveTo(self, index: int, to: int) -> None:
        """Move an entry to position `to` (0-based, among its kind as shown)."""
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return
        try:
            plan = profile_mods.move_entry(profile, entry["kind"], index, to, loc=self.host.locations)
        except Exception as e:
            self.notifier.toast(tr("Could not change the load order: {why}").format(why=e), error=True)
            self.refresh()
            return
        if plan.text is None:
            if plan.problem:
                refusal = self.presenter.move_refused(plan.problem)
                by = (
                    next((e["index"] for e in self._facts.entries if e["name"] == plan.decided_by), -1)
                    if self._facts
                    else -1
                )
                if by >= 0:
                    self.notifier.toast_action(
                        refusal.body,
                        self.presenter.edit_options_text(),
                        lambda: self.optionsRequested.emit(by),
                        error=True,
                    )
                else:
                    self.notifier.toast(refusal.body, error=True)
            self.refresh()
            return
        self._changed(f"profile: moved {entry['name']}", tr("Load order changed"))

    @Slot(int, int)
    def moveBy(self, index: int, delta: int) -> None:
        """Ctrl+Up / Ctrl+Down and the row's Move menu: by delta places (a large delta: to the top or bottom)."""
        entry = self._entry(index)
        if entry is None or self._facts is None:
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
        combine = (self._state.parameters.state == "stacked") or None
        refusal = profile_mods.rebuild_refusal(
            profile, loc=self.host.locations, game_running=self.host.game_running, combine=combine
        )
        if refusal is not None:
            code, detail = refusal
            text = {
                profile_mods.REBUILD_GAME_RUNNING: tr(
                    "Close the game first: the rebuild rewrites files the game has open."
                ),
                profile_mods.REBUILD_BLOCKED: tr("It cannot be rebuilt now: {why}").format(why=detail),
                profile_mods.REBUILD_NOTHING: tr(
                    "Nothing to rebuild: fewer than two packs ship parameters and there is no rebuild tool."
                ),
            }[code]
            self.notifier.toast(text, error=True)
            return
        state = profile_mods.tool_state(profile, loc=self.host.locations)
        if state.problem:
            self.notifier.toast(
                tr("{tool} cannot run: {why}").format(tool=state.tool.label, why=state.problem), error=True
            )
            return

        def start() -> None:
            uses_tool = profile_mods.rebuild_uses_tool(profile, loc=self.host.locations)
            self.host.run_job(
                profile_mods.rebuild_job(profile, combine),
                tr("Rebuilding combined parameters...") if uses_tool else tr("Combining parameters..."),
            )

        if state.ready:
            start()
            return

        def answered(ok: bool, _option: bool) -> None:
            if ok:
                profile_mods.allow_tool(state.tool)
                start()

        self.notifier.ask(self.presenter.tool(state.tool), answered)

    @Slot()
    def allowTool(self) -> None:
        """The InfoBar's Allow (owner, D2): what the tool runs, then remembered once the player confirms."""
        profile = self.host.profile
        tool = self._tool
        if profile is None or tool is None:
            return

        def answered(ok: bool, _option: bool) -> None:
            if ok:
                profile_mods.allow_tool(tool)
                self.notifier.toast(tr("{tool} is allowed to run").format(tool=tool.label))
                self.refresh()

        words = self.presenter.tool(tool)
        self.notifier.ask(type(words)(**{**words.__dict__, "apply": tr("Allow")}), answered)

    @Slot()
    def undoRebuild(self) -> None:
        rec = self._rebuild_undo
        if not rec:
            return
        plan = ActivityPresenter().undo_plan(rec, busy=self.host.busy, game_running=self.host.game_running)
        if isinstance(plan, UndoRefusal):
            self.notifier.toast(f"{plan.title}. {plan.body}", error=True)
            return

        def answered(ok: bool) -> None:
            if ok:
                self.host.run_job(plan.job(self.host.locations), plan.progress)

        self.notifier.confirm(plan.title, plan.changes, plan.safety, plan.apply_text, answered)

    @Slot()
    def trimBackups(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        extra = profile_mods.tool_backups_to_trim(profile)
        if not extra:
            self.notifier.toast(
                tr("Nothing to trim: {n} or fewer backups are kept.").format(n=profile_mods.KEEP_TOOL_BACKUPS)
            )
            return

        def answered(ok: bool, _option: bool) -> None:
            if ok:
                moved = profile_mods.trim_tool_backups(profile)
                self.notifier.toast(tr("Older rebuild backups moved: {n} to the Recycle Bin.").format(n=len(moved)))
                self.refresh()

        self.notifier.ask(self.presenter.trim(extra), answered)

    @Slot()
    def fixOrder(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        from roundtable_souls.mods import order as mod_order

        problem = mod_order.fix(profile, loc=self.host.locations)
        if problem:
            self.notifier.toast(tr("The order could not be fixed: {why}").format(why=problem), error=True)
            return
        self._changed("profile: fixed the order of the mod that must stay last", tr("Load order fixed"))

    @Slot(bool)
    def setShowAll(self, on: bool) -> None:
        self._show_all = on
        self.changed.emit()

    # ---- InfoBars
    @Slot(str)
    def closeNotice(self, key: str) -> None:
        self.presenter.close_notice(key)
        self._render()

    @Slot(str)
    def noticeAction(self, key: str) -> None:
        if key == "stale":
            self.rebuild()
        elif key == "allow-tool":
            self.allowTool()

    # ---- the header
    @Slot()
    def openProfileFolder(self) -> None:
        profile = self.host.profile
        if profile is not None:
            self.host.open_path(Path(profile).parent)

    @Slot(bool)
    def install(self, from_folder: bool) -> None:
        if self._profile() is not None:
            self.host.install(from_folder)

    @Slot(list)
    def installDropped(self, urls: list) -> None:
        """Files dropped from Explorer: the launcher's install flow takes them in turn."""
        from PySide6.QtCore import QUrl

        paths = [Path(QUrl(u).toLocalFile()) for u in urls if QUrl(u).isLocalFile()]
        if paths and self._profile() is not None:
            self.host.install_paths(paths)

    # ---- the dialogs (Mod options, Profile settings, Versions, Add existing, attaching a config file)
    dialogRequested = Signal(str, int)  # which dialog, the entry it is about (-1: none)

    @Slot(int)
    def openOptions(self, index: int) -> None:
        if self._entry(index) is not None:
            self.dialogRequested.emit("options", index)

    @Slot()
    def openProfileSettings(self) -> None:
        if self.host.profile is not None:
            self.dialogRequested.emit("profile-settings", -1)

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
        if self._entry(index) is not None:
            self.dialogRequested.emit("attach", index)

    @Slot()
    def deleteProfile(self) -> None:
        profile = self.host.profile
        refusal = self.presenter.delete_refusal(
            profile_mods.delete_refusal(self._setup_like(), self.host.busy), Path(profile).stem if profile else ""
        )
        if refusal is not None:
            self.notifier.toast(f"{refusal.title}. {refusal.body}", error=True)
            return
        assert profile is not None

        def answered(ok: bool, _option: bool) -> None:
            if not ok:
                return
            try:
                gone = mod_service.delete_profile(profile)
            except Exception as e:
                self.notifier.toast(tr("Could not delete: {why}").format(why=e), error=True)
                return
            self.host.profile_deleted(Path(profile), gone)
            self.notifier.toast(
                tr("Profile {name} deleted: the .me3 is in Deleted profiles").format(name=Path(profile).stem)
            )
            self.refresh()

        self.notifier.ask(self.presenter.delete_profile(profile), answered, destructive=True)

    def _setup_like(self):
        """The host's current setup as delete_refusal reads it (profile and kind)."""
        return getattr(self.host, "setup", None)

    # ---- Edit as text
    editText = Property(bool, lambda self: self._edit_text, notify=textChanged)
    me3Text = Property(str, lambda self: self._text, notify=textChanged)
    textDirty = Property(bool, lambda self: self._text != self._saved_text, notify=textChanged)
    me3Error = Property(str, lambda self: self._parse_error(), notify=textChanged)

    def _read_text(self) -> None:
        profile = self.host.profile
        try:
            raw = Path(profile).read_bytes() if profile else b""
        except OSError:
            raw = b""
        text = raw.decode("utf-8", errors="replace")
        self._crlf = "\r\n" in text
        self._text = self._saved_text = text.replace("\r\n", "\n")
        self.textChanged.emit()

    def _parse_error(self) -> str:
        try:
            tomllib.loads(self._text)
        except tomllib.TOMLDecodeError as e:
            return tr("Does not parse as a profile: {why}. Save is off until it does.").format(why=e)
        return ""

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
        text = self._text.replace("\n", "\r\n") if self._crlf else self._text
        try:
            mod_service.save_profile_text(profile, text)
        except Exception as e:
            self.notifier.toast(tr("Could not save the profile: {why}").format(why=e), error=True)
            return
        self._saved_text = self._text
        self.textChanged.emit()
        self._changed("profile: saved as text", tr(".me3 saved  ·  a Version was kept"))

    @Slot()
    def discardText(self) -> None:
        self._text = self._saved_text
        self.textChanged.emit()

    def entry_text(self) -> str:
        """The profile as read (tests)."""
        profile = self.host.profile
        return profile_edit.read_text(Path(profile)) if profile else ""
