"""The Export / Import profile page's adapter: the thin QObject the QML page binds to. It holds the form (what is
ticked, the fields), asks the session for everything else (the export listing, opening and previewing a file, the
export and the import as jobs) and shows what the presenter makes of it. The unpacked zip and a download's staging
folder are the backend's resources: the page keeps only an id. The page has three views: Export, Import (a share list
or a full export someone sent) and the bundled-profile view (a mod download that also holds a .me3)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from bayle.errors import OperationError
from bayle.modules.mods import profile_import
from bayle.modules.mods.profile_transfer import Listing, Opened, PreviewFacts, ProfileTransferService
from bayle.runtime.features import Features
from PySide6.QtCore import Property, QObject, Signal, Slot

from bayle_qt.notifications import Notifier
from bayle_qt.pages.profile_transfer.presenter import PageInputs, ProfileTransferPresenter
from bayle_qt.refresh import Refresher
from bayle_qt.text import tr

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
    def job_manager(self) -> Any: ...
    @property
    def features(self) -> Features: ...
    def run_in_background(self, work, on_result) -> None: ...
    def follow_job(self, job_id: str, done) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None: ...
    def pick_folder(self, title: str) -> Path | None: ...
    def open_path(self, path: Path) -> None: ...
    def profile_changed(self, note: str) -> None: ...


def _call(read) -> Any:
    """read() (a call of the engine's Profile transfer interface) on a worker: the result, or the OperationError to show."""
    try:
        return read()
    except OperationError as e:
        return e


class ProfileTransferAdapter(QObject):
    changed = Signal()
    _events_ready = Signal()  # the session's bus has events (from a worker thread)

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
        self._mods: list[Any] = []  # services.profile_transfer.ModRow
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
        # import: the backend resource (an unpacked zip or a download's staging folder) is only an id here
        self._res = ""
        self._opened: Opened | None = None
        self._preview: PreviewFacts | None = None
        self._ticked: set[str] = set()
        self._choices: dict[str, str] = {}  # per mod that differs from an installed one: incoming | mine | both
        self._new_profile = True
        self._new_name = ""
        self._names: list[str] = []  # a profile a download ships
        self._which = 0
        self._bundled: PreviewFacts | None = None
        self._error = ""
        self._import_pct = -1  # -1: no byte count (reading, or a share list)
        # the running or finished export: phase idle | running | done | error | cancelled
        self._run: dict[str, Any] = {"phase": "idle"}
        self._job = ""  # the session job this page follows: "export" | "import" once started
        self._job_id = ""
        self._starting = False  # a job is being started: its first events may arrive before its id does
        self._early: list[Any] = []
        self._started = 0.0
        self._refresher = Refresher(host, self._snapshot, self._build, self._apply_items)
        self._events = host.job_manager.bus.subscribe(notify=self._events_ready.emit)  # progress only
        self._events_ready.connect(self._drain)

    # ---- what QML reads
    title = Property(str, lambda self: self._words["title"], constant=True)
    words = Property(dict, lambda self: self._words, constant=True)
    mode = Property(str, lambda self: self._mode, notify=changed)
    working = Property(bool, lambda self: self._working, notify=changed)
    state = Property(dict, lambda self: self._state(), notify=changed)

    @property
    def _svc(self) -> ProfileTransferService:
        return self.host.features.profile_transfer

    def _state(self) -> dict:
        o, b = self._opened, self._bundled
        return self.presenter.page_state(
            PageInputs(
                profile=self._profile,
                ex=self._ex,
                mods=self._mods,
                picked=self._picked,
                busy=self.host.busy,
                game_running=self.host.game_running,
                working=self._working,
                run=self._run,
                incoming_file=self.presenter.file_line(o) if o else "",
                incoming_zip=bool(o and o.kind == "zip"),
                incoming_readme=o.readme if o else "",
                preview=self._preview,
                bundled=b,
                ticked=self._ticked,
                new_profile=self._new_profile,
                new_name=self._new_name,
                error=self._error,
                import_pct=self._import_pct,
                names=self._names,
                which=self._which,
            )
        )

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
        profiles the .me3 paths in it. staging: the folder the backend deletes when the view is done."""
        self._release()
        self._mode = BUNDLED
        self._names = list(profiles)
        self._which = 0
        self._new_profile = True
        self._new_name = Path(self._names[0]).stem if self._names else ""
        self.refresh()
        svc, names = self._svc, list(self._names)

        def opened(got) -> None:
            if isinstance(got, OperationError):
                self._error = self.presenter.error_text(got)
            elif self._mode == BUNDLED:
                self._res = got.resource
                self._preview_bundled()
            else:  # the player moved on before it was open
                self._drop(got.resource)
            self._emit()

        self.host.run_in_background(lambda: _call(lambda: svc.open_bundled(unpacked, names, staging or "")), opened)

    def _drop(self, resource: str) -> None:
        svc = self._svc
        self.host.run_in_background(lambda: _call(lambda: svc.discard(resource)), lambda _: None)

    def _release(self) -> None:
        """Let go of what an earlier view held: the backend deletes the unpacked zip and the download's staging folder."""
        if self._res:
            self._drop(self._res)
        self._res = ""
        self._opened = self._preview = self._bundled = None
        self._ticked = set()
        self._choices = {}
        self._error = ""
        self._names = []

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
        profile = self.host.profile
        before, self._profile = self._profile, Path(profile) if profile else None
        if before is not None and before != self._profile:  # another profile in the top bar: name and readme start over
            self._ex.update(name="", readme="", readmeEdited=False)
        self._emit()
        if self._mode == IMPORT and self._res:  # the top bar's profile may have changed
            self._make_preview()
        if self._mode != EXPORT or self._profile is None or self._working:
            return
        self._refresher.request()

    def _snapshot(self) -> tuple:
        return self._svc, self.host.locations, self._profile

    @staticmethod
    def _build(snap: tuple):
        svc, loc, profile = snap
        if loc is None or profile is None:
            return None, profile
        got = _call(lambda: svc.listing(str(profile)))
        return (None if isinstance(got, OperationError) else got), profile

    def _apply_items(self, result) -> None:
        listing: Listing | None
        listing, profile = result
        if listing is None or profile is None or profile != self._profile:  # none, or the top bar moved on
            if listing is None:
                self._mods = []
                self._emit()
            return
        self._mods = listing.mods
        self._picked = {m.key for m in self._mods}
        self._ex["name"] = self._ex["name"] or profile.stem
        self._ex["saveName"] = listing.save_name
        if not self._ex["readmeEdited"]:
            self._ex["readme"] = self._default_readme()
        self._emit()

    def _default_readme(self) -> str:
        ex = self._ex
        picked = [m for m in self._mods if m.key in self._picked]
        return self.presenter.readme(ex["name"], ex["version"], ex["author"], picked)

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
                self._ex["readme"] = self._default_readme()
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

    def _export_params(self) -> dict[str, Any]:
        ex = self._ex
        return dict(
            profile=str(self._profile),
            kind=ex["kind"],
            name=ex["name"],
            version=ex["version"],
            author=ex["author"],
            readme=ex["readme"],
            changelog=ex["changelog"],
            chosen=sorted(self._picked),
            folder=ex["folder"],
            with_configs=bool(ex["withConfigs"]),
            with_save=bool(ex["withSave"]),
            password=bool(ex["withPassword"]),
        )

    @Slot()
    def exportNow(self) -> None:
        profile, loc = self._profile, self.host.locations
        st = self._state()["ex"]
        if profile is None or loc is None or self._working or not st["ready"]:
            if st["reason"]:
                self.notifier.toast(st["reason"], error=True)
            return
        if self._ex["kind"] == "full":  # a big one is asked about once, here
            self._ask_big()
            return
        self._start_export(None)

    def _start_export(self, expect: int | None) -> None:
        svc, params = self._svc, self._export_params()
        self._start("export", lambda: svc.export(**params, expect=expect))

    def _ask_big(self) -> None:
        svc, p = self._svc, self._export_params()

        def shown(got) -> None:
            if isinstance(got, OperationError):
                self.notifier.toast(self.presenter.error_text(got), error=True)
            elif not got.big:
                self._start_export(got.size)
            else:
                words = self.presenter.confirm_big(got.size, tr("Export"))
                self.notifier.confirm(words, lambda ok: self._start_export(got.size) if ok else None)

        self.host.run_in_background(lambda: _call(lambda: svc.check_export(p["profile"], "full", p["chosen"])), shown)

    def _start(self, kind: str, begin) -> None:
        """Start the export or the import: begin() on a worker gives the job id, which the page follows to its end."""
        if self._working or self.host.busy:
            return
        self._working = True
        self._job = kind
        self._starting = True
        self._early = []
        self._started = time.monotonic()
        if kind == "export":
            self._run = {
                "phase": "running",
                "pct": 0,
                "title": "",
                "bytes": "",
                "eta": "",
                "file": "",
                "cancelling": False,
            }
        else:
            self._import_pct = 0
        self._emit()

        def started(got) -> None:
            self._starting = False
            if isinstance(got, OperationError):
                self._ended(self.presenter.error_text(got))
                return
            self._job_id = got
            early, self._early = self._early, []
            for e in early:
                self._on_event(e)
            self.host.follow_job(got, self._finished)

        self.host.run_in_background(lambda: _call(begin), started)

    # ---- how the job goes: its progress from the bus, its end from follow_job
    def _finished(self, snap) -> None:
        if snap is None or snap.state == "cancelled":
            self._ended("", cancelled=True)
        elif snap.state == "done":
            self._ended("", result=snap.result or {})
        else:
            self._ended(snap.error.message if snap.error else tr("Failed."))

    def _drain(self) -> None:
        while (e := self._events.get(0)) is not None:
            if e.job_id is None:
                continue
            if self._starting:
                self._early.append(e)  # the job id is not known yet: hold its events until it is
            elif e.job_id == self._job_id:
                self._on_event(e)

    def _on_event(self, e) -> None:
        if e.job_id != self._job_id:
            return
        if e.type == "progress":
            done, total = e.data.get("done") or 0, e.data.get("total") or 0
            if self._job == "export":
                d = e.data.get("detail") or {}
                shown = self.presenter.progress(
                    done, total, d.get("n", 0), d.get("count", 0), time.monotonic() - self._started
                )
                self._run.update(shown, file=str(e.data.get("label") or "").rsplit("/", 1)[-1])
            else:
                self._import_pct = int(100 * done / total) if total else 0
            self._emit()

    def _ended(self, why: str, result: dict | None = None, cancelled: bool = False) -> None:
        kind, self._job, self._job_id, self._working, self._import_pct = self._job, "", "", False, -1
        if kind == "export":
            if cancelled:
                self._run = {"phase": "cancelled", "text": self.presenter.cancelled()}
            elif why:
                self._run = {"phase": "error", "text": self.presenter.failed(why)}
            elif result:
                took = time.monotonic() - self._started
                text = self.presenter.done_text(Path(result["path"]), result["size"], took)
                self._run = {"phase": "done", "text": text, "path": result["path"]}
            else:
                self._run = {"phase": "idle"}
        elif why:
            self.notifier.toast(self.presenter.import_failed(why), error=True)
        elif result:
            self.notifier.toast(self.presenter.imported(result["name"]))
            self._res = ""  # the backend let go of it when the import worked
            self._release()
            self._mode = IMPORT if self._mode == BUNDLED else self._mode
            self.host.profile_changed(f"imported {result['name']}")
        self._emit()

    @Slot()
    def cancelExport(self) -> None:
        if self._run.get("phase") == "running" and self._job_id:
            self.host.job_manager.cancel(self._job_id)
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
        self._release()
        self._working = True
        self._emit()
        svc = self._svc

        def done(result) -> None:
            self._working = False
            if isinstance(result, OperationError):
                self._error = self.presenter.unreadable(result.message)
                self._emit()
                return
            self._res, self._opened = result.resource, result
            self._new_profile, self._new_name = result.new_profile, result.new_name
            self._make_preview()

        self.host.run_in_background(lambda: _call(lambda: svc.open_file(got)), done)

    def _preview_params(self) -> dict[str, Any]:
        return dict(
            resource=self._res,
            profile=str(self._profile),
            new_profile=self._new_profile,
            new_name=self._new_name,
            choices=dict(self._choices),
            which=self._which,
        )

    def _preview_call(self, want: dict[str, Any], done) -> None:
        svc = self._svc
        self.host.run_in_background(
            lambda: _call(lambda: svc.preview(want.pop("resource"), want.pop("profile"), **want)), done
        )

    def _make_preview(self) -> None:
        if not self._res or self._profile is None:
            return
        want = self._preview_params()
        res = want["resource"]
        self._working = True
        self._emit()

        def done(result) -> None:
            self._working = False
            if self._res != res:  # the player left that file
                return
            prev = None if isinstance(result, OperationError) else result
            self._error = self.presenter.error_text(result) if isinstance(result, OperationError) else ""
            before = (
                ({c.key for c in self._preview.cards}, set(self._ticked)) if self._preview else None
            )  # a new look after a choice keeps what was unticked
            self._preview = prev
            keys = {c.key for c in prev.cards} if prev else set()
            self._ticked = {k for k in keys if before is None or k not in before[0] or k in before[1]}
            self._emit()

        self._preview_call(want, done)

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
        elif self._res:
            self._make_preview()

    @Slot()
    def importNow(self) -> None:
        prev = self._preview
        if prev is None or self._working or self.host.busy:
            if self.host.busy:
                self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        self._import(sorted({c.key for c in prev.cards} - self._ticked), prev.serial)

    def _import(self, skip: list[str], serial: int) -> None:
        svc, res = self._svc, self._res
        self._start("import", lambda: svc.import_(res, skip, expect=serial))

    # ---- a profile a download ships (S3g)
    @Slot(int)
    def pickWhich(self, index: int) -> None:
        if 0 <= index < len(self._names):
            self._which = index
            self._new_name = Path(self._names[index]).stem
            self._preview_bundled()

    def _preview_bundled(self) -> None:
        if not self._res or self._profile is None or not self._names:
            return
        want = self._preview_params()
        res = want["resource"]
        self._working = True
        self._emit()

        def done(result) -> None:
            self._working = False
            if self._res != res:
                return
            self._bundled = None if isinstance(result, OperationError) else result
            self._error = self.presenter.error_text(result) if isinstance(result, OperationError) else ""
            self._emit()

        self._preview_call(want, done)

    @Slot()
    def importBundled(self) -> None:
        prev = self._bundled
        if prev is None or not prev.ok or self._working:
            return
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        self._import([], prev.serial)

    @Slot()
    def cancel(self) -> None:
        """Leave the import: the backend deletes the unpacked zip and the download's staging folder."""
        self._release()
        self._emit()

    @Slot()
    def openZipFolder(self) -> None:
        if self._opened is not None and self._opened.folder:
            self.host.open_path(Path(self._opened.folder))
