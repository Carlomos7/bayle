"""The Export / Import profile page's adapter: the thin QObject the QML page binds to. What to show comes from the
presenter, what a button does from services/profile_transfer.py (and services/mods.py for a profile a download
ships). The page has three views: Export, Import (a share list or a full export someone sent) and the bundled-profile
view (a mod download that also holds a .me3). Reading, previewing and exporting run on the host's worker; the import
itself is a logged job, so it shows in Activity with its Undo."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from roundtable_souls.mods import naming, profile_import
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.services import mods as mod_service
from roundtable_souls.services import profile_transfer as pt
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.profile_transfer.presenter import ProfileTransferPresenter, size_text
from roundtable_souls.ui.text import tr

EXPORT, IMPORT, BUNDLED = "export", "import", "bundled"


class ProfileTransferHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell)."""

    @property
    def busy(self) -> bool: ...
    @property
    def game_running(self) -> bool: ...
    @property
    def locations(self) -> Any: ...
    @property
    def profile(self) -> Path | None: ...
    @property
    def settings(self) -> Any: ...
    def run_in_background(self, work, on_result) -> None: ...
    def run_job(self, job, status: str) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None: ...
    def pick_folder(self, title: str) -> Path | None: ...
    def open_path(self, path: Path) -> None: ...
    def profile_changed(self, note: str) -> None: ...


class ProfileTransferAdapter(QObject):
    changed = Signal()
    _progressed = Signal(object, object, str, int, int)  # emitted on the export's worker, delivered on the UI thread
    _bytes_in = Signal(object, object)  # an import's bytes unpacked of the total, likewise

    def __init__(
        self,
        host: ProfileTransferHost,
        notifier: Notifier,
        presenter: ProfileTransferPresenter | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.presenter = presenter or ProfileTransferPresenter()
        self._words = self.presenter.words()
        self._mode = EXPORT
        self._working = False
        self._profile: Path | None = None
        # export
        self._items: list[pt.Item] = []
        self._picked: set[str] = set()
        self._ex: dict[str, Any] = {
            "kind": "list",
            "name": "",
            "version": "",
            "author": "",
            "readme": "",
            "readmeEdited": False,
            "changelog": "",
            "withConfigs": True,
            "withPassword": False,
            "withSave": False,
            "saveName": "",
            "folder": "",
        }
        # import
        self._incoming: pt.Incoming | None = None
        self._preview: pt.Preview | None = None
        self._ticked: set[str] = set()
        self._choices: dict[str, str] = {}  # per mod that differs from an installed one: incoming | mine | both
        self._new_profile = True
        self._new_name = ""
        # a profile a download ships
        self._staging: Path | None = None
        self._unpacked: Path | None = None
        self._names: list[str] = []
        self._which = 0
        self._bundled: Any = None
        self._error = ""
        self._result: dict[str, Any] = {}
        # a running or finished export: phase idle | running | done | error | cancelled
        self._run: dict[str, Any] = {"phase": "idle"}
        self._cancel = threading.Event()
        self._started = 0.0
        self._progressed.connect(self._on_progress)
        self._import_pct = -1  # -1: no byte count (reading, or a share list)
        self._bytes_in.connect(self._on_unpacked)

    # ---- what QML reads
    title = Property(str, lambda self: self._words["title"], constant=True)
    words = Property(dict, lambda self: self._words, constant=True)
    mode = Property(str, lambda self: self._mode, notify=changed)
    working = Property(bool, lambda self: self._working, notify=changed)
    state = Property(dict, lambda self: self._state(), notify=changed)

    def _state(self) -> dict:
        ex = dict(self._ex)
        ex["mods"] = [
            {
                "key": it.key,
                "name": it.entry["name"],
                "size": size_text(it.size),
                "note": self.presenter.mod_note(it),
                "checked": it.key in self._picked,
            }
            for it in self._items
        ]
        picked = [it for it in self._items if it.key in self._picked]
        size = sum(it.size for it in picked)
        full = ex["kind"] == "full"
        for row, it in zip(ex["mods"], self._items, strict=True):
            row["large"] = it.size >= pt.LARGE_MOD
        ex["total"] = self.presenter.total(len(picked), size)
        name_ok, folder_ok, mods_ok = bool(ex["name"].strip()), bool(ex["folder"]), bool(picked) or not full
        busy = (
            tr("Another job is running. Wait for it to finish.")
            if self.host.busy
            else tr("Close the game first: exports run as launcher jobs.")
            if self.host.game_running
            else tr("Exporting...")
            if self._working
            else ""
        )
        ex["reason"] = self.presenter.reason(name_ok, folder_ok, mods_ok, busy)
        ex["ready"] = ex["reason"] == ""
        ex["nameError"], ex["folderError"], ex["modsError"] = not name_ok, not folder_ok, not mods_ok
        ex["summary"] = self.presenter.summary(
            full,
            len(picked),
            size,
            bool(ex["withConfigs"]),
            bool(ex["withSave"] and ex["saveName"]),
            bool(ex["withPassword"]),
        )
        top = sorted(picked, key=lambda it: it.size, reverse=True)[:3]
        ex["warn"] = (
            self.presenter.big_warning(size, [(it.entry["name"], it.size) for it in top])
            if full and size >= pt.LARGE_EXPORT
            else ""
        )
        ex["run"] = dict(self._run)
        ex["fullLabel"] = f"{self._words['fullExport']} ({size_text(size)})" if picked else self._words["fullExport"]
        prev = self._preview
        imp: dict[str, Any] = {
            "file": self.presenter.file_line(self._incoming) if self._incoming else "",
            "isZip": bool(self._incoming and self._incoming.kind == "zip"),
            "readme": self._incoming.readme if self._incoming else "",
            "cards": [{**c, "checked": c["key"] in self._ticked} for c in self.presenter.cards(prev)] if prev else [],
            "skipped": list(prev.skipped) if prev else [],
            "notes": list(prev.notes) if prev else [],
            "refusals": list(prev.refusals) if prev else [],
            "newProfile": self._new_profile,
            "newName": self._new_name,
            "error": self._error,
            "pct": self._import_pct,
            "clashes": self.presenter.clashes(prev.zip_preview, self._new_profile) if prev and prev.zip_preview else [],
        }
        imp["canImport"] = bool(
            prev
            and not prev.refusals
            and (self._ticked & {c["key"] for c in imp["cards"]})
            and not (prev.zip_preview and prev.zip_preview.undecided)
        )
        b = self._bundled
        bun = {
            "names": self._names,
            "which": self._which,
            "lines": list(b.lines) if b else [],
            "skipped": [],
            "refusals": list(b.refusals) if b else [],
            "newProfile": self._new_profile,
            "newName": self._new_name,
            "canImport": bool(b and b.ok and not b.undecided),
            "clashes": self.presenter.clashes(b, self._new_profile) if b else [],
        }
        return {
            "hasProfile": self._profile is not None,
            "profileName": self._profile.stem if self._profile else "",
            "ex": ex,
            "imp": imp,
            "bun": bun,
        }

    def _emit(self) -> None:
        self.changed.emit()

    # ---- opening
    def open_transfer(self, mode: str) -> None:
        """Show the Export or the Import view (the gear menu's two entries)."""
        self._release()
        self._mode = IMPORT if mode == IMPORT else EXPORT
        self.refresh()

    def open_profile_import(self, unpacked: Path, profiles: list[str], staging: Path | None = None) -> None:
        """The bundled-profile view for a download that ships .me3 profiles (E1): unpacked is the unpacked download,
        profiles the .me3 paths in it. staging: the folder to delete when the view is done."""
        self._release()
        self._mode = BUNDLED
        self._unpacked, self._staging = Path(unpacked), Path(staging) if staging else None
        self._names = list(profiles)
        self._which = 0
        self._new_profile = True
        self._new_name = Path(self._names[0]).stem if self._names else ""
        self._bundled = None
        self.refresh()
        self._preview_bundled()

    def _release(self) -> None:
        """Let go of what an earlier view held: the unpacked zip, the download's staging folder."""
        if self._incoming is not None:
            pt.discard(self._incoming)
        if self._staging is not None:
            shutil.rmtree(self._staging, ignore_errors=True)
        self._incoming = self._preview = self._bundled = None
        self._staging = self._unpacked = None
        self._ticked = set()
        self._choices = {}
        self._error = ""

    # ---- what the shell's menu and keys may ask of this page (ui/launcher/menu.py)
    COMMANDS = {
        "import": "_import_view",
        "export": "_export_view",
    }

    def command(self, name: str, args) -> bool:
        """Run a menu command; False when this page has none by that name."""
        method = self.COMMANDS.get(name)
        if method is None:
            return False
        getattr(self, method)(*args)
        return True

    def _import_view(self) -> None:
        self.open_transfer("import")

    def _export_view(self) -> None:
        self.open_transfer("export")

    @Slot()
    def refresh(self) -> None:
        """Read the profile and what an export lists (also the host's call after a job)."""
        self._finished()
        profile = self.host.profile
        before, self._profile = self._profile, Path(profile) if profile else None
        if before is not None and before != self._profile:  # another profile in the top bar: name and readme start over
            self._ex.update(name="", readme="", readmeEdited=False)
        self._emit()
        if self._mode == IMPORT and self._incoming is not None:  # the top bar's profile may have changed
            self._make_preview()
        if self._mode != EXPORT or self._profile is None or self._working:
            return
        loc, profile = self.host.locations, self._profile

        def work():
            if loc is None:
                return [], None
            return pt.items(profile, full=True), pt.save_candidate(profile, loc=loc)

        def got(result) -> None:
            self._items, save = result
            self._picked = {it.key for it in self._items if it.inside}
            self._ex["name"] = self._ex["name"] or profile.stem
            self._ex["saveName"] = save.name if save else ""
            if not self._ex["readmeEdited"]:
                self._ex["readme"] = pt.default_readme(self._ex["name"], "", "", self._items)
            self._emit()

        self.host.run_in_background(work, got)

    def _finished(self) -> None:
        """After an import job: say how it went."""
        res, self._result = self._result, {}
        if not res:
            return
        self._working = False
        self._import_pct = -1
        if res.get("kind") == "export":
            took = time.monotonic() - self._started
            if res.get("cancelled"):
                self._run = {"phase": "cancelled", "text": self.presenter.cancelled()}
            elif res.get("error"):
                self._run = {"phase": "error", "text": self.presenter.failed(res["error"])}
            else:
                text = self.presenter.done_text(res["path"], res["size"], took)
                self._run = {"phase": "done", "text": text, "path": str(res["path"])}
            self._emit()
            return
        if res.get("error"):
            self.notifier.toast(self.presenter.import_failed(res["error"]), error=True)
        else:
            self.notifier.toast(self.presenter.imported(res["name"]))
            self._release()
            self._preview = None
            self._mode = IMPORT if self._mode == BUNDLED else self._mode
            self.host.profile_changed(f"imported {res['name']}")

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode in (EXPORT, IMPORT) and mode != self._mode:
            self._release()
            self._mode = mode
            self.refresh()

    # ---- export
    @Slot(str, str)
    def setText(self, field: str, value: str) -> None:
        if field in ("name", "version", "author", "readme", "changelog", "kind") and self._ex[field] != value:
            self._ex[field] = value
            if field == "readme":
                self._ex["readmeEdited"] = True
            elif field in ("name", "version", "author") and not self._ex["readmeEdited"]:
                self._ex["readme"] = pt.default_readme(
                    self._ex["name"],
                    self._ex["version"],
                    self._ex["author"],
                    [i for i in self._items if i.key in self._picked],
                )
            self._emit()

    @Slot(str, bool)
    def setFlag(self, field: str, on: bool) -> None:
        if field in ("withConfigs", "withPassword", "withSave") and self._ex[field] != on:
            self._ex[field] = on
            self._emit()

    @Slot(str, bool)
    def toggleMod(self, key: str, on: bool) -> None:
        if (key in self._picked) == on:
            return
        (self._picked.add if on else self._picked.discard)(key)
        self._emit()

    @Slot()
    def chooseFolder(self) -> None:
        got = self.host.pick_folder(self._words["outFolder"])
        if got is not None:
            self._ex["folder"] = str(got)
            self._emit()

    @Slot()
    def exportNow(self) -> None:
        ex, profile, loc = self._ex, self._profile, self.host.locations
        st = self._state()["ex"]
        if profile is None or loc is None or self._working or not st["ready"]:
            if st["reason"]:
                self.notifier.toast(st["reason"], error=True)
            return
        if ex["kind"] == "full":
            size = sum(it.size for it in self._items if it.key in self._picked)
            if size >= pt.LARGE_EXPORT:  # asked once, here, for a big one
                title, lines = self.presenter.confirm_big(size)
                self.notifier.confirm(title, lines, "", self._words["export"], lambda ok: ok and self._start_export())
                return
        self._start_export()

    def _start_export(self) -> None:
        ex, profile, loc, settings = self._ex, self._profile, self.host.locations, self.host.settings
        if profile is None or loc is None or self._working or self.host.busy:
            return
        picked = set(self._picked)
        self._working = True
        self._cancel.clear()
        self._started = time.monotonic()
        self._run = {"phase": "running", "pct": 0, "title": "", "bytes": "", "eta": "", "file": "", "cancelling": False}
        self._emit()
        box = self._result
        args = dict(
            loc=loc,
            settings=settings,
            name=ex["name"].strip(),
            version=ex["version"].strip(),
            author=ex["author"].strip(),
            password=bool(ex["withPassword"]),
        )
        full, folder = ex["kind"] == "full", Path(ex["folder"])
        extra = dict(
            readme=ex["readme"],
            changelog=ex["changelog"],
            chosen=picked,
            out_dir=folder,
            with_configs=bool(ex["withConfigs"]),
            with_save=bool(ex["withSave"]),
        )
        last = [0.0]

        def report(done, total, current, n, count) -> None:  # on the worker: at most ten times a second
            now = time.monotonic()
            if now - last[0] >= 0.1 or done >= total:
                last[0] = now
                self._progressed.emit(done, total, current, n, count)

        def job(_setup, _loc):
            from roundtable_souls.platform import logging as run_logging

            run_logging.start_log(f"launcher: export profile {args['name']}", loc.game.key)
            try:
                if full:
                    out = pt.full_export(profile, progress=report, cancelled=self._cancel.is_set, **extra, **args)
                else:
                    doc, _ = pt.share_list(profile, **args)
                    if not ex["withConfigs"]:
                        doc["configs"] = {}
                    out = pt.write_share_list(doc, folder)
                box.update(kind="export", path=out, size=out.stat().st_size)
            except pt.ExportCancelled:
                box.update(kind="export", cancelled=True)
                run_logging.log("export cancelled; the partial zip was removed")
                raise SystemExit(130) from None
            except Exception as e:
                box.update(kind="export", error=str(e) or type(e).__name__)
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, tr("Exporting a profile..."))

    def _on_progress(self, done, total, current: str, n: int, count: int) -> None:
        if self._run.get("phase") != "running":
            return
        shown = self.presenter.progress(done, total, n, count, time.monotonic() - self._started)
        self._run.update(shown, file=current.rsplit("/", 1)[-1])
        self._emit()

    def _on_unpacked(self, done, total) -> None:
        self._import_pct = int(100 * done / total) if total else 0
        self._emit()

    @Slot()
    def cancelExport(self) -> None:
        if self._run.get("phase") == "running":
            self._cancel.set()
            self._run["cancelling"] = True
            self._emit()

    @Slot()
    def dismissRun(self) -> None:
        self._run = {"phase": "idle"}
        self._emit()

    @Slot()
    def showExport(self) -> None:
        path = self._run.get("path")
        if path:
            self.host.open_path(Path(path).parent)

    # ---- import: a share list or a full export
    @Slot()
    def openFile(self) -> None:
        got = self.host.pick_file(self._words["openFile"], "Profile files (*.json *.zip)")
        if got is None or self._working:
            return
        loc = self.host.locations
        self._release()
        self._working = True
        self._emit()

        def work():
            try:
                return pt.read(got, loc=loc), ""
            except Exception as e:
                return None, str(e)

        def done(result) -> None:
            self._working = False
            incoming, why = result
            if incoming is None:
                self._error = self.presenter.unreadable(why)
                self._emit()
                return
            self._incoming = incoming
            self._new_profile = incoming.kind == "zip"
            self._new_name = incoming.share.name or incoming.path.stem
            self._make_preview()

        self.host.run_in_background(work, done)

    def _make_preview(self) -> None:
        incoming, profile, loc, settings = self._incoming, self._profile, self.host.locations, self.host.settings
        if incoming is None or profile is None:
            return
        new_name = self._new_name.strip() if incoming.kind == "zip" and self._new_profile else None
        choices = self._choices
        self._working = True
        self._emit()

        def work():
            try:
                if incoming.kind == "zip" and self._new_profile and not new_name:
                    raise ModError(tr("Give the new profile a name."))
                if new_name and not naming.mod_id(new_name):
                    raise ModError(tr("Give the new profile a name."))
                return pt.preview(
                    incoming, profile, loc=loc, settings=settings, new_name=new_name, choices=dict(choices)
                ), ""
            except Exception as e:
                return None, str(e)

        def done(result) -> None:
            self._working = False
            prev, why = result
            self._error = why
            before = (
                ({c.key for c in self._preview.cards}, set(self._ticked)) if self._preview else None
            )  # a new look after a choice keeps what was unticked
            self._preview = prev
            keys = {c.key for c in prev.cards} if prev else set()
            self._ticked = {k for k in keys if before is None or k not in before[0] or k in before[1]}
            self._emit()

        self.host.run_in_background(work, done)

    @Slot(str, bool)
    def toggleCard(self, key: str, on: bool) -> None:
        if (key in self._ticked) == on:
            return
        (self._ticked.add if on else self._ticked.discard)(key)
        self._emit()

    @Slot(str, str)
    def chooseCopy(self, key: str, choice: str) -> None:
        """The player's pick for a mod that differs from the installed one: incoming | mine | both."""
        if choice not in profile_import.CHOICES or self._working:
            return
        self._choices[key.lower()] = choice
        self._emit()
        self._retarget()

    @Slot(bool)
    def setNewProfile(self, new: bool) -> None:
        if new == self._new_profile:
            return
        self._new_profile = new
        self._emit()
        self._retarget()

    @Slot(str)
    def setNewName(self, name: str) -> None:
        self._new_name = name
        self._emit()

    @Slot()
    def renamed(self) -> None:
        """The profile name field lost focus or Enter: preview again with it."""
        self._retarget()

    def _retarget(self) -> None:
        if self._mode == BUNDLED:
            self._preview_bundled()
        elif self._incoming is not None:
            self._make_preview()

    @Slot()
    def importNow(self) -> None:
        prev = self._preview
        if prev is None or self._working or self.host.busy:
            if self.host.busy:
                self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        skip = {c.key for c in prev.cards} - self._ticked
        box = self._result
        self._working = True
        self._import_pct = 0
        self._emit()
        last = [0.0]

        def report(done, total) -> None:  # on the worker: at most ten times a second
            now = time.monotonic()
            if now - last[0] >= 0.1 or done >= total:
                last[0] = now
                self._bytes_in.emit(done, total)

        def job(_setup, loc):
            from roundtable_souls.platform import logging as run_logging

            run_logging.start_log(f"launcher: import a shared profile into {prev.profile.name}", loc.game.key)
            try:
                out = pt.apply(prev, skip, progress=report)
                box.update(name=Path(out["profile"]).name)
            except Exception as e:
                box.update(error=str(e) or type(e).__name__)
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, tr("Importing a profile..."))

    # ---- a profile a download ships (S3g)
    @Slot(int)
    def pickWhich(self, index: int) -> None:
        if 0 <= index < len(self._names):
            self._which = index
            self._new_name = Path(self._names[index]).stem
            self._preview_bundled()

    def _preview_bundled(self) -> None:
        profile, loc = self._profile, self.host.locations
        if self._unpacked is None or profile is None or not self._names:
            return
        unpacked, me3 = self._unpacked, self._names[self._which]
        new_name = self._new_name.strip() if self._new_profile else None
        choices = self._choices
        self._working = True
        self._emit()

        def work():
            try:
                if self._new_profile and not new_name:
                    raise ModError(tr("Give the new profile a name."))
                return mod_service.preview_profile_import(
                    unpacked, me3, profile, loc=loc, new_name=new_name, choices=dict(choices)
                ), ""
            except Exception as e:
                return None, str(e)

        def done(result) -> None:
            self._working = False
            prev, why = result
            self._bundled = prev
            self._error = why
            self._emit()

        self.host.run_in_background(work, done)

    @Slot()
    def importBundled(self) -> None:
        prev = self._bundled
        if prev is None or not prev.ok or self._working:
            return
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        box = self._result
        self._working = True
        self._emit()

        def job(_setup, loc):
            from roundtable_souls.platform import logging as run_logging

            run_logging.start_log(f"launcher: import profile {prev.profile.name}", loc.game.key)
            try:
                out = mod_service.import_profile(prev)
                box.update(name=Path(out["profile"]).name)
            except Exception as e:
                box.update(error=str(e) or type(e).__name__)
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, tr("Importing a profile..."))

    @Slot()
    def cancel(self) -> None:
        """Leave the import: the unpacked zip and the download's staging folder go."""
        self._release()
        self._preview = None
        self._emit()

    @Slot()
    def openZipFolder(self) -> None:
        if self._incoming is not None:
            self.host.open_path(self._incoming.path.parent)
