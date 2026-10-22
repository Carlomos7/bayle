"""The Mods page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). It holds no
decisions: what to show comes from the presenter, what a change does from services/profile_mods.py. Reading the
profile and the Load order scan runs on the job runner's worker thread and only the presenter's output reaches QML,
on the GUI thread; rebuilds and removals run as logged jobs of the host (the window that owns the job runner);
results reach the user through the Notifier."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from bayle.mods import conflicts as mod_overview
from bayle.mods import move_in, profile_edit
from bayle.mods import order as mod_order
from bayle.platform import logging as run_logging
from bayle.platform.text import tr
from bayle.services import coop as coop_service
from bayle.services import mods as mod_service
from bayle.services import profile_mods
from bayle.services import profile_rename as rename_service
from bayle.services import shared_mods as library_service
from bayle.ui.models import RowsModel, plain
from bayle.ui.notifications import Notifier
from bayle.ui.pages.activity.presenter import ActivityPresenter
from bayle.ui.pages.activity.presenter import Refusal as UndoRefusal
from bayle.ui.pages.mods import load_order, take_over
from bayle.ui.pages.mods.install_adapter import InstallAdapter
from bayle.ui.pages.mods.presenter import ModsPresenter, ModsState, Pick, Refusal
from bayle.ui.refresh import Refresher, stat_key

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
    def locations(self) -> Any: ...
    @property
    def profile(self) -> Path | None:
        """The profile the page shows (the current profile's), or None."""

    @property
    def settings(self) -> Any: ...
    @property
    def game(self) -> Any: ...
    def run_job(self, job, status: str, on_done=None) -> None: ...
    def run_in_background(self, work, on_result) -> None: ...
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
        self._facts: profile_mods.PageFacts | None = None
        self._drag: dict = {}
        self._scan: dict | None = None
        self._tool: Any = None
        self._rebuild_undo: dict | None = None
        self._recovered: tuple[str, ...] = ()  # interrupted changes put right as the page read the profile
        self._overhaul: tuple[bool, dict | None, bool] = (False, None, False)  # switch on, the profile's, leftovers
        self._picks: dict[str, Any] = {}  # an open tick list's key -> what runs with the ticked indexes
        self._duplicated: tuple[int, int] = (0, 0)  # mods kept as Separate copies in several profiles, and their size
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
    panel = Property(dict, lambda self: plain(load_order.panel(self._scan, self._show_all)), notify=changed)
    rebuildUndo = Property(str, lambda self: self._undo_label(), notify=changed)
    words = Property(dict, lambda self: self._words, constant=True)
    packages = Property(QObject, lambda self: self._packages, constant=True)
    natives = Property(QObject, lambda self: self._natives, constant=True)
    notices = Property(QObject, lambda self: self._notices, constant=True)
    loading = Property(bool, lambda self: self._loading, notify=loadingChanged)
    showAll = Property(bool, lambda self: self._show_all, notify=changed)
    hasProfile = Property(bool, lambda self: self._facts is not None and not self._facts.error, notify=changed)
    overhaul = Property(dict, lambda self: plain(self.presenter.overhaul_menu(*self._overhaul)), notify=changed)
    installer = Property(QObject, lambda self: self._install, constant=True)

    @Slot()
    def createProfile(self) -> None:
        self.host.request_new_profile()

    def _group(self, kind: str) -> dict:
        group = next((g for g in self._state.groups if g.kind == kind), None)
        return plain(group) if group else {"title": "", "count": "", "empty": "", "lines": [], "rows": []}

    def _undo_label(self) -> str:
        if not self._rebuild_undo:
            return ""
        from bayle.mods import undo as mod_undo

        return tr(mod_undo.label(self._rebuild_undo.get("undo")))

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
        order = getattr(self._state, "load_order", None)
        stays = getattr(order, "stays_last", None)
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
            "loc": self.host.locations,
            "settings": self.host.settings,
            "game": self.host.game,
            "busy": self.host.busy,  # a running job holds the folder: nothing of it is interrupted
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

    def _build(self, snap: dict):
        profile, launch, loc = snap["profile"], snap["launch"], snap["loc"]
        settings, game, recover = snap["settings"], snap["game"], not snap["busy"]
        if profile is None or not Path(profile).is_file():
            return None, None, None, None, (), (False, None, False)
        try:
            self._seamless_found = coop_service.game_folder_seamless(launch) if launch is not None else None
        except Exception:  # a game folder that cannot be read: nothing to offer
            self._seamless_found = None
        recovered = tuple(mod_service.recover_interrupted(profile, timeout=0.5)) if recover else ()
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
        try:
            on = mod_service.overhaul_preview_on(loc)
            overhaul = (
                on,
                mod_service.profile_overhaul(profile, loc=loc) if on else None,
                bool(mod_service.overhaul_leftovers(profile, loc=loc)) if on else False,
            )
        except Exception:  # an overhaul config or record that does not read: no overhaul entries
            overhaul = (False, None, False)
        return facts, scan, tool, undo, recovered, overhaul

    def _apply(self, got) -> None:
        before = self._facts.profile if self._facts is not None else None
        self._facts, self._scan, self._tool, self._rebuild_undo, recovered, self._overhaul = got
        now = self._facts.profile if self._facts is not None else None
        self._recovered = (self._recovered if now == before else ()) + recovered  # another profile: its own lines
        self._render()
        if not self._edit_text:
            self._read_text()
        self._install.after_job()
        self._look_for_duplicates()

    def _render(self) -> None:
        self._state = self.presenter.page(
            self._facts,
            self._scan,
            game_running=self.host.game_running,
            tool_to_allow=self._tool,
            recovered=self._recovered,
            seamless=self._seamless_found.kind if getattr(self, "_seamless_found", None) else "",
            no_profiles=not self.host.profiles(),
            duplicated=self._duplicated,
        )
        groups = {g.kind: g for g in self._state.groups}
        self._packages.set_rows([_row(r) for r in (groups["package"].rows if "package" in groups else ())])
        self._natives.set_rows([_row(r) for r in (groups["native"].rows if "native" in groups else ())])
        self._notices.set_rows(self._state.notices)
        self.changed.emit()

    def _look_for_duplicates(self) -> None:
        """The disk hint: mods kept as the same Separate copy in several profiles, worked out after the page shows."""
        if self._facts is None:
            return
        loc = self.host.locations

        def got(found) -> None:
            if found != self._duplicated:
                self._duplicated = found
                self._render()

        self.host.run_in_background(lambda: library_service.duplicates(loc), got)

    # ---- the Library (opt-in sharing of game-file mods between profiles)
    @Slot(int)
    def share(self, index: int) -> None:
        profile, entry = self._ready(), self._entry(index)
        if profile is None or entry is None:
            return
        name = entry["name"]

        def answered(ok: bool, _option: bool) -> None:
            if ok and not self.host.busy:
                self._library_job(
                    tr("Sharing {name}...").format(name=name),
                    f"share {name}",
                    lambda loc: library_service.share(profile, [index], loc=loc),
                )

        self.notifier.ask(self.presenter.share_confirm([name]), answered)

    @Slot(int)
    def separate(self, index: int) -> None:
        profile, entry = self._ready(), self._entry(index)
        if profile is None or entry is None:
            return
        loc = self.host.locations
        ref = library_service.shared_ref(profile, entry, loc=loc)
        if ref is None:
            return
        name = library_service.display_name(ref[0], loc=loc)

        def answered(ok: bool, _option: bool) -> None:
            if ok and not self.host.busy:
                self._library_job(
                    tr("Copying {name}...").format(name=name),
                    f"separate copy of {name}",
                    lambda job_loc: library_service.separate(profile, [index], loc=job_loc),
                )

        size = library_service.version_size(*ref, loc=loc)
        self.notifier.ask(self.presenter.separate_confirm(name, size), answered)

    @Slot(int)
    def useInOthers(self, index: int) -> None:
        profile, entry = self._ready(), self._entry(index)
        if profile is None or entry is None:
            return
        loc = self.host.locations
        ref = library_service.shared_ref(profile, entry, loc=loc)
        if ref is None:
            return
        found = library_service.candidates(profile, ref[0], loc=loc)
        if not found:
            self.notifier.toast(tr("There are no other profiles."), error=True)
            return
        name = library_service.display_name(ref[0], loc=loc)
        rows = [self.presenter.use_row(c.profile.stem, c.has_copy, c.uses) for c in found]

        def chosen(indexes: list[int]) -> None:
            targets = {found[i].profile: True for i in indexes}
            if targets and not self.host.busy:
                self._library_job(
                    tr("Linking {name}...").format(name=name),
                    f"use {name} in other profiles",
                    lambda job_loc: library_service.use_in(ref[0], ref[1], targets, loc=job_loc),
                )

        self._pick(self.presenter.use_pick(name), rows, chosen)

    def _library_job(self, status: str, what: str, work) -> None:
        def job(_launch, loc):
            run_logging.start_log(f"launcher: {what}", loc.game.key)
            try:
                work(loc)
                run_logging.log(f"done: {what}")
            except Exception as e:  # the Library refuses with its reason and changes nothing
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, status)

    @Slot(result=list)
    def libraryList(self) -> list:
        try:
            return self.presenter.library(library_service.listing(self.host.locations))
        except Exception:
            return []

    @Slot()
    def removeUnused(self) -> None:
        if self._ready() is None:
            return
        loc = self.host.locations

        def work():
            return library_service.unused(loc)

        def got(result) -> None:
            found, why = result
            if why:
                self.notifier.toast(why, error=True)
            elif not found:
                self.notifier.toast(tr("Every shared version is in use."))
            else:
                size = sum(v.size for _m, v in found)

                def answered(ok: bool, _option: bool) -> None:
                    if ok and not self.host.busy:
                        self._library_job(
                            tr("Removing unused versions..."),
                            "remove unused library versions",
                            lambda job_loc: library_service.remove_unused(loc=job_loc),
                        )

                self.notifier.ask(self.presenter.clean_confirm(len(found), size), answered, destructive=True)

        self.host.run_in_background(work, got)

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
            (tr("{name} is on again") if on else tr("{name} is off. It stays in the profile and me3 skips it.")).format(
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

        def answered(ok: bool, recycle: bool, quiet: bool = False) -> None:
            if not ok or self.host.busy:
                return
            fresh = self._entry(index)
            if fresh is None or fresh["name"] != entry["name"]:
                self.notifier.toast(tr("The profile changed; look again before removing."), error=True)
                self.refresh()
                return
            name = entry["name"]

            def job(_launch, loc):
                from bayle.platform import logging as run_logging

                run_logging.start_log(f"launcher: remove {name}", loc.game.key)
                out = profile_mods.remove_entry(profile, index, plan, delete_folder=recycle, loc=self.host.locations)
                undone.append(out["undo"])

            def finished(ok: bool) -> None:
                if not (ok and undone):
                    return
                self.notifier.toast_action(
                    tr("Removed {name}").format(name=name), self._words["undo"], lambda: self._undo_removal(undone[0])
                )

            undone: list[dict] = []
            if quiet:
                self.host.run_job(job, tr("Removing {name}...").format(name=name), on_done=finished)
            else:
                self.host.run_job(job, tr("Removing {name}...").format(name=name))

        if profile_mods.removal_undoable(profile, plan, loc=self.host.locations):
            answered(True, plan.can_recycle, True)  # Undo brings it all back: no confirm
        else:
            self.notifier.ask(words, answered, destructive=True)

    def _undo_removal(self, undo: dict) -> None:
        try:
            profile_mods.undo_removal(undo, loc=self.host.locations)
        except Exception as e:
            self.notifier.toast(tr("Could not undo: {why}").format(why=e), error=True)
            return
        self.host.profile_changed(f"profile: restored {undo.get('name')}")
        self.refresh()
        self.notifier.toast(tr("Undone"))

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
                tr("{name} is out of the profile. Nothing in the game changes.").format(name=entry["name"]),
            )

        self.notifier.ask(self.presenter.holder(profile, entry["name"], needs), answered)

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

    @Slot(int)
    def beginDrag(self, index: int) -> None:
        """A drag starts: read the profile text and the stays-last target once, so the drop spots are judged in memory
        (no disk read while the pointer moves). The real check and the write happen on drop (moveTo)."""
        self._drag = {}
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None or self.host.busy:
            return
        try:
            loc = self.host.locations
            self._drag = {
                "profile": profile,
                "text": profile_edit.read_text(Path(profile)),
                "tgt": mod_order.target(Path(profile), loc),
                "kind": entry["kind"],
                "memo": {},
            }
        except Exception:
            self._drag = {}

    @Slot()
    def endDrag(self) -> None:
        self._drag = {}

    @Slot(int, int, result=str)
    def dropReason(self, index: int, to: int) -> str:
        """Why dropping entry `index` at position `to` would be refused (words for the drop spot), or "" when allowed.
        The same rules moveTo applies (mods.order.move), over the text read when the drag began."""
        if self.host.busy:
            return self.presenter.move_busy().body
        d = self._drag
        if not d:
            return ""
        if to not in d["memo"]:
            try:
                plan = mod_order.move(Path(d["profile"]), d["text"], d["kind"], index, to, d["tgt"])
                d["memo"][to] = plan.problem if plan.text is None and plan.problem else ""
            except Exception as e:
                d["memo"][to] = str(e)
        return d["memo"][to]

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
                    "Close the game first. The rebuild rewrites files the game has open."
                ),
                profile_mods.REBUILD_BLOCKED: tr("It cannot be rebuilt now: {why}").format(why=detail),
                profile_mods.REBUILD_NOTHING: tr(
                    "Nothing to rebuild. Fewer than two packs ship parameters and there is no rebuild tool."
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
                tr("Nothing to trim. {n} or fewer backups are kept.").format(n=profile_mods.KEEP_TOOL_BACKUPS)
            )
            return

        def answered(ok: bool, _option: bool) -> None:
            if ok:
                moved = profile_mods.trim_tool_backups(profile)
                self.notifier.toast(tr("{n} older rebuild backups moved to the Recycle Bin.").format(n=len(moved)))
                self.refresh()

        self.notifier.ask(self.presenter.trim(extra), answered)

    @Slot()
    def fixOrder(self) -> None:
        profile = self._profile()
        if profile is None:
            return
        from bayle.mods import order as mod_order

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
        self.presenter.close_notice(key, str(self._facts.profile) if self._facts is not None else "")
        self._render()

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
        profile, facts = self.host.profile, self._facts
        if profile is None or facts is None or self.host.busy:
            return
        old, kind, loc = Path(profile), facts.folder.kind, self.host.locations
        if kind == "misnamed":
            if why := rename_service.rename_folder_refusal(old, loc=loc):
                self.notifier.toast(why, error=True)
                return
            self._folder_job(lambda l: rename_service.rename_folder(old, loc=l), tr("Renaming the folder..."))
        elif kind == "crowded":
            plan = rename_service.split_preview(old, loc=loc)
            if not plan.ok:
                self.notifier.toast(" ".join(plan.refusals), error=True)
                return

            def answered(ok: bool) -> None:
                if ok:
                    self._folder_job(lambda l: rename_service.split_folder(old, loc=l), tr("Splitting the folder..."))

            self.notifier.confirm(*self.presenter.split_confirm(plan.profiles, plan.copies, plan.moves), answered)

    def _dll_folders_action(self) -> None:
        """Give each loose DLL mod a folder of its own, after a confirmation (a logged job, Undo in Activity)."""
        profile = self.host.profile
        if profile is None or self.host.busy:
            return
        old, loc = Path(profile), self.host.locations
        plan = profile_mods.dll_folders_preview(old, loc=loc)
        if not plan.ok:
            self.notifier.toast(" ".join(plan.refusals) or tr("Every DLL is in its own folder."), error=True)
            return

        def answered(ok: bool) -> None:
            if ok:
                self._folder_job(lambda l: profile_mods.put_dlls_in_folders(old, loc=l), tr("Moving the DLLs..."))

        self.notifier.confirm(
            *self.presenter.dll_folders_confirm(len(plan.moves), plan.files_moved, plan.files_copied), answered
        )

    def _folder_job(self, work, busy_text: str) -> None:
        def job(_launch, loc):
            run_logging.start_log("launcher: fix the profile's folder", loc.game.key)
            try:
                work(loc)
            except (rename_service.FolderError, profile_mods.dll_folders.DllFolderError) as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, busy_text)

    def _seamless_action(self) -> None:
        """Move Seamless Co-op from the game folder into this profile, or clean up what it left there (a job; the
        files go to the Recycle Bin, the profile's own copy and the settings file in use are never touched)."""
        found, launch = getattr(self, "_seamless_found", None), self.host.launch_profile
        if found is None or launch is None or self.host.busy or self.host.game_running:
            return
        move = found.kind == "move"
        changes = [
            tr("{n} file(s) in {folder} {what}").format(
                n=len(found.files),
                folder=found.folder,
                what=tr("move into this profile, settings included") if move else tr("go to the Recycle Bin"),
            )
        ]
        if found.launcher is not None:
            changes.append(
                tr("{name}, Seamless Co-op's own launcher, goes to the Recycle Bin").format(name=found.launcher.name)
            )

        def answered(ok: bool) -> None:
            if not ok:
                return

            def job(_launch, _loc):
                run_logging.start_log("launcher: seamless co-op in the game folder", launch.game.key)
                try:
                    if move:
                        coop_service.move_seamless_into_profile(launch, found, run_logging.log)
                    else:
                        coop_service.clean_up_game_folder_seamless(launch, found, run_logging.log)
                except Exception as e:
                    run_logging.log(f"error: {e}")
                    raise SystemExit(1) from e

            self.host.run_job(job, tr("Moving Seamless Co-op...") if move else tr("Cleaning up the game folder..."))

        self.notifier.confirm(
            tr("Move Seamless Co-op into this profile?") if move else tr("Clean up the game folder?"),
            changes,
            tr("The profile is written first with a Version you can undo; if that fails, nothing moves.")
            if move
            else tr("Your profile's own copy is not touched."),
            tr("Move") if move else tr("Clean up"),
            answered,
        )

    @Slot()
    def copyFingerprint(self) -> None:
        from PySide6.QtGui import QGuiApplication

        facts = self._facts
        if facts is None or facts.fingerprint is None:
            return
        QGuiApplication.clipboard().setText(self.presenter.fingerprint(facts.fingerprint, facts.regulation))
        self.notifier.toast(tr("Fingerprint copied"))

    # ---- overhauls installed with the launcher (preview; owner, D4 A: shown while the switch is on)
    pickRequested = Signal(str, dict, list)  # a tick list: its key, its words (presenter.Pick), the rows' labels

    def _refuse(self, refusal: Refusal) -> None:
        self.notifier.toast(f"{refusal.title}. {refusal.body}", error=True)

    def _ready(self) -> Path | None:
        """The profile to change, or None (with the reason said) while a job runs."""
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job to finish."), error=True)
            return None
        return self._profile()

    def _pick(self, words: Pick, rows: list[str], then) -> None:
        key = f"pick-{len(self._picks) + 1}"
        self._picks[key] = then
        self.pickRequested.emit(key, plain(words), rows)

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
        profile = self._ready()
        if profile is None:
            return
        folder = self.host.pick_folder(self.presenter.overhaul_folder_title())
        if folder is None:
            return
        loc = self.host.locations

        def work():
            try:
                return mod_service.preview_overhaul_install(profile, folder, loc=loc), ""
            except Exception as e:  # not a download the launcher installs: said, nothing written
                return None, str(e)

        def got(result) -> None:
            preview, why = result
            if preview is None:
                self._refuse(self.presenter.overhaul_unreadable(folder, why))
                return
            words = self.presenter.overhaul_install(profile, preview)
            if isinstance(words, Refusal):
                self._refuse(words)
                return

            def answered(ok: bool, _option: bool) -> None:
                if not ok or self.host.busy:
                    return

                def job(_launch, loc):
                    from bayle.platform import logging as run_logging

                    verb = "update" if preview.update else "install"
                    run_logging.start_log(f"launcher: {verb} overhaul {preview.label}", loc.game.key)
                    mod_service.install_overhaul(preview, loc=loc)

                self.host.run_job(job, self.presenter.overhaul_installing(preview))

            self.notifier.ask(words, answered)

        self.host.run_in_background(work, got)

    @Slot()
    def removeOverhaul(self) -> None:
        profile, has = self._ready(), self._overhaul[1]
        if profile is None or not has:
            return
        loc, label = self.host.locations, has["label"]

        def preview_and_ask(chosen: list) -> None:
            try:
                preview = mod_service.preview_overhaul_removal(profile, loc=loc, legacy_choices=chosen)
            except Exception as e:
                self._refuse(self.presenter.overhaul_remove_failed(label, str(e)))
                return
            words = self.presenter.overhaul_remove(profile, label, preview)
            if isinstance(words, Refusal):
                self._refuse(words)
                return

            def answered(ok: bool, switch_back: bool) -> None:
                if not ok or self.host.busy:
                    return
                final = preview
                if switch_back:
                    final = mod_service.preview_overhaul_removal(
                        profile, loc=loc, revert_asked=True, legacy_choices=chosen
                    )
                    if not final.ok:
                        self._refuse(self.presenter.overhaul_remove_failed(label, " ".join(final.refusals)))
                        return

                def job(_launch, loc):
                    from bayle.platform import logging as run_logging

                    run_logging.start_log(f"launcher: remove overhaul {label}", loc.game.key)
                    mod_service.remove_overhaul(final)

                self.host.run_job(job, self.presenter.overhaul_removing(label))
                if has["legacy"]:
                    later = self.presenter.overhaul_leftovers_later(label)
                    self.notifier.toast(f"{later.title}. {later.body}")

            self.notifier.ask(words, answered, destructive=True)

        choices = mod_service.legacy_overhaul_choices(profile, loc=loc) if has["legacy"] else []
        if choices:  # what its installer changed: offered unticked (owner, 3.22-A)
            self._pick(
                self.presenter.overhaul_put_back(label),
                [text for text, _ in choices],
                lambda ticked: preview_and_ask([choices[i][1] for i in ticked]),
            )
        else:
            preview_and_ask([])

    @Slot()
    def takeOverOverhaul(self) -> None:
        take_over.start(self)

    @Slot()
    def cleanLeftovers(self) -> None:
        profile = self._ready()
        if profile is None:
            return
        left = mod_service.overhaul_leftovers(profile, loc=self.host.locations)
        folders = [x for x in left if not x.backups]
        backups = [x for x in left if x.backups]

        def ask_backups(picked: list, rest: list) -> None:
            if rest:  # last, and one at a time: the only copy of the profile from before the overhaul
                x = rest[0]
                self.notifier.ask(
                    self.presenter.leftover_backups(x),
                    lambda ok, _o: ask_backups([*picked, x.path] if ok else picked, rest[1:]),
                    destructive=True,
                )
                return
            if not picked or self.host.busy:
                return

            def job(_launch, loc):
                from bayle.platform import logging as run_logging

                run_logging.start_log("launcher: clean up overhaul installer leftovers", loc.game.key)
                mod_service.remove_overhaul_leftovers(picked)

            self.host.run_job(job, self.presenter.leftovers_moving())

        if folders:
            self._pick(
                self.presenter.leftovers(bool(backups)),
                [x.label for x in folders],
                lambda ticked: ask_backups([folders[i].path for i in ticked], backups),
            )
        else:
            ask_backups([], backups)

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
        entry, profile = self._entry(index), self.host.profile
        if entry is None or profile is None or not entry.get("path"):
            return ""
        folder = profile_edit.resolve(profile, entry["path"])
        return (folder if entry["kind"] == "package" else folder.parent).name

    renamePreviewReady = Signal(dict)

    @Slot(int, str)
    def requestRenamePreview(self, index: int, name: str) -> None:
        """renamePreview off the UI thread; the answer comes on renamePreviewReady."""
        self.host.run_in_background(
            lambda: {**self.renamePreview(index, name), "name": name}, self.renamePreviewReady.emit
        )

    def renamePreview(self, index: int, name: str) -> dict:
        """Whether renaming to `name` is allowed and what it would change: {ok, lines, refusals}."""
        entry, profile = self._entry(index), self.host.profile
        if entry is None or profile is None:
            return {"ok": False, "lines": [], "refusals": []}
        try:
            pre = profile_mods.rename_preview(profile, index, name, loc=self.host.locations)
        except Exception as e:
            return {"ok": False, "lines": [], "refusals": [str(e)]}
        return {"ok": pre.ok, "lines": list(pre.lines), "refusals": list(pre.refusals)}

    @Slot(int, str)
    def rename(self, index: int, name: str) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None or self.host.busy:
            return
        old, loc = entry["name"], self.host.locations

        def job(_launch, _loc):
            from bayle.platform import logging as run_logging

            run_logging.start_log(f"launcher: rename {old} to {name}", loc.game.key)
            profile_mods.rename_mod(profile, index, name, loc=loc)

        self.host.run_job(job, tr("Renaming {name}...").format(name=old))

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
        entry, profile = self._entry(index), self.host.profile
        if entry is None or profile is None:
            return {}
        facts = profile_mods.options_facts(profile, entry)
        init = entry.get("initializer") or {}
        delay = init.get("delay") if isinstance(init.get("delay"), dict) else None
        return {
            "index": index,
            "name": entry["name"],
            "kind": entry["kind"],
            "enabled": entry.get("enabled", True) is not False,
            "id": entry.get("id") or "",
            "loadAfter": [
                {"id": str(d["id"]), "optional": bool(d.get("optional"))} for d in entry.get("load_after") or []
            ],
            "loadBefore": [
                {"id": str(d["id"]), "optional": bool(d.get("optional"))} for d in entry.get("load_before") or []
            ],
            "optional": bool(entry.get("optional")),
            "loadEarly": bool(entry.get("load_early")),
            "initKind": 1 if init.get("function") else 2 if delay is not None else 0,
            "initValue": str(init.get("function") or (delay or {}).get("ms", "") or ""),
            "finalizer": str(entry.get("finalizer") or ""),
            "others": list(facts.others),
            "overlay": -1 if facts.overlay is None else int(facts.overlay),
            "rebuildFile": facts.rebuild_file,
            "configs": list(self._facts.configs.get(index, ())) if self._facts else [],
        }

    @Slot(int, dict)
    def saveOptions(self, index: int, chosen: dict) -> None:
        profile, entry = self._profile(), self._entry(index)
        if profile is None or entry is None:
            return
        opts: dict = {
            "enabled": bool(chosen.get("enabled", True)),
            "load_after": [{"id": d["id"], "optional": bool(d.get("optional"))} for d in chosen.get("loadAfter") or []],
            "load_before": [
                {"id": d["id"], "optional": bool(d.get("optional"))} for d in chosen.get("loadBefore") or []
            ],
        }
        if entry["kind"] == "package":
            opts["id"] = str(chosen.get("id") or "").strip()
        else:
            opts["optional"] = bool(chosen.get("optional"))
            opts["load_early"] = bool(chosen.get("loadEarly"))
            opts["finalizer"] = str(chosen.get("finalizer") or "").strip()
            kind, value = int(chosen.get("initKind") or 0), str(chosen.get("initValue") or "").strip()
            if kind == 2 and value and not value.isdigit():
                self.notifier.toast(tr("The wait is a number of milliseconds."), error=True)
                return
            opts["initializer"] = (
                {"function": value}
                if kind == 1 and value
                else {"delay": {"ms": int(value)}}
                if kind == 2 and value
                else None
            )
        overlay = chosen.get("overlay")
        try:
            profile_mods.save_options(
                profile,
                index,
                entry,
                opts,
                loc=self.host.locations,
                overlay=None if overlay in (None, -1) else bool(overlay),
                rebuild_file=str(chosen.get("rebuildFile") or "").strip(),
            )
        except Exception as e:
            self.notifier.toast(tr("Could not save the options: {why}").format(why=e), error=True)
            self.refresh()
            return
        self._changed(
            f"profile: options saved for {entry['name']}", tr("{name}: options saved").format(name=entry["name"])
        )

    # ---- Profile settings
    def _heap_shown(self) -> bool:
        """Whether me3 uses a heap size for this game (game.catalog)."""
        return bool(getattr(self.host.locations.game, "me3_heap_setting", True))

    @Slot(result=dict)
    def settingsFor(self) -> dict:
        profile = self.host.profile
        if profile is None:
            return {}
        vals = mod_service.read_profile_settings(profile)

        def tri(value) -> int:  # 0 me3 default, 1 on, 2 off
            return {True: 1, False: 2}.get(value, 0)

        return {
            "savefile": str(vals.get("savefile") or ""),
            "start_online": tri(vals.get("start_online")),
            "disable_arxan": tri(vals.get("disable_arxan")),
            "mem_patch": tri(vals.get("mem_patch")),
            "mem_patch_heap_size": int(vals.get("mem_patch_heap_size") or 0),
            "heapApplies": profile_mods.heap_size_applies(vals),
            "heapShown": self._heap_shown(),
        }

    @Slot(str, "QVariant")
    def setSetting(self, key: str, value) -> None:
        """One me3 option; the three-way ones come as 0 (me3 default) / 1 (on) / 2 (off)."""
        profile = self._profile()
        if profile is None:
            return
        if key in ("start_online", "disable_arxan", "mem_patch"):
            value = {1: True, 2: False}.get(int(value))
        elif key == "mem_patch_heap_size":
            value = int(value) or None
        else:
            value = str(value or "").strip() or None

        def write() -> None:
            try:
                changed = mod_service.write_profile_setting(profile, key, value)
            except Exception as e:
                self.notifier.toast(tr("Could not write the profile: {why}").format(why=e), error=True)
                return
            if changed:
                from bayle.mods.profile import SETTING_TEXT

                self._changed(
                    f"profile: {key} = {value if value not in (None, '') else 'me3 default'}",
                    tr("{setting} changed: it applies at the next launch").format(setting=tr(SETTING_TEXT[key][0])),
                )

        if profile_mods.setting_needs_confirmation(key, value):
            self.notifier.ask(self.presenter.online(), lambda ok, _o: write() if ok else self.refresh())
        else:
            write()

    # ---- Versions
    @Slot(result=list)
    def versionsList(self) -> list:
        profile = self.host.profile
        if profile is None:
            return []
        return [
            {"path": str(v["path"]), "when": v["when"].strftime("%Y-%m-%d %H:%M"), "why": str(v.get("why") or "")}
            for v in profile_mods.versions(profile)
        ]

    @Slot(str)
    def restoreVersion(self, path: str) -> None:
        profile = self._profile()
        if profile is None:
            return
        try:
            before = profile_mods.restore_version(profile, path)
        except Exception as e:
            self.notifier.toast(tr("Could not restore: {why}").format(why=e), error=True)
            return
        self.host.profile_changed("profile: restored an earlier version")
        self.refresh()
        if before is not None:

            def undo() -> None:
                profile_mods.restore_version(profile, before)
                self.host.profile_changed("profile: undid a restore")
                self.refresh()

            self.notifier.toast_action(tr("The earlier version is back"), self._words["undo"], undo)

    # ---- Add existing
    @Slot(str, result=list)
    def unlistedFor(self, kind: str) -> list:
        profile = self.host.profile
        if profile is None:
            return []
        return [{"label": label, "path": str(path)} for label, path in profile_mods.unlisted(profile, kind)]

    @Slot(str, list)
    def addPaths(self, kind: str, paths: list) -> None:
        profile = self._profile()
        if profile is None or not paths:
            return
        try:
            names = profile_mods.add_existing(profile, [Path(p) for p in paths], kind, loc=self.host.locations)
        except Exception as e:
            self.notifier.toast(tr("Could not add: {why}").format(why=e), error=True)
            return
        self._changed(
            f"profile: added {', '.join(names)}",
            tr("Added {names}: they load at the next launch").format(names=", ".join(names)),
        )
        if kind == "native" and profile_mods.loose_dlls_of(profile):
            self._dll_folders_action()  # the same move the notice offers, asked right away

    @Slot()
    def deleteProfile(self) -> None:
        profile = self.host.profile
        refusal = self.presenter.delete_refusal(
            profile_mods.delete_refusal(self._launch_profile_like(), self.host.busy, loc=self.host.locations),
            Path(profile).stem if profile else "",
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
                tr("Profile {name} deleted. It is in Deleted profiles.").format(name=Path(profile).stem)
            )
            self.refresh()

        kept = profile_mods.overhaul_to_keep(profile, loc=self.host.locations)
        self.notifier.ask(self.presenter.delete_profile(profile, kept), answered, destructive=True)

    # ---- renaming and duplicating the profile (click its name in the header, or Profile > Rename / Duplicate)
    profileRenameRequested = Signal()  # the menu asked: the header opens its name field

    def _ask_profile_rename(self) -> None:
        QTimer.singleShot(0, self.profileRenameRequested.emit)  # the page may only just have been shown

    @Slot(result=str)
    def profileRenameBlock(self) -> str:
        """Why the profile can't be renamed or copied now ("" when it can): no profile, run by an installer, a job or
        the game running."""
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            return tr("Pick a profile first.")
        launch = self._launch_profile_like()
        code = rename_service.refusal(launch, self.host.busy, loc=self.host.locations)
        return self.presenter.rename_block(code, Path(profile).stem, self.host.game_running)

    @Slot(str, result=str)
    def profileNameCheck(self, name: str) -> str:
        """Why `name` can't be the profile's new name ("" when it can). Reads the profile's folder only."""
        profile = self.host.profile
        if profile is None:
            return tr("Pick a profile first.")
        if not name.strip():
            return tr("Type a new name.")
        return rename_service.name_problem(Path(profile), name) or ""

    @Slot(str, result=str)
    def renameProfile(self, name: str) -> str:
        """Rename the profile as a logged job (its Undo is in Activity). Returns why not ("" when it started)."""
        profile = self.host.profile
        block = self.profileRenameBlock()
        if block or profile is None:
            return block
        why = self.profileNameCheck(name)
        if why:
            return why
        old = Path(profile)

        def job(_launch, loc):
            run_logging.start_log(f"launcher: rename profile {old.stem} to {name.strip()}", loc.game.key)
            out = rename_service.rename(old, name, loc=loc)
            run_logging.log(f"done: {old.stem} is now {out['new']}")

        self.host.run_job(job, tr("Renaming {name}...").format(name=old.stem))
        return ""

    @Slot()
    def duplicateProfile(self) -> None:
        block = self.profileRenameBlock()
        profile = self.host.profile
        if block or profile is None:
            self.notifier.toast(block, error=True)
            return
        old = Path(profile)

        def copy(share: bool) -> None:
            def job(_launch, loc):
                run_logging.start_log(f"launcher: duplicate profile {old.stem}", loc.game.key)
                out = rename_service.duplicate(old, loc=loc, share=share)
                run_logging.log(f"done: {out['name']} is a copy of {old.stem}")

            self.host.run_job(job, tr("Copying {name}...").format(name=old.stem))

        if library_service.separate_copies(old, loc=self.host.locations):  # packages can be shared: ask, never force
            self.notifier.ask(self.presenter.duplicate_confirm(old.stem), lambda ok, share: copy(share) if ok else None)
        else:
            copy(False)

    def profile_outside(self) -> bool:
        """The profile is not in Bayle's folder, so the menu offers Move into Bayle's folder."""
        profile = self.host.profile
        return (
            profile is not None
            and Path(profile).is_file()
            and mod_service.profile_outside(self.host.locations, profile)
        )

    @Slot()
    def moveIntoLauncherFolder(self) -> None:
        """Ask, then move the profile into Bayle's folder as a logged job (its Undo is in Activity)."""
        profile = self.host.profile
        block = self.profileRenameBlock()
        if block or profile is None:
            self.notifier.toast(block, error=True)
            return
        old = Path(profile)
        plan = mod_service.move_in_plan(self.host.locations, old)
        if not plan.ok:
            self.notifier.toast(" ".join(plan.refusals), error=True)
            return
        words = self.presenter.move_in_confirm(old.stem, old.parent.name, *move_in.counts(plan))

        def answered(ok: bool) -> None:
            if ok:

                def job(_launch, loc):
                    run_logging.start_log(f"launcher: move profile {old.stem} into Bayle's folder", loc.game.key)
                    mod_service.move_into_launcher_folder(loc, old)

                self.host.run_job(job, tr("Moving {name}...").format(name=old.stem))

        self.notifier.confirm(*words, answered)

    def _launch_profile_like(self):
        """The host's current profile as delete_refusal reads it (profile and kind)."""
        return getattr(self.host, "launch_profile", None)

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
