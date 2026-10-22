"""The Saves page's adapter: the thin QObject the QML page binds to (technical specification §8.10, Saves). What to show
comes from the presenter, what a change does from the session's saves operations (session/ops/saves.py).

The read (every live save, the Library, the Backups) is the session's `saves` snapshot, run on the host's worker. Each
write is an operation: a plan (the presenter's words asked through the Notifier, the answer sent back) whose answer
starts a job, or a job at once. The adapter follows the job on the host, tells its result with Undo once the page is
read again, and holds no decision about what to write or how to back it up."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from bayle.platform.text import tr
from bayle.services.errors import OperationError
from bayle.services.saves_page import retention_limits
from bayle.session import Session
from bayle.ui.notifications import Notifier
from bayle.ui.refresh import Refresher
from bayle.views.common import Refusal
from bayle.views.saves import SavesPresenter


class SavesHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell)."""

    @property
    def busy(self) -> bool: ...
    @property
    def game_running(self) -> bool: ...
    @property
    def locations(self) -> Any: ...
    @property
    def session(self) -> Session: ...
    def run_in_background(self, work, on_result) -> None: ...
    def follow_job(self, job_id: str, done) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None: ...
    def open_path(self, path: Path) -> None: ...
    def saves_in_use(self) -> dict:
        """The save files the profile in use plays on by name: {active, standard, coop} ({} without a profile)."""
        ...


class SavesAdapter(QObject):
    changed = Signal()
    repairChanged = Signal()
    sheetChanged = Signal()
    importNameRequested = Signal(str, str)  # the file, a name to start from
    nameAsked = Signal(str, str)  # a drop that needs a name first (mode, file), as the menu's Save a copy does

    def __init__(self, host: SavesHost, notifier: Notifier, presenter: SavesPresenter | None = None, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.presenter = presenter or SavesPresenter()
        self._words = self.presenter.words()
        self._infos: list[dict] = []
        self._libs: dict[str, dict] = {}
        self._backups: list[dict] = []
        self._names: dict = {}
        self._loading = False
        self._refresher = Refresher(host, lambda: host.locations, self._build, self._apply, busy=self._set_loading)
        self._after: dict = {}  # a write's result {text, save, backup}; told at the next read
        self._adopt = False  # the next read is a user's Refresh: it also takes in older backup folders
        self._sheet_path, self._sheet_slot = "", 0
        self._repair_path = ""
        self._repair_slot = -1
        self._ticks: set[str] = set()
        self._keys: dict[str, tuple] = {}
        self._sheet: dict = {}
        self._sheet_open = False
        self._clip: dict = {}

    # ---- what QML reads
    title = Property(str, lambda self: self._words["title"], constant=True)
    words = Property(dict, lambda self: self._words, constant=True)
    loading = Property(bool, lambda self: self._loading, notify=changed)
    running = Property(bool, lambda self: bool(self.host.game_running), notify=changed)
    gameName = Property(str, lambda self: self._game_name(), notify=changed)
    runningBar = Property(str, lambda self: self.presenter.running_bar(self._game_name()), notify=changed)
    header = Property(str, lambda self: self.presenter.header(self._names), notify=changed)
    cards = Property(list, lambda self: self._cards(), notify=changed)
    hasSaves = Property(bool, lambda self: bool(self._infos), notify=changed)
    encrypted = Property(bool, lambda self: self._encrypted(), notify=changed)
    libraryRows = Property(list, lambda self: self.presenter.library_rows(self._libs)[0], notify=changed)
    libraryProblems = Property(list, lambda self: self.presenter.library_rows(self._libs)[1], notify=changed)
    backupDays = Property(list, lambda self: self.presenter.backup_days(self._backups), notify=changed)
    retention = Property(str, lambda self: self.presenter.retention(*retention_limits()), constant=True)
    # Check & repair
    repairOpen = Property(bool, lambda self: bool(self._repair_path), notify=repairChanged)
    repairCard = Property(dict, lambda self: self._repair_card(), notify=repairChanged)
    repairSlot = Property(int, lambda self: self._repair_slot, notify=repairChanged)
    repairGroups = Property(list, lambda self: self._repair_groups(), notify=repairChanged)
    repairDamaged = Property(list, lambda self: self._repair_damaged(), notify=repairChanged)
    repairSummary = Property(str, lambda self: self.presenter.summary(self._ticked()), notify=repairChanged)
    repairCount = Property(int, lambda self: len(self._ticked()), notify=repairChanged)
    repairButton = Property(str, lambda self: self.presenter.repair_button(len(self._ticked())), notify=repairChanged)
    # the character sheet
    sheetOpen = Property(bool, lambda self: self._sheet_open, notify=sheetChanged)
    sheet = Property(dict, lambda self: self._sheet, notify=sheetChanged)

    def _game_name(self) -> str:
        loc = self.host.locations
        return loc.game.name if loc is not None else ""

    def _encrypted(self) -> bool:
        loc = self.host.locations
        return loc is not None and loc.game.save_reader != "eldenring"

    def _info(self, path: str) -> dict | None:
        return next((i for i in self._infos if str(i["path"]) == str(path)), None)

    def _role(self, name: str) -> str:
        used = self._names or {}
        if name.lower() == str(used.get("active") or "").lower():
            return tr("Launch Profile uses this")
        if used.get("coop") and name.lower() == str(used.get("standard") or "").lower():
            return tr("Launch Vanilla and Launch Offline use this")
        return ""

    def _cards(self) -> list[dict]:
        running = bool(self.host.game_running)
        ordered = sorted(self._infos, key=lambda i: 0 if i["kind"] == "Standard" else 1)  # Standard first
        return [self.presenter.card(i, self._role(i["name"]), running) for i in ordered]

    # ---- reading
    # ---- what the shell's menu and keys may ask of this page (ui/launcher/menu.py)
    COMMANDS = {
        "backUpNow": "backUpAll",
        "transferCharacter": "_transfer_hint",
        "importSave": "pickImport",
        "openSavesFolder": "_open_saves_folder",
        "openLibrary": "openLibrary",
        "openBackups": "openBackups",
        "back": "_back",
    }

    def command(self, name: str, args) -> bool:
        """Run a menu command; False when this page has none by that name."""
        method = self.COMMANDS.get(name)
        if method is None:
            return False
        getattr(self, method)(*args)
        return True

    def _back(self) -> None:
        if self._repair_path:
            self.closeRepair()
        elif self._sheet_open:
            self.closeSheet()

    def _transfer_hint(self) -> None:
        self.notifier.toast(tr("Open a character's menu and pick Copy character to..."))

    def _open_saves_folder(self) -> None:
        self._open("saves")

    def backUpAll(self) -> None:
        """Saves > Back up now: one backup of every live save of this game."""
        if not self._blocked():
            self._job("saves.back_up", {"everything": True})

    @Slot()
    def refresh(self) -> None:
        """The user's Refresh (and the page being shown): also takes in older tools' backup folders, then reads."""
        self._adopt = True
        self._refresher.request()

    def _read(self) -> None:
        self._refresher.request()

    def _set_loading(self, on: bool) -> None:
        self._loading = on
        self.changed.emit()

    def _build(self, loc):
        if loc is None:
            return [], {}, [], {}
        session, adopt, self._adopt = self.host.session, self._adopt, False
        try:
            names = self.host.saves_in_use()  # before the read: the locations learn the names
        except Exception:
            names = {}
        if adopt:
            try:
                session.run("saves.adopt_legacy")
            except OperationError:
                pass  # the read still shows what is there
        state = session.snapshot("saves")
        return state.infos, state.libraries, state.backups, names

    def _apply(self, got) -> None:
        infos, libs, backups, names = got
        self._infos, self._libs, self._backups, self._names = infos, libs, backups, names
        self.changed.emit()
        if self._repair_path:
            self._reload_repair()
        if self._sheet_open:
            self._reload_sheet()
        after = dict(self._after)
        self._after.clear()
        if after:
            self._tell(after)

    def _tell(self, after: dict) -> None:
        text = after.get("text", "")
        if after.get("backup"):
            save, backup = Path(after["save"]), Path(after["backup"])
            self.notifier.toast_action(text, self._words["undo"], lambda: self._undo(save, backup))
        elif text:
            self.notifier.toast(text)

    def _undo(self, save: Path, backup: Path) -> None:
        """The toast's Undo: the same record the Activity page offers (mods.undo, type save-restore)."""
        if not self._blocked():
            self._job("saves.undo_change", {"save": str(save), "backup": str(backup)}, tell=False)

    # ---- the gate every write goes through (the session enforces it too; this tells the player at once)
    def _blocked(self, read_only: bool = False) -> bool:
        """read_only: a twin that only reads the live save (Save a copy, Import) is refused for a running job only."""
        if self.host.busy or (self.host.game_running and not read_only):
            self._refuse(
                self.presenter.refusal_busy(self._game_name(), bool(self.host.game_running) and not self.host.busy)
            )
            return True
        return False

    def _refuse(self, r: Refusal) -> None:
        self.notifier.toast(f"{r.title}. {r.body}", error=True)

    def _fail(self, e: OperationError, title: str = "") -> None:
        if e.code == "busy":
            self._refuse(
                self.presenter.refusal_busy(self._game_name(), (e.details or {}).get("reason") == "game_running")
            )
        elif title:
            self._refuse(Refusal(title, e.message))
        else:
            self.notifier.toast(e.message, error=True)

    # ---- asking the session (on the host's worker; the answer lands on the UI thread)
    def _call(self, name: str, params: dict | None, done=None, fail: str = "", settle=None) -> None:
        """Run an operation. done(result) on success; an OperationError is a toast (titled fail); settle() either way."""
        session = self.host.session

        def work():
            try:
                return session.run(name, params)
            except OperationError as e:
                return e

        def landed(got) -> None:
            if isinstance(got, OperationError):
                self._fail(got, fail)
            elif done is not None:
                done(got)
            if settle is not None:
                settle()

        self.host.run_in_background(work, landed)

    def _job(self, name: str, params: dict | None, tell: bool = True) -> None:
        """Run a job operation and follow it: when it ends its result is told (tell) and the page is read again."""
        self._call(name, params, lambda job_id: self._follow(job_id, tell))

    def _follow(self, job_id: str, tell: bool = True) -> None:
        def ended(snap) -> None:
            if tell and snap is not None and snap.state == "done" and isinstance(snap.result, dict):
                self._after.update(snap.result)
            self._read()

        self.host.follow_job(job_id, ended)

    def _ask(self, name: str, params: dict, fail: str = "", then=None) -> None:
        """A plan operation: the session offers it, the Notifier asks in its words, and the answer goes back. A job
        the answer starts is followed; one that finishes inline (a removal) calls then()."""

        def offered(plan) -> None:
            if isinstance(plan, Refusal):
                self._refuse(plan)
                return
            self.notifier.ask(
                plan.words,
                lambda ok, option: self._answer(plan.id, ok, option, fail, then),
                destructive=plan.destructive,
            )

        self._call(name, params, offered, fail)

    def _answer(self, plan_id: str, ok: bool, option: bool, fail: str, then) -> None:
        session = self.host.session

        def work():
            try:
                return session.answer(plan_id, {"ok": ok, "option": bool(option)})
            except OperationError as e:  # busy, expired, or changed since
                return e

        def landed(got) -> None:
            if isinstance(got, OperationError):
                self._fail(got, fail)
            elif ok and isinstance(got, str):
                self._follow(got)
            elif ok and then is not None:
                then()

        self.host.run_in_background(work, landed)

    def _open(self, which: str) -> None:
        self._call("saves.folder", {"which": which}, lambda f: self.host.open_path(Path(f.path)) if f.path else None)

    # ---- drag and drop (every drop is one of the menu twins' slots below, after the presenter's one rule set)
    @staticmethod
    def _plain(v) -> dict:
        """A drag's payload or spot, from QML (a QJSValue) or Python (a dict)."""
        return dict(v.toVariant() if hasattr(v, "toVariant") else v)

    def _drop_plan(self, source, target):
        return self.presenter.drop(
            self._plain(source),
            self._plain(target),
            game=self._game_name(),
            running=bool(self.host.game_running),
            busy=bool(self.host.busy),
            encrypted=self._encrypted(),
        )

    @Slot("QVariant", "QVariant", result=str)
    def dropReason(self, source, target) -> str:
        """Why the spot refuses this drag, in words ("" when it takes it). In memory: nothing is read from disk."""
        plan = self._drop_plan(source, target)
        return f"{plan.title}. {plan.body}" if isinstance(plan, Refusal) else ""

    @Slot("QVariant", "QVariant")
    def drop(self, source, target) -> None:
        """A drop: the same slot, confirmation and write as the menu twin; a refusal is said in a toast."""
        plan = self._drop_plan(source, target)
        if isinstance(plan, Refusal):
            self._refuse(plan)
        elif plan.call == "askName":
            self.nameAsked.emit(*plan.args)
        else:
            getattr(self, plan.call)(*plan.args)

    @Slot(str, str, int, str, int)
    def copyFromLibrary(self, folder: str, entry_id: str, src_slot: int, target: str, dst_slot: int) -> None:
        """One character out of a Library copy into a slot: copyCharacter with the copy's file as the source."""
        if self._blocked():
            return
        self._call(
            "saves.copy_entry",
            {"folder": folder, "entry_id": entry_id},
            lambda entry: self.copyCharacter(entry.path, src_slot, target, dst_slot),
            fail=tr("This copy cannot be used"),
        )

    # ---- Ctrl+C on a character, Ctrl+V on a slot (a drop of the copied character)
    @Slot(str, int)
    def copyCharacterKey(self, path: str, slot: int) -> None:
        self._clip = {"type": "character", "path": path, "slot": slot}
        self.notifier.toast(tr("Character copied. Select a slot and press Ctrl+V."))

    @Slot(str, str, int)
    def copyLibraryCharacterKey(self, folder: str, entry_id: str, slot: int) -> None:
        self._clip = {"type": "copychar", "folder": folder, "id": entry_id, "slot": slot}
        self.notifier.toast(tr("Character copied. Select a slot and press Ctrl+V."))

    @Slot("QVariant")
    def pasteInto(self, target) -> None:
        if not self._clip:
            self.notifier.toast(tr("Copy a character first (Ctrl+C on its row)."), error=True)
            return
        self.drop(self._clip, target)

    # ---- 4. Back up now
    @Slot(str)
    def backUpNow(self, path: str) -> None:
        if not self._blocked():
            self._job("saves.back_up", {"paths": [path]})

    # ---- 3. Save a copy
    @Slot(str, result=str)
    def defaultName(self, path: str) -> str:
        try:
            return self.host.session.run("saves.default_name", {"path": path}).text
        except OperationError:
            return ""

    @Slot(str, str)
    def saveCopy(self, path: str, name: str) -> None:
        if not self._blocked(read_only=True):  # only reads the live save; the Library check rejects a half-written file
            self._job("saves.save_copy", {"path": path, "name": name})

    # ---- 5. Import
    @Slot()
    def pickImport(self) -> None:
        got = self.host.pick_file(tr("Import a save file into the Library"), "Save files (*.sl2 *.co2);;All files (*)")
        if got is not None:
            self._offer_import(got)

    @Slot("QVariantList")
    def dropFiles(self, urls: list) -> None:
        """Files from Explorer: one save file asks for a name; several import each under its own name, and any that
        are not save files are named in a toast (never silently dropped)."""
        paths = [Path(t[8:] if t.startswith("file:///") else t.removeprefix("file://")) for t in map(str, urls)]
        good = [p for p in paths if p.suffix.lower() in (".sl2", ".co2")]
        skipped = [p.name for p in paths if p not in good]
        if skipped:
            self.notifier.toast(
                tr("Not imported, these are not save files (.sl2 or .co2): {names}").format(names=", ".join(skipped)),
                error=True,
            )
        if len(good) == 1:
            self._offer_import(good[0])
        elif good:
            self._import_many(good)

    def _has_library(self) -> bool:
        if not (self._libs or self._infos):
            self.notifier.toast(tr("Play once so the game creates its save folder."), error=True)
            return False
        return True

    def _import_many(self, paths: list[Path]) -> None:
        if not self._blocked(read_only=True) and self._has_library():
            self._job("saves.import_files", {"files": [str(p) for p in paths]})

    def _offer_import(self, path: Path) -> None:
        if not self._blocked(read_only=True):
            self.importNameRequested.emit(str(path), self.defaultName(str(path)))

    @Slot(str, str)
    def importFile(self, path: str, name: str) -> None:
        if not self._blocked(read_only=True) and self._has_library():
            self._job("saves.import_files", {"files": [path], "name": name})

    # ---- 1. Copy a character (also Duplicate in the same file)
    @Slot(str, int, result=list)
    def copyTargets(self, source: str, slot: int) -> list:
        """Where a character can go: every slot of every live save (an empty slot, or one it replaces)."""
        out = []
        for c in self._cards():
            kind = c["kind"]
            by_slot = {ch["slot"]: ch for ch in c["characters"]}
            for n in range(1, 11):
                if str(c["path"]) == str(source) and n == slot:
                    continue
                old = by_slot.get(n)
                out.append(
                    {
                        "path": c["path"],
                        "slot": n,
                        "danger": old is not None,
                        "label": tr("{kind}  ·  slot {n}  ·  replaces {name}").format(kind=kind, n=n, name=old["name"])
                        if old
                        else tr("{kind}  ·  slot {n}  ·  empty").format(kind=kind, n=n),
                    }
                )
        return out

    @Slot(str, int, str, int)
    def copyCharacter(self, source: str, src_slot: int, target: str, dst_slot: int) -> None:
        if not self._blocked():
            self._ask(
                "saves.copy_character",
                {"source": source, "src_slot": src_slot, "target": target, "dst_slot": dst_slot},
            )

    # ---- 2. Replace a live save with a file
    @Slot(str, str, str)
    def replaceFromLibrary(self, folder: str, entry_id: str, target: str) -> None:
        if self._blocked():
            return
        plan = {"folder": folder, "entry_id": entry_id, "target": target}

        def checked(entry) -> None:
            if entry.changed_outside:  # the copy's file is not what the launcher stored: ask first
                self.notifier.ask(
                    self.presenter.changed_outside(entry.name),
                    lambda ok, _o: self._ask("saves.replace_from_library", plan) if ok else None,
                )
            else:
                self._ask("saves.replace_from_library", plan)

        self._call(
            "saves.copy_entry", {"folder": folder, "entry_id": entry_id}, checked, fail=tr("This copy cannot be used")
        )

    @Slot(str)
    def replaceFromFile(self, target: str) -> None:
        if self._blocked():
            return
        src = self.host.pick_file(tr("Replace with a save file"), "Save files (*.sl2 *.co2);;All files (*)")
        if src is not None:
            self._ask("saves.replace_from_file", {"source": str(src), "target": target})

    @Slot(str, str)
    def restoreBackup(self, backup: str, target: str) -> None:
        if not self._blocked():
            self._ask("saves.restore_backup", {"backup": backup, "target": target})

    # ---- the saved copies' upkeep (the Library file and the Backups list; no live save is written)
    @Slot(str, str)
    def keepAs(self, backup: str, name: str) -> None:
        def kept(got) -> None:
            self.notifier.toast(tr("Kept as '{name}' in the Library").format(name=got.text))
            self._read()

        self._call("saves.keep_as", {"backup": backup, "name": name}, kept, fail=tr("Could not keep it"))

    @Slot(str)
    def letAgeOut(self, backup: str) -> None:
        self._call(
            "saves.keep_backup",
            {"backup": backup, "keep": False},
            lambda _r: self._read(),
            fail=tr("Could not change it"),
        )

    @Slot(str)
    def deleteBackup(self, backup: str) -> None:
        def removed() -> None:
            self.notifier.toast(tr("Backup removed"))
            self._read()

        self._ask("saves.delete_backup", {"backup": backup}, fail=tr("Could not remove"), then=removed)

    @Slot(str, str, str)
    def renameCopy(self, folder: str, entry_id: str, name: str) -> None:
        self._call(
            "saves.rename_copy",
            {"folder": folder, "entry_id": entry_id, "name": name},
            lambda _r: self._read(),
            fail=tr("Could not rename"),
        )

    @Slot(str, str)
    def removeCopy(self, folder: str, entry_id: str) -> None:
        self._ask(
            "saves.remove_copy", {"folder": folder, "entry_id": entry_id}, fail=tr("Could not remove"), then=self._read
        )

    @Slot(str, str, bool)
    def finishStranded(self, folder: str, entry_id: str, restore: bool) -> None:
        def finished(got) -> None:
            if got.warning:
                self.notifier.toast(got.warning)

        self._call(
            "saves.finish_stranded",
            {"folder": folder, "entry_id": entry_id, "restore": restore},
            finished,
            fail=tr("Could not finish it"),
            settle=self._read,
        )

    @Slot(str)
    def openFolder(self, path: str) -> None:
        self.host.open_path(Path(path).parent)

    @Slot()
    def openBackups(self) -> None:
        self._open("backups")

    @Slot()
    def openLibrary(self) -> None:
        self._open("library")

    @Slot(str)
    def copyReport(self, path: str) -> None:
        def copied(got) -> None:
            from PySide6.QtGui import QGuiApplication

            QGuiApplication.clipboard().setText(got.text)
            self.notifier.toast(tr("Report copied"))

        self._call("saves.health_report", {"path": path}, copied)

    @Slot()
    def postSessionRepair(self) -> None:
        if not self._blocked():
            self._job("saves.post_session_repair", None)

    # ---- Check & repair
    @Slot(str)
    def openRepair(self, path: str) -> None:
        self._repair_path, self._repair_slot = path, -1
        self._reload_repair(reset=True)

    @Slot()
    def closeRepair(self) -> None:
        self._repair_path = ""
        self.repairChanged.emit()

    @Slot(int)
    def pickRepairSlot(self, slot: int) -> None:
        self._repair_slot = slot
        self.repairChanged.emit()

    def _reload_repair(self, reset: bool = False) -> None:
        info = self._info(self._repair_path)
        if info is None:
            self._repair_path = ""
        elif reset:
            self._ticks = set(self.presenter.default_ticks(self.presenter.repair_groups(info)))
        else:
            known = {i["key"] for g in self.presenter.repair_groups(info) for i in g["items"]}
            self._ticks &= known
        self.repairChanged.emit()

    def _repair_card(self) -> dict:
        info = self._info(self._repair_path)
        if info is None:
            return {}
        return self.presenter.card(info, self._role(info["name"]), bool(self.host.game_running))

    def _repair_groups(self) -> list[dict]:
        info = self._info(self._repair_path)
        if info is None:
            return []
        slot = None if self._repair_slot < 0 else self._repair_slot
        self._keys = {}
        groups = []
        for g in self.presenter.repair_groups(info, slot):
            items = []
            for i in g["items"]:
                self._keys[i["key"]] = i["tuple"]
                items.append({k: v for k, v in i.items() if k != "tuple"} | {"checked": i["key"] in self._ticks})
            groups.append({**g, "items": items})
        return groups

    def _repair_damaged(self) -> list[dict]:
        info = self._info(self._repair_path)
        return self.presenter.damaged(info) if info else []

    def _ticked(self) -> list[tuple]:
        info = self._info(self._repair_path)
        if info is None:
            return []
        every = {i["key"]: i["tuple"] for g in self.presenter.repair_groups(info) for i in g["items"]}
        return [every[k] for k in sorted(self._ticks) if k in every]

    @Slot(str, bool)
    def setTick(self, key: str, on: bool) -> None:
        (self._ticks.add if on else self._ticks.discard)(key)
        self.repairChanged.emit()

    @Slot(str, bool)
    def setGroup(self, group: str, on: bool) -> None:
        for g in self._repair_groups():
            if g["id"] == group:
                for i in g["items"]:
                    if i["enabled"]:
                        (self._ticks.add if on else self._ticks.discard)(i["key"])
        self.repairChanged.emit()

    @Slot()
    def applyRepair(self) -> None:
        if self._blocked():
            return
        info, keys = self._info(self._repair_path), self._ticked()
        if info is not None and keys:
            self._ask("saves.repair", {"path": str(info["path"]), "keys": [list(k) for k in keys]})

    # ---- the character sheet (read-only)
    @Slot(str, int)
    def openSheet(self, path: str, slot: int) -> None:
        self._sheet_path, self._sheet_slot = path, slot
        self._reload_sheet()

    @Slot()
    def closeSheet(self) -> None:
        self._sheet_open = False
        self.sheetChanged.emit()

    def _reload_sheet(self) -> None:
        """Read the character from the session; the sheet opens (or refreshes) when it lands."""
        path, slot = self._sheet_path, self._sheet_slot
        if self._info(path) is None:
            self._sheet = {}
            self.closeSheet()
            return

        def shown(got) -> None:
            if (path, slot) == (self._sheet_path, self._sheet_slot):  # not for a character the user has left
                self._sheet_open = True
                self._sheet = got.data | {"path": path}
                self.sheetChanged.emit()

        self._call("saves.sheet", {"path": path, "slot": slot}, shown)
