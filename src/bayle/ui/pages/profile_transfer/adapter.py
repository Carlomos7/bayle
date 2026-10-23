"""The Export / Import profile page's adapter: the thin QObject the QML page binds to. It holds the form (what is
ticked, the fields), asks the session for everything else (the export listing, opening and previewing a file, the
export and the import as jobs) and shows what the presenter makes of it. The unpacked zip and a download's staging
folder are the backend's resources: the page keeps only an id. The page has three views: Export, Import (a share list
or a full export someone sent) and the bundled-profile view (a mod download that also holds a .me3)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from bayle.errors import OperationError
from bayle.mods import profile_import
from bayle.platform.text import tr
from bayle.session import Session
from bayle.session.ops.profile_transfer import ExportListing, Opened, PreviewView
from bayle.ui.notifications import Notifier
from bayle.ui.refresh import Refresher
from bayle.views.profile_transfer import PageInputs, ProfileTransferPresenter

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
    def session(self) -> Session: ...
    def run_in_background(self, work, on_result) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None: ...
    def pick_folder(self, title: str) -> Path | None: ...
    def open_path(self, path: Path) -> None: ...
    def profile_changed(self, note: str) -> None: ...


def _call(session: Session, name: str, params: dict) -> Any:
    """session.run on a worker: the result, or the OperationError to show."""
    try:
        return session.run(name, params)
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
        self._mods: list[Any] = []  # session.ops.profile_transfer.ModRow
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
        self._preview: PreviewView | None = None
        self._ticked: set[str] = set()
        self._choices: dict[str, str] = {}  # per mod that differs from an installed one: incoming | mine | both
        self._new_profile = True
        self._new_name = ""
        self._names: list[str] = []  # a profile a download ships
        self._which = 0
        self._bundled: PreviewView | None = None
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
        self._events = host.session.jobs.bus.subscribe(notify=self._events_ready.emit)
        self._events_ready.connect(self._drain)

    # ---- what QML reads
    title = Property(str, lambda self: self._words["title"], constant=True)
    words = Property(dict, lambda self: self._words, constant=True)
    mode = Property(str, lambda self: self._mode, notify=changed)
    working = Property(bool, lambda self: self._working, notify=changed)
    state = Property(dict, lambda self: self._state(), notify=changed)

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
                incoming_file=o.file if o else "",
                incoming_zip=bool(o and o.is_zip),
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
        session = self.host.session
        want = {"unpacked": str(unpacked), "profiles": self._names, "staging": str(staging) if staging else ""}

        def opened(got) -> None:
            if isinstance(got, OperationError):
                self._error = got.message
            elif self._mode == BUNDLED:
                self._res = got.resource
                self._preview_bundled()
            else:  # the player moved on before it was open
                self._drop(got.resource)
            self._emit()

        self.host.run_in_background(lambda: _call(session, "profile_transfer.open_bundled", want), opened)

    def _drop(self, resource: str) -> None:
        session = self.host.session
        self.host.run_in_background(
            lambda: _call(session, "profile_transfer.discard", {"resource": resource}), lambda _: None
        )

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
        return self.host.session, self.host.locations, self._profile

    @staticmethod
    def _build(snap: tuple):
        session, loc, profile = snap
        if loc is None or profile is None:
            return None, profile
        return session.snapshot("profile_transfer", profile=str(profile)), profile

    def _apply_items(self, result) -> None:
        listing: ExportListing | None
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
        size = sum(m.size for m in self._mods if m.key in self._picked)
        if self._ex["kind"] == "full" and self.presenter.is_big(size):  # asked once, here, for a big one
            self._ask_big({**self._export_params(), "size": size})
            return
        self._start("export", lambda session: _call(session, "profile_transfer.export", self._export_params()))

    def _ask_big(self, params: dict) -> None:
        session = self.host.session

        def shown(plan) -> None:
            if isinstance(plan, OperationError):
                self.notifier.toast(plan.message, error=True)
                return
            self.notifier.confirm(plan.words, lambda ok: self._answer_big(plan.id, ok))

        self.host.run_in_background(lambda: _call(session, "profile_transfer.confirm_export", params), shown)

    def _answer_big(self, plan_id: str, ok: bool) -> None:
        if not ok:
            return
        self._start("export", lambda session: self._answer(session, plan_id))

    @staticmethod
    def _answer(session: Session, plan_id: str) -> Any:
        try:
            return session.answer(plan_id, {"ok": True})
        except OperationError as e:  # busy, expired
            return e

    def _start(self, kind: str, call) -> None:
        """Start the export or the import: call(session) on a worker gives the job id, then the bus tells how it goes."""
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
        session = self.host.session

        def started(got) -> None:
            self._starting = False
            if isinstance(got, OperationError) or not got:
                self._ended(got.message if isinstance(got, OperationError) else "", cancelled=got is None)
                return
            self._job_id = got
            early, self._early = self._early, []
            for e in early:
                self._on_event(e)

        self.host.run_in_background(lambda: call(session), started)

    # ---- the session's job events
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
        elif e.type == "finished":
            self._ended("", result=e.data.get("result") or {})
        elif e.type == "failed":
            self._ended((e.data.get("error") or {}).get("message") or tr("Failed."))
        elif e.type == "cancelled":
            self._ended("", cancelled=True)

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
            self.host.session.jobs.cancel(self._job_id)
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
        session = self.host.session

        def done(result) -> None:
            self._working = False
            if isinstance(result, OperationError):
                self._error = self.presenter.unreadable(result.message)
                self._emit()
                return
            self._res, self._opened = result.resource, result
            self._new_profile, self._new_name = result.new_profile, result.new_name
            self._make_preview()

        self.host.run_in_background(lambda: _call(session, "profile_transfer.open_file", {"path": str(got)}), done)

    def _preview_params(self) -> dict[str, Any]:
        return dict(
            resource=self._res,
            profile=str(self._profile),
            new_profile=self._new_profile,
            new_name=self._new_name,
            choices=dict(self._choices),
            which=self._which,
        )

    def _make_preview(self) -> None:
        if not self._res or self._profile is None:
            return
        want, session = self._preview_params(), self.host.session
        self._working = True
        self._emit()

        def done(result) -> None:
            self._working = False
            if self._res != want["resource"]:  # the player left that file
                return
            prev = None if isinstance(result, OperationError) else result
            self._error = result.message if isinstance(result, OperationError) else ""
            before = (
                ({c["key"] for c in self._preview.cards}, set(self._ticked)) if self._preview else None
            )  # a new look after a choice keeps what was unticked
            self._preview = prev
            keys = {c["key"] for c in prev.cards} if prev else set()
            self._ticked = {k for k in keys if before is None or k not in before[0] or k in before[1]}
            self._emit()

        self.host.run_in_background(lambda: _call(session, "profile_transfer.preview", want), done)

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
        want = {"resource": self._res, "skip": sorted({c["key"] for c in prev.cards} - self._ticked)}
        self._start("import", lambda session: _call(session, "profile_transfer.import", want))

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
        want, session = self._preview_params(), self.host.session
        self._working = True
        self._emit()

        def done(result) -> None:
            self._working = False
            if self._res != want["resource"]:
                return
            self._bundled = None if isinstance(result, OperationError) else result
            self._error = result.message if isinstance(result, OperationError) else ""
            self._emit()

        self.host.run_in_background(lambda: _call(session, "profile_transfer.preview", want), done)

    @Slot()
    def importBundled(self) -> None:
        prev = self._bundled
        if prev is None or not prev.ok or self._working:
            return
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        want = {"resource": self._res, "skip": []}
        self._start("import", lambda session: _call(session, "profile_transfer.import", want))

    @Slot()
    def cancel(self) -> None:
        """Leave the import: the backend deletes the unpacked zip and the download's staging folder."""
        self._release()
        self._emit()

    @Slot()
    def openZipFolder(self) -> None:
        if self._opened is not None and self._opened.folder:
            self.host.open_path(Path(self._opened.folder))
