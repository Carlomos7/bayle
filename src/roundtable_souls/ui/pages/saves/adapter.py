"""The Saves page's adapter: the thin QObject the QML page binds to (technical specification §8.10, Saves). What to show
comes from the presenter, what a change does from services/saves.py and the saves package.

The read (every live save, the Library, the Backups) runs on the host's worker. Each of the five operations is one
slot: it checks the game is closed and no job runs, plans the change on the worker, asks in the presenter's words, and
runs the write as a logged job whose body waits for the game to let go of the file (services.saves.assert_writable),
backs up first and records how to take it back (the Activity's Undo). The result is told by a toast with Undo once the
page is read again."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from roundtable_souls.game import catalog as games
from roundtable_souls.mods import undo as mod_undo
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.saves import backups as save_backups
from roundtable_souls.saves import library as save_library
from roundtable_souls.saves import repair as save_repair
from roundtable_souls.saves import transfer as save_transfer
from roundtable_souls.services import saves as saves_service
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.mods.presenter import Refusal
from roundtable_souls.ui.pages.saves.presenter import SavesPresenter
from roundtable_souls.ui.text import tr


class SavesHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell)."""

    @property
    def busy(self) -> bool: ...
    @property
    def game_running(self) -> bool: ...
    @property
    def locations(self) -> Any: ...
    def run_job(self, job, status: str) -> None: ...
    def run_in_background(self, work, on_result) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None: ...
    def open_path(self, path: Path) -> None: ...
    def saves_in_use(self) -> dict:
        """The save files the setup in use plays on by name: {active, standard, coop} ({} without a setup)."""
        ...


def apply_repairs(path: Path, calls: dict, *, loc) -> Path | None:
    """Check & repair's writes, in order: loading fixes, mod items, checksums, the regulation block. Returns the
    FIRST backup taken (the file as it was before anything changed), which is what Undo goes back to."""
    backups = []
    if calls["loading"]:
        backups.append(saves_service.fix_loading(path, selection=calls["loading"], loc=loc).get("backup"))
    if calls["vanilla"]:
        backups.append(saves_service.restore_vanilla(path, selection=calls["vanilla"], loc=loc).get("backup"))
    if calls["checksums"]:
        backups.append(saves_service.fix_checksums(path, loc=loc).get("backup"))
    if calls["regulation"]:
        saves_service.repair_save(path, loc=loc)
    return next((b for b in backups if b), None)


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
        self._token = 0
        self._after: dict = {}  # filled by a job: {text, save, backup}; told at the next read
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
    retention = Property(
        str, lambda self: self.presenter.retention(save_backups.KEEP_NEWEST, save_backups.KEEP_DAYS), constant=True
    )
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
        self.notifier.toast(tr("Open a character's menu and choose Copy character to..."))

    def _open_saves_folder(self) -> None:
        if self._infos:
            self.host.open_path(Path(self._infos[0]["path"]).parent)

    def backUpAll(self) -> None:
        """Saves > Back up now: one backup of every live save of this game."""
        if self._blocked():
            return
        paths = [Path(i["path"]) for i in self._infos]

        def body(loc):
            made = [saves_service.back_up_now(p, loc=loc) for p in paths]
            return {"text": tr("Backed up {n} save file(s).").format(n=len(made))}

        self._write("back up now", tr("Backing up saves..."), body)

    @Slot()
    def refresh(self) -> None:
        loc = self.host.locations
        self._token += 1
        token = self._token
        if loc is None:
            self._infos, self._libs, self._backups, self._names, self._loading = [], {}, [], {}, False
            self.changed.emit()
            return
        self._loading = True
        self.changed.emit()
        game = loc.game
        try:
            self._names = self.host.saves_in_use()  # on this thread, before the read: the locations learn the names
        except Exception:
            self._names = {}

        def work():
            files = loc.save_files()
            for d in {p.parent for p in files}:  # older tools may still drop backup folders beside the saves
                save_backups.adopt_legacy_save_folders(d, game, again=True)
            infos = [saves_service.save_info(p, game, loc=loc) for p in files]
            libs = {str(f): save_library.load(f) for f in sorted({p.parent for p in files})}
            try:
                backups = saves_service.list_backups(loc=loc)
            except Exception:
                backups = []
            return token, infos, libs, backups

        self.host.run_in_background(work, self._apply)

    def _apply(self, got) -> None:
        token, infos, libs, backups = got
        if token != self._token:  # a newer read superseded this one
            return
        loc = self.host.locations
        self._infos = [i for i in infos if loc is None or games.for_save(i["path"]) in (loc.game, None)]
        self._libs, self._backups, self._loading = libs, backups, False
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
            save, backup = after["save"], after["backup"]
            self.notifier.toast_action(text, self._words["undo"], lambda: self._undo(save, backup))
        elif text:
            self.notifier.toast(text)

    def _undo(self, save: Path, backup: Path) -> None:
        """The toast's Undo: the same record the Activity page offers (mods.undo, type save-restore)."""
        record = {"type": "save-restore", "save": str(save), "backup": str(backup), "name": save.name}
        if self._blocked():
            return

        def job(_launch, loc):
            run_logging.start_log(f"launcher: undo the last change to {save.name}", loc.game.key)
            try:
                said = mod_undo.run(record, run_logging.log, loc=loc)
            except (mod_undo.UndoError, OSError) as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e
            run_logging.log(f"done: {said}")

        self.host.run_job(job, tr("Undoing the change to {name}...").format(name=save.name))

    # ---- the gate every write goes through
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

    def _write(self, log_title: str, status: str, body) -> None:
        """Run body(loc) as a logged job. body returns {text, save?, backup?}: the toast's words, and how to take
        the change back (the Activity's Undo and the toast's)."""
        after = self._after

        def job(_launch, loc):
            run_logging.start_log(f"launcher: {log_title}", loc.game.key)
            try:
                out = body(loc)
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e
            if out.get("backup"):
                run_logging.set_undo(
                    {
                        "type": "save-restore",
                        "save": str(out["save"]),
                        "backup": str(out["backup"]),
                        "name": Path(out["save"]).name,
                    }
                )
            after.clear()
            after.update(out)
            run_logging.log(f"done: {out['text']}")

        self.host.run_job(job, status)

    def _plan(self, work, then) -> None:
        """Plan a change on the worker (it reads whole saves), then ask about it. work() -> a Refusal or (Confirm,
        context, destructive); then(context) runs on the user's yes."""

        def done(got) -> None:
            if isinstance(got, Refusal):
                self._refuse(got)
                return
            words, context, destructive = got
            self.notifier.ask(
                words, lambda ok, _o: then(context) if ok and not self._blocked() else None, destructive=destructive
            )

        def safe():
            try:
                return work()
            except Exception as e:
                return Refusal(tr("This cannot be done"), str(e))

        self.host.run_in_background(safe, done)

    def _game(self):
        loc = self.host.locations
        return loc.game

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
        try:
            entry = save_library.find(self._libs.get(folder) or save_library.load(Path(folder)), entry_id)
            src = save_library.entry_path(Path(folder), entry)
        except Exception as e:
            self._refuse(Refusal(tr("This copy cannot be used"), str(e)))
            return
        if not src.is_file():
            self._refuse(Refusal(tr("This copy cannot be used"), tr("Its file is missing from the Library.")))
            return
        self.copyCharacter(str(src), src_slot, target, dst_slot)

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
        if self._blocked():
            return
        save = Path(path)

        def body(loc):
            bak = saves_service.back_up_now(save, loc=loc)
            return {"text": tr("Backed up {name} ({file})").format(name=save.name, file=bak.name)}

        self._write(f"back up {save.name}", tr("Backing up {name}...").format(name=save.name), body)

    # ---- 3. Save a copy
    @Slot(str, result=str)
    def defaultName(self, path: str) -> str:
        return save_library.default_name(Path(path), self._game())

    @Slot(str, str)
    def saveCopy(self, path: str, name: str) -> None:
        if self._blocked(read_only=True):  # only reads the live save; the Library check rejects a half-written file
            return
        save, game = Path(path), self._game()

        def body(loc):
            e = save_library.add(save.parent, save, name, game, action="stash")
            return {"text": tr("Saved a copy of {file} as '{name}'").format(file=save.name, name=e["name"])}

        self._write(f"save a copy of {save.name}", tr("Saving a copy of {name}...").format(name=save.name), body)

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

    def _library_folder(self) -> Path | None:
        folders = [Path(f) for f in self._libs] or sorted({Path(i["path"]).parent for i in self._infos})
        if not folders:
            self.notifier.toast(tr("Play once so the game creates its save folder."), error=True)
            return None
        return folders[0]

    def _import_many(self, paths: list[Path]) -> None:
        if self._blocked(read_only=True):
            return
        folder, game = self._library_folder(), self._game()
        if folder is None:
            return

        def body(loc):
            done, failed = [], []
            for src in paths:
                try:
                    save_library.add(folder, src, save_library.default_name(src, game), game, action="import")
                    done.append(src.name)
                except Exception as e:
                    run_logging.log(f"error: {src.name}: {e}")
                    failed.append(src.name)
            if not done:
                raise RuntimeError(tr("None of these files could be imported: {names}").format(names=", ".join(failed)))
            text = tr("Imported {n} files into the Library").format(n=len(done))
            if failed:
                text += tr(". Not imported: {names}").format(names=", ".join(failed))
            return {"text": text}

        self._write("import several files into the Library", tr("Importing {n} files...").format(n=len(paths)), body)

    def _offer_import(self, path: Path) -> None:
        if self._blocked(read_only=True):
            return
        self.importNameRequested.emit(str(path), save_library.default_name(path, self._game()))

    @Slot(str, str)
    def importFile(self, path: str, name: str) -> None:
        if self._blocked(read_only=True):
            return
        src, game = Path(path), self._game()
        folder = self._library_folder()
        if folder is None:
            return

        def body(loc):
            e = save_library.add(folder, src, name, game, action="import")
            return {"text": tr("Imported '{name}' into the Library").format(name=e["name"])}

        self._write(f"import {src.name} into the Library", tr("Importing {name}...").format(name=src.name), body)

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
        if self._blocked():
            return
        src, dst = Path(source), Path(target)
        same = src.resolve() == dst.resolve()

        def work():
            plan = save_transfer.plan_character_copy(src, src_slot, dst, dst_slot)
            return self.presenter.character_copy(plan, src.name, dst.name, dst_slot, same), plan, bool(plan["replaces"])

        def go(plan) -> None:
            who = (plan["character"] or {}).get("name", "?")

            def body(loc):
                saves_service.assert_writable(dst, loc=loc)
                out = save_transfer.copy_character(src, src_slot, dst, dst_slot)
                return {
                    "text": tr("{who} is in slot {n} of {file}").format(who=who, n=dst_slot, file=dst.name),
                    "save": dst,
                    "backup": out["backup"],
                }

            self._write(
                f"copy slot {src_slot} of {src.name} into slot {dst_slot} of {dst.name}",
                tr("Copying a character into {name}...").format(name=dst.name),
                body,
            )

        self._plan(work, go)

    # ---- 2. Replace a live save with a file
    def _replace(self, source: Path, target: Path, source_label: str, run, restore: bool = False) -> None:
        """Plan Replace (the compare table, the signing) and, on yes, run(loc) -> {backup, kept?}."""
        game = self._game()
        live = next((i for i in self._infos if Path(i["path"]) == source), None)
        holders = sum(1 for p in (live or {}).get("vanilla_plan") or [] if p.get("strip"))  # only a live source is read

        def work():
            rows = save_transfer.compare(source, target, game) if target.exists() else []
            signed = save_library.signed_for_account(source.read_bytes(), target, game)[1]
            kinds = None
            if source.suffix.lower() != target.suffix.lower():
                kinds = (self.presenter.kind_of(source), self.presenter.kind_of(target))
            words = self.presenter.replace(
                source_label,
                target.name,
                rows,
                signed,
                holders,
                target.suffix.lower() == ".sl2",
                restore=restore,
                kinds=kinds,
            )
            return words, None, True

        def go(_context) -> None:
            def body(loc):
                saves_service.assert_writable(target, loc=loc)
                out = run(loc)
                return {
                    "text": tr("{target} now holds {source}").format(target=target.name, source=source_label),
                    "save": target,
                    "backup": out.get("backup"),
                }

            self._write(
                f"replace {target.name} with {source_label}",
                tr("Replacing {name}...").format(name=target.name),
                body,
            )

        self._plan(work, go)

    @Slot(str, str, str)
    def replaceFromLibrary(self, folder: str, entry_id: str, target: str) -> None:
        if self._blocked():
            return
        game, tgt = self._game(), Path(target)
        doc = self._libs.get(folder) or save_library.load(Path(folder))
        try:
            entry = save_library.find(doc, entry_id)
        except Exception as e:
            self._refuse(Refusal(tr("This copy cannot be used"), str(e)))
            return
        source = save_library.entry_path(Path(folder), entry)
        if not source.is_file():
            self._refuse(Refusal(tr("This copy cannot be used"), tr("Its file is missing from the Library.")))
            return

        def run(_loc):
            out = save_library.swap_in(Path(folder), entry_id, tgt, None, game)
            return {"backup": out["backup"]}

        if save_library.changed_outside(Path(folder), entry):
            self.notifier.ask(
                self.presenter.changed_outside(entry["name"]),
                lambda ok, _o: self._replace(source, tgt, entry["name"], run, True) if ok else None,
            )
            return
        self._replace(source, tgt, entry["name"], run, True)

    @Slot(str)
    def replaceFromFile(self, target: str) -> None:
        if self._blocked():
            return
        src = self.host.pick_file(tr("Replace with a save file"), "Save files (*.sl2 *.co2);;All files (*)")
        if src is None:
            return
        game, tgt = self._game(), Path(target)

        def run(_loc):
            out = save_transfer.copy_file(src, tgt, game)
            return {"backup": out["backup"]}

        self._replace(src, tgt, src.name, run)

    @Slot(str, str)
    def restoreBackup(self, backup: str, target: str) -> None:
        if self._blocked():
            return
        bak, tgt = Path(backup), Path(target)
        row = next((b for b in self._backups if str(b["path"]) == backup), None)
        if row is None:
            return
        words = self.presenter.restore(row, tgt.name)

        def go() -> None:
            def body(loc):
                safety = saves_service.restore_backup(bak, tgt, loc=loc)
                return {
                    "text": tr("{name} is back as it was in the backup").format(name=tgt.name),
                    "save": tgt,
                    "backup": safety,
                }

            self._write(f"restore backup {bak.name}", tr("Restoring {name}...").format(name=tgt.name), body)

        self.notifier.ask(words, lambda ok, _o: go() if ok and not self._blocked() else None)

    # ---- the saved copies' upkeep (the Library file and the Backups list; no live save is written)
    @Slot(str, str)
    def keepAs(self, backup: str, name: str) -> None:
        try:
            e = saves_service.keep_backup_as_copy(Path(backup), name, loc=self.host.locations)
        except Exception as ex:
            self._refuse(Refusal(tr("Could not keep it"), str(ex)))
            return
        self.notifier.toast(tr("Kept as '{name}' in the Library").format(name=e["name"]))
        self.refresh()

    @Slot(str)
    def letAgeOut(self, backup: str) -> None:
        try:
            saves_service.keep_backup(Path(backup), False)
        except OSError as e:
            self._refuse(Refusal(tr("Could not change it"), str(e)))
            return
        self.refresh()

    @Slot(str)
    def deleteBackup(self, backup: str) -> None:
        row = next(
            (b for d in self.presenter.backup_days(self._backups) for b in d["rows"] if b["path"] == backup), None
        )
        if row is None:
            return

        def go() -> None:
            try:
                saves_service.delete_backup(Path(backup))
            except Exception as e:
                self._refuse(Refusal(tr("Could not remove"), str(e)))
                return
            self.notifier.toast(tr("Backup removed"))
            self.refresh()

        self.notifier.ask(self.presenter.delete_backup(row), lambda ok, _o: go() if ok else None, destructive=True)

    @Slot(str, str, str)
    def renameCopy(self, folder: str, entry_id: str, name: str) -> None:
        try:
            save_library.rename(Path(folder), entry_id, name)
        except Exception as e:
            self._refuse(Refusal(tr("Could not rename"), str(e)))
            return
        self.refresh()

    @Slot(str, str)
    def removeCopy(self, folder: str, entry_id: str) -> None:
        entry = next((e for e in (self._libs.get(folder) or {}).get("entries", []) if e["id"] == entry_id), None)
        if entry is None:
            return

        def go() -> None:
            try:
                save_library.remove(Path(folder), entry_id)
            except Exception as e:
                self._refuse(Refusal(tr("Could not remove"), str(e)))
                return
            self.refresh()

        self.notifier.ask(
            self.presenter.remove_copy(entry["name"]), lambda ok, _o: go() if ok else None, destructive=True
        )

    @Slot(str, str, bool)
    def finishStranded(self, folder: str, entry_id: str, restore: bool) -> None:
        try:
            if restore:
                warning = save_library.restore_removed(Path(folder), entry_id)
                if warning:
                    self.notifier.toast(warning)
            else:
                save_library.finish_removal(Path(folder), entry_id)
        except Exception as e:
            self._refuse(Refusal(tr("Could not finish it"), str(e)))
        self.refresh()

    @Slot(str)
    def openFolder(self, path: str) -> None:
        self.host.open_path(Path(path).parent)

    @Slot()
    def openBackups(self) -> None:
        folders = saves_service.backup_folders(loc=self.host.locations) if self.host.locations else []
        if folders:
            folders[0].mkdir(parents=True, exist_ok=True)
            self.host.open_path(folders[0])

    @Slot()
    def openLibrary(self) -> None:
        folders = [Path(f) for f in self._libs] or sorted({Path(i["path"]).parent for i in self._infos})
        if folders:
            lib = save_library.folder_for(folders[0])
            lib.mkdir(parents=True, exist_ok=True)
            self.host.open_path(lib)

    @Slot(str)
    def copyReport(self, path: str) -> None:
        info = self._info(path)
        if info is None:
            return
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(saves_service.health_report(info=info))
        self.notifier.toast(tr("Report copied"))

    @Slot()
    def postSessionRepair(self) -> None:
        if self._blocked():
            return

        def body(loc):
            save_repair.repair_all(loc)
            return {"text": tr("Post-session repair finished")}

        self._write("post-session repair", tr("Repairing saves..."), body)

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
        if info is None or not keys:
            return
        path, calls = Path(info["path"]), self.presenter.calls(keys)

        def go() -> None:
            def body(loc):
                first = apply_repairs(path, calls, loc=loc)
                return {
                    "text": tr("Repaired {name}").format(name=path.name),
                    "save": path,
                    "backup": first,
                }

            self._write(
                f"repair {len(keys)} item(s) in {path.name}",
                tr("Repairing {name}...").format(name=path.name),
                body,
            )

        self.notifier.ask(
            self.presenter.repair_confirm(info, keys), lambda ok, _o: go() if ok and not self._blocked() else None
        )

    # ---- the character sheet (read-only)
    @Slot(str, int)
    def openSheet(self, path: str, slot: int) -> None:
        self._sheet_path, self._sheet_slot = path, slot
        self._sheet_open = True
        self._reload_sheet()

    @Slot()
    def closeSheet(self) -> None:
        self._sheet_open = False
        self.sheetChanged.emit()

    def _reload_sheet(self) -> None:
        info = self._info(self._sheet_path)
        self._sheet = (self.presenter.sheet(info, self._sheet_slot) | {"path": self._sheet_path}) if info else {}
        if not self._sheet:
            self._sheet_open = False
        self.sheetChanged.emit()
