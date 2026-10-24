"""The Install mod dialog's adapter (technical specification §8.2): the QObject InstallModDialog.qml binds to, held
by the Mods adapter. It picks or takes the mods to install, asks the engine's ModInstallService (host.features.mod_install)
to open each (it unpacks and plans in the background) and keeps the draft the dialog edits (install_presenter): every
edit stays here and goes back as InstallChoices with the install. It pauses 200 ms before asking for the replan and the
preview, keeps several drops in a queue (one dialog after another, the next once the previous install has finished)
and follows the install as a logged job of the engine. If the profile changed while the dialog was open, it asks once
more before installing into it as it is now."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bayle.errors import OperationError
from bayle.platform.text import tr
from bayle.platform.threads import as_worker
from bayle.services.mod_configs import stamp
from bayle.work.prompts import Confirm
from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from bayle_qt.notifications import Notifier
from bayle_qt.pages.mods.install_presenter import InstallDraft
from bayle_qt.pages.mods.install_presenter import words as install_words


def query(
    host: Any, work: Callable[[], Any], then: Callable[[Any], None], fail: Callable[[OperationError], None]
) -> None:
    """work() on the host's worker; then(result) on the UI thread, or fail(the refusal)."""

    def run() -> Any:
        try:
            with as_worker():  # a test host runs this inline
                return work()
        except OperationError as e:
            return e

    def landed(got: Any) -> None:
        (fail if isinstance(got, OperationError) else then)(got)

    host.run_in_background(run, landed)


def not_ready_text(e: OperationError) -> str:
    """Why the engine would not start the install (its not_ready reasons), in words."""
    reasons = {
        "plan_error": tr("the download cannot be installed"),
        "name_blank": tr("the folder name is empty"),
        "name_problem": tr("the folder name cannot be used"),
        "library_blocked": tr("this version cannot update a Shared mod"),
        "id_blank": tr("the id is empty"),
        "id_taken": tr("the id is already used by another package"),
        "nothing_loaded": tr("nothing the game loads is ticked"),
    }
    details = e.details or {}
    why = details.get("reason", "")
    if why == "overhaul_refused":
        return " ".join(details.get("refusals") or []) or tr("it cannot be set up as an overhaul")
    return reasons.get(why) or e.message


class InstallAdapter(QObject):
    viewChanged = Signal()
    openRequested = Signal()  # show the dialog

    def __init__(self, host: Any, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self._queue: list[Path] = []
        self._draft: InstallDraft | None = None  # the open install the dialog shows
        self._view: dict = {}
        self._planning = False  # a source is being unpacked
        self._refreshing = False  # a replan and preview are being asked for
        self._again = False  # an edit came in meanwhile: ask once more
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)

    view = Property(dict, lambda self: self._view, notify=viewChanged)
    words = Property(dict, lambda self: install_words(), constant=True)

    @property
    def _service(self):
        return self.host.features.mod_install

    def _say(self, e: OperationError) -> None:
        self.notifier.toast(e.message, error=True)

    # ---- taking the sources
    @Slot(bool)
    def pick(self, from_folder: bool) -> None:
        if self._profile() is None:
            return
        if from_folder:
            src = self.host.pick_folder(tr("Install a mod: pick its folder"))
        else:
            src = self.host.pick_file(
                tr("Install a mod: pick an archive or DLL"),
                tr("Mod archive or DLL (*.zip *.7z *.rar *.dll);;All files (*)"),
            )
        if src:
            self._add([Path(src)])

    @Slot(list)
    def dropped(self, urls: list) -> None:
        paths = [Path(QUrl(u).toLocalFile()) for u in urls if QUrl(u).isLocalFile()]
        if paths and self._profile() is not None:
            self._add(paths)

    def _add(self, paths: list[Path]) -> None:
        """Folders, .zip / .7z / .rar archives and DLL mods can be installed; the rest is skipped, with a toast."""

        def sorted_out(got) -> None:
            if got.skipped:
                self.notifier.toast(
                    tr("Skipped {names}: not an archive (.zip, .7z, .rar), a .dll or a folder.").format(
                        names=", ".join(Path(x).name for x in got.skipped[:4])
                    )
                )
            self._queue += [Path(x) for x in got.usable]
            self._next()

        query(self.host, lambda: self._service.sources([str(x) for x in paths]), sorted_out, self._say)

    def _profile(self) -> Path | None:
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            self.notifier.toast(tr("Pick a profile first."), error=True)
            return None
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job to finish."), error=True)
            return None
        return Path(profile)

    def after_job(self) -> None:
        """The page has read the profile again (an install finished, or anything else): open the next queued mod."""
        self._next()

    # ---- one source at a time
    def _next(self) -> None:
        if self._draft is not None or self._planning or not self._queue or self.host.busy:
            return
        profile = self.host.profile
        if profile is None or not Path(profile).is_file():
            self._queue = []
            return
        src = self._queue.pop(0)
        self._planning = True

        def failed(e: OperationError) -> None:
            self._planning = False
            if e.code == "already_listed":
                self.notifier.toast(
                    tr("Nothing to do: {name} is already installed and listed in the profile.").format(name=e.message)
                )
            elif e.code == "not_installable":
                self.notifier.toast(
                    tr("{name} is not a mod Bayle can install: {why}").format(name=src.name, why=e.message), error=True
                )
            else:
                self.notifier.toast(tr("Could not read {name}: {why}").format(name=src.name, why=e.message), error=True)
            QTimer.singleShot(0, self._next)

        query(self.host, lambda: self._service.open(str(profile), str(src)), self._opened, failed)

    def _opened(self, got) -> None:
        self._planning = False
        if self.host.profile is None:  # the profile went away while it was unpacked
            self._close(got.install_id)
            QTimer.singleShot(0, self._next)
            return
        draft = InstallDraft(
            got.plan, Path(self.host.profile), overhaul_on=got.overhaul_on, install_id=got.install_id, stamp=got.stamp
        )
        self._draft, self._view = draft, {}
        if draft.overhaul_mode:  # the preview of the option that starts ticked
            draft.asked()
        self._view = draft.view()
        if draft.busy:
            self._refresh()
        self.viewChanged.emit()
        self.openRequested.emit()

    def _close(self, install_id: str) -> None:
        query(self.host, lambda: self._service.close(install_id), lambda _r: None, lambda _e: None)

    # ---- edits (the dialog calls these as the player types and ticks): in memory; the ones the engine must see wait
    def _edit(self, change: Callable[[InstallDraft], Any], ask: bool = False) -> None:
        d = self._draft
        if d is None:
            return
        if change(d) is not False and ask:
            d.asked()
            self._timer.start()
        self._view = d.view()
        self.viewChanged.emit()

    @Slot(str)
    def setName(self, text: str) -> None:
        self._edit(lambda d: d.set_name(text), ask=True)

    @Slot(str)
    def setId(self, text: str) -> None:
        self._edit(lambda d: d.set_id(text), ask=True)

    @Slot(str)
    def setVariant(self, name: str) -> None:
        def change(d: InstallDraft) -> None:
            d.variant = name

        self._edit(change, ask=True)

    @Slot(str, bool)
    def setTick(self, name: str, on: bool) -> None:
        self._edit(lambda d: d.ticks.__setitem__(name, on))

    @Slot(bool)
    def setPlaceLast(self, last: bool) -> None:
        self._edit(lambda d: setattr(d, "place_last", last))

    @Slot(bool)
    def setRebuild(self, on: bool) -> None:
        self._edit(lambda d: setattr(d, "rebuild", on))

    @Slot(bool)
    def setAfterLast(self, on: bool) -> None:
        self._edit(lambda d: d.set_after_last(on))

    @Slot(str)
    def setLibraryChoice(self, key: str) -> None:
        self._edit(lambda d: setattr(d, "library_choice", key))

    @Slot(bool)
    def setOverhaul(self, on: bool) -> None:
        self._edit(lambda d: setattr(d, "overhaul", on), ask=True)

    @Slot(str, str, str)
    def setNative(self, file: str, kind: str, value: str) -> None:
        """A DLL option of the setup (kind early | after | init): the preview is worked out again with it."""
        self._edit(lambda d: d.set_native(file, kind, value), ask=True)

    @Slot(str, str)
    def setTable(self, file: str, table: str) -> None:
        """The table a texts entry sets its strings in (chosen among the tables of the download's copy)."""
        self._edit(lambda d: d.set_table(file, table), ask=True)

    @Slot(str, str)
    def setFile(self, file: str, value: str) -> None:
        """A choice of the Files table (an action, or place:<game path>): the preview is worked out again with it."""
        self._edit(lambda d: d.set_file(file, value), ask=True)

    # ---- the engine's replan and overhaul preview, one at a time (an edit meanwhile asks once more)
    def _refresh(self) -> None:
        d = self._draft
        if d is None:
            return
        if self._refreshing:
            self._again = True
            return
        self._refreshing = True
        gen, key = d.gen, d.key()
        if key == d.planned:
            self._planned(d, gen, key, None)
            return
        query(
            self.host,
            lambda: self._service.replan(d.install_id, key[0], key[1], key[2]),
            lambda plan: self._planned(d, gen, key, plan),
            lambda e: self._planned(d, gen, key, e),
        )

    def _planned(self, d: InstallDraft, gen: int, key: tuple, got: Any) -> None:
        """The plan for key landed (None: it was the plan's already). An answer to an edit made since is dropped."""
        if d is not self._draft:  # the dialog is gone
            self._refreshing = False
            return
        if gen == d.gen:
            if isinstance(got, OperationError):
                if got.code == "cannot_plan":  # the last good plan stays
                    d.problem = got.message
            else:
                d.problem = ""
                if got is not None:
                    d.new_plan(got, variant_changed=key[2] != d.planned[2])
            if not d.problem and d.needs_preview():
                mode, setup = d.overhaul_mode, d.setup_values()
                query(
                    self.host,
                    lambda: self._service.check_overhaul(d.install_id, key[0], setup),
                    lambda pv: self._previewed(d, gen, mode, key, pv),
                    lambda _e: self._settled(d, gen),
                )
                return
        self._settled(d, gen)

    def _previewed(self, d: InstallDraft, gen: int, mode: str, key: tuple, pv: Any) -> None:
        if d is self._draft and gen == d.gen:
            d.apply_preview(pv, mode, key)
        self._settled(d, gen)

    def _settled(self, d: InstallDraft, gen: int) -> None:
        self._refreshing = False
        if d is not self._draft:
            return
        if gen == d.gen:
            d.busy = False
        self._view = d.view()
        self.viewChanged.emit()
        if self._again:
            self._again = False
            self._refresh()

    # ---- ending
    @Slot(result=bool)
    def accept(self) -> bool:
        """Install; True closes the dialog."""
        d = self._draft
        if d is None or self._timer.isActive() or not d.can_install():
            return False
        if self._profile() is None:
            return False
        self._draft, self._view = None, {}
        self.viewChanged.emit()
        self._install(d, d.stamp)
        return True

    def _install(self, d: InstallDraft, expect: tuple[int, int] | None, again: bool = True) -> None:
        """Start the install with what the dialog set; if the profile changed since it was opened, ask once more."""
        choices, name = d.choices(), d.name_text.strip()

        def ended(snap: Any) -> None:
            if snap is not None and snap.state == "failed" and snap.error is not None:
                self.notifier.toast(
                    tr("Could not install {name}: {why}").format(name=name, why=snap.error.message), error=True
                )

        def failed(e: OperationError) -> None:
            if e.code == "stale" and again:
                self._ask_again(d)
                return
            self._close(d.install_id)  # the engine keeps the download open until it is installed or closed
            if e.code == "not_ready":
                self.notifier.toast(
                    tr("Could not install {name}: {why}").format(name=name, why=not_ready_text(e)), error=True
                )
            else:
                self._say(e)

        query(
            self.host,
            lambda: self._service.install(d.install_id, choices, expect),
            lambda job_id: self.host.follow_job(job_id, ended),
            failed,
        )

    def _ask_again(self, d: InstallDraft) -> None:
        name = d.name_text.strip()
        words = Confirm(
            title=tr("Install {name} now?").format(name=name),
            changes=(tr("The profile changed since you opened this download. It is installed into it as it is now."),),
            apply=tr("Install"),
        )

        def answered(ok: bool, _option: bool) -> None:
            profile = self.host.profile
            if ok and profile is not None:
                self._install(d, stamp(Path(profile)), again=False)
            else:
                self._close(d.install_id)

        self.notifier.ask(words, answered)

    @Slot(result=bool)
    def importInstead(self) -> bool:
        """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder and clears the
        staging folder itself. True closes the dialog."""
        d = self._draft
        if d is None or not self._view.get("profilesInside"):
            return False
        self._draft, self._view = None, {}
        self.viewChanged.emit()

        def handed(h) -> None:
            self.host.open_profile_import(Path(h.unpacked), list(h.profiles), Path(h.staging) if h.staging else None)

        query(self.host, lambda: self._service.hand_off(d.install_id), handed, self._say)
        return True

    @Slot()
    def dialogClosed(self) -> None:
        """The dialog closed: a cancel (an install already took the draft) drops the unpacked copy."""
        d, self._draft = self._draft, None
        self._timer.stop()
        if d is not None:
            self._view = {}
            self.viewChanged.emit()
            self._close(d.install_id)
        QTimer.singleShot(0, self._next)
