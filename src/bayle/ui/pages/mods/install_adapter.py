"""The Install mod dialog's adapter (technical specification §8.2): the QObject InstallModDialog.qml binds to, held
by the Mods adapter. The draft lives in the session (mods.install_*): this picks or takes the mods to install, asks
the session to open each (it unpacks and plans in the background), sends the edits as the player types and ticks,
pauses 200 ms before asking for the replan and the preview, keeps several drops in a queue (one dialog after
another, the next once the previous install has finished) and finishes as a logged job of the session."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot

from bayle.platform.text import tr
from bayle.platform.threads import as_worker
from bayle.services.errors import OperationError
from bayle.ui.notifications import Notifier
from bayle.ui.pages.calls import Calls
from bayle.views.mod_install import words as install_words


class InstallAdapter(QObject):
    viewChanged = Signal()
    openRequested = Signal()  # show the dialog

    def __init__(self, host: Any, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self._calls = Calls(host, notifier)
        self._queue: list[Path] = []
        self._draft: str | None = None  # the session's draft the dialog shows
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

        self._calls.run("mods.install_sources", {"paths": [str(x) for x in paths]}, sorted_out)

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

        self._calls.run("mods.install_open", {"profile": str(profile), "source": str(src)}, self._opened, failed)

    def _opened(self, got) -> None:
        self._planning = False
        if self.host.profile is None:  # the profile went away while it was unpacked
            self._calls.run("mods.install_close", {"draft_id": got.draft_id}, fail=lambda _e: None)
            QTimer.singleShot(0, self._next)
            return
        self._draft, self._view = got.draft_id, got.view
        if got.pending:
            self._refresh()  # the preview of the option that starts ticked
        self.viewChanged.emit()
        self.openRequested.emit()

    # ---- edits (the dialog calls these as the player types and ticks): in memory, so asked at once
    def _edit(self, field: str, key: str = "", text: str = "", on: bool = False, kind: str = "") -> None:
        if self._draft is None:
            return
        params = {"draft_id": self._draft, "field": field, "key": key, "text": text, "on": on, "kind": kind}
        try:
            got = self.host.session.run("mods.install_edit", params)
        except OperationError:  # the draft is gone
            return
        self._view = got.view
        if got.pending:
            self._timer.start()
        self.viewChanged.emit()

    @Slot(str)
    def setName(self, text: str) -> None:
        self._edit("name", text=text)

    @Slot(str)
    def setId(self, text: str) -> None:
        self._edit("id", text=text)

    @Slot(str)
    def setVariant(self, name: str) -> None:
        self._edit("variant", text=name)

    @Slot(str, bool)
    def setTick(self, name: str, on: bool) -> None:
        self._edit("tick", key=name, on=on)

    @Slot(bool)
    def setPlaceLast(self, last: bool) -> None:
        self._edit("place_last", on=last)

    @Slot(bool)
    def setRebuild(self, on: bool) -> None:
        self._edit("rebuild", on=on)

    @Slot(bool)
    def setAfterLast(self, on: bool) -> None:
        self._edit("after_last", on=on)

    @Slot(str)
    def setLibraryChoice(self, key: str) -> None:
        self._edit("library", text=key)

    @Slot(bool)
    def setOverhaul(self, on: bool) -> None:
        self._edit("overhaul", on=on)

    @Slot(str, str, str)
    def setNative(self, file: str, kind: str, value: str) -> None:
        """A DLL option of the setup (kind early | after | init): the preview is worked out again with it."""
        self._edit("native", key=file, kind=kind, text=value)

    @Slot(str, str)
    def setTable(self, file: str, table: str) -> None:
        """The table a texts entry sets its strings in (chosen among the tables of the download's copy)."""
        self._edit("table", key=file, text=table)

    @Slot(str, str)
    def setFile(self, file: str, value: str) -> None:
        """A choice of the Files table (an action, or place:<game path>): the preview is worked out again with it."""
        self._edit("file", key=file, text=value)

    def _refresh(self) -> None:
        """Plan again for the typed name, id and variant, and work out the overhaul preview when that option is on;
        on the worker, one at a time (an edit meanwhile asks once more)."""
        draft = self._draft
        if draft is None:
            return
        if self._refreshing:
            self._again = True
            return
        self._refreshing = True
        session = self.host.session

        def work() -> Any:
            try:
                with as_worker():  # a test host runs this inline
                    session.run("mods.install_replan", {"draft_id": draft})
                    return session.run("mods.install_preview", {"draft_id": draft})
            except OperationError as e:
                return e

        def landed(got: Any) -> None:
            self._refreshing = False
            if draft != self._draft:  # the dialog is gone
                return
            if not isinstance(got, OperationError):
                self._view = got.view
                self.viewChanged.emit()
            if self._again:
                self._again = False
                self._refresh()

        self.host.run_in_background(work, landed)

    # ---- ending
    @Slot(result=bool)
    def accept(self) -> bool:
        """Install; True closes the dialog."""
        if self._draft is None or self._timer.isActive() or not self._view.get("canInstall"):
            return False
        if self._profile() is None:
            return False
        draft, self._draft, self._view = self._draft, None, {}
        self.viewChanged.emit()
        self._calls.job("mods.install_finish", {"draft_id": draft})
        return True

    @Slot(result=bool)
    def importInstead(self) -> bool:
        """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder and clears the
        staging folder itself. True closes the dialog."""
        if self._draft is None or not self._view.get("profilesInside"):
            return False
        draft, self._draft, self._view = self._draft, None, {}
        self.viewChanged.emit()

        def handed(h) -> None:
            self.host.open_profile_import(Path(h.unpacked), h.profiles, Path(h.staging) if h.staging else None)

        self._calls.run("mods.install_import", {"draft_id": draft}, handed)
        return True

    @Slot()
    def dialogClosed(self) -> None:
        """The dialog closed: a cancel (an install already took the draft) drops the unpacked copy."""
        draft, self._draft = self._draft, None
        self._timer.stop()
        if draft is not None:
            self._view = {}
            self.viewChanged.emit()
            self._calls.run("mods.install_close", {"draft_id": draft}, fail=lambda _e: None)
        QTimer.singleShot(0, self._next)
