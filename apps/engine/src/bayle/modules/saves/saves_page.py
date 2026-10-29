"""What the Saves page reads and the writes it runs, without Qt: the page's facts (live saves, Library, Backups), the
Library's upkeep, and each write as one logged job that backs up first and returns how to take it back. The session's
saves operations and the Qt page call this; nothing here knows a window.

A write is logged_write(): it names the job (start_log), runs the body, records the undo (a save-restore record built
by restore_record, the one place that builds it) and returns Written, which carries that record."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from bayle.adapters.filesystem import filelock
from bayle.adapters.filesystem.files import Unsettled
from bayle.adapters.system import logging as run_logging
from bayle.errors import Cancelled, OperationError
from bayle.modules.activity import service as activity_service
from bayle.modules.games import catalog as games
from bayle.modules.games.locate import Locations
from bayle.modules.saves import backups as save_backups
from bayle.modules.saves import library as save_library
from bayle.modules.saves import repair as save_repair
from bayle.modules.saves import service as saves_service
from bayle.modules.saves import transfer as save_transfer
from bayle.work.jobs import JobManager
from bayle.work.runner import run_job_result, run_logged


@dataclass(frozen=True)
class Written:
    """What a save write did: a line for the job's log, the facts the client words (character, slot, file...), and how
    to take it back (save and the backup taken first, and the undo record the jobs index holds for it)."""

    text: str
    facts: dict = field(default_factory=dict)
    save: Path | None = None
    backup: Path | None = None
    undo: dict | None = None

    def result(self) -> dict:
        """The job's result: the facts and the Undo record's parts, as plain data."""
        return {
            **self.facts,
            "save": None if self.save is None else str(self.save),
            "backup": None if self.backup is None else str(self.backup),
            "undo": self.undo,
        }


@dataclass(frozen=True)
class BackupFacts:
    """One listed backup, as a removal asks about it: stamp (size, mtime) is what the client confirms."""

    path: Path
    save_name: str
    when: str
    action: str
    size: int
    mtime: float

    @property
    def stamp(self) -> tuple[int, float]:
        return self.size, self.mtime


@dataclass(frozen=True)
class SavesFacts:
    infos: list[dict]
    libraries: dict[str, dict]
    backups: list[dict]


def restore_record(save: Path, backup: Path) -> dict:
    """The Undo record of a save write: put the backup back over the save (mods.undo type save-restore)."""
    return {"type": "save-restore", "save": str(save), "backup": str(backup), "name": Path(save).name}


def logged_write(log_title: str, progress: str, loc: Locations, body: Callable[[Locations], Written]) -> Written:
    """Run body(loc) as a logged job of its own (its log and jobs-index record, as before), on this (worker) thread.
    Raises OperationError when it failed (the message is the reason), Cancelled when it was stopped."""

    def job(_launch: Any, loc: Locations) -> Written:
        try:
            with run_logged(f"launcher: {log_title}", loc.game.key):
                out = body(loc)
        except OperationError:
            raise
        except Exception as e:  # a code, not an unexpected failure: the file the write stopped on is left as it was
            raise _coded(e) from e
        if out.backup is not None and out.save is not None:
            run_logging.set_undo(restore_record(out.save, out.backup))
        run_logging.log(f"done: {out.text}")
        return out

    done = run_job_result(job, None, loc, progress)
    if done.state == "done":
        return replace(done.result, undo=done.undo)
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError.from_info(done.error)


# ----------------------------------------------------------------------------- reading
def retention_limits() -> tuple[int, int]:
    """How many backups of each save are kept, and for how many days (what the Backups tab says)."""
    return save_backups.KEEP_NEWEST, save_backups.KEEP_DAYS


def live_saves(loc: Locations) -> list[Path]:
    """The save files of the game in use (a file of another game beside them is left out)."""
    return [p for p in loc.save_files() if games.for_save(p) in (loc.game, None)]


def adopt_legacy_folders(loc: Locations) -> list[str]:
    """Take in the backup folders older tools dropped beside the saves. Writes (moves them); never part of a read."""
    folders = sorted({p.parent for p in loc.save_files()})
    for d in folders:
        save_backups.adopt_legacy_save_folders(d, loc.game, again=True)
    return [str(d) for d in folders]


def read_facts(loc: Locations) -> SavesFacts:
    """Every live save, the Library of each save folder and the Backups. Reads only."""
    files = loc.save_files()
    infos = [saves_service.save_info(p, loc.game, loc=loc) for p in files]
    infos = [i for i in infos if games.for_save(i["path"]) in (loc.game, None)]
    libs = {str(f): save_library.load(f) for f in sorted({p.parent for p in files})}
    try:
        backups = saves_service.list_backups(loc=loc)
    except Exception:
        backups = []
    return SavesFacts(infos, libs, backups)


def replace_facts(source: Path, target: Path, *, loc: Locations) -> dict:
    """What Replace shows before it writes: the slot-by-slot compare, whether the file gets signed for the target's
    account, and how many mod-item holders a live source carries."""
    source, target = Path(source), Path(target)
    game = loc.game
    rows = save_transfer.compare(source, target, game) if target.exists() else []
    signed = save_library.signed_for_account(source.read_bytes(), target, game)[1]
    holders = 0
    if source in live_saves(loc):  # only a live source is read for its mod items
        holders = sum(
            1 for p in saves_service.save_info(source, game, loc=loc).get("vanilla_plan") or [] if p.get("strip")
        )
    return {"rows": rows, "signed": signed, "holders": holders}


# ----------------------------------------------------------------------------- the Library
def library_folder(loc: Locations) -> Path:
    folders = sorted({p.parent for p in loc.save_files()})
    if not folders:
        raise OperationError("no_saves", "Play once so the game creates its save folder.")
    return folders[0]


def library_entry(folder: Path, entry_id: str) -> dict:
    """One Library copy: {name, path, changed_outside}. Raises OperationError when the copy cannot be used."""
    try:
        entry = save_library.find(save_library.load(folder), entry_id)
        path = save_library.entry_path(folder, entry)
    except Exception as e:
        raise OperationError("copy_unusable", str(e)) from e
    if not path.is_file():
        raise OperationError("copy_unusable", "Its file is missing from the Library.")
    return {"name": entry["name"], "path": path, "changed_outside": save_library.changed_outside(folder, entry)}


def library_default_name(path: Path, loc: Locations) -> str:
    return save_library.default_name(Path(path), loc.game)


def open_folder(which: str, *, loc: Locations) -> Path | None:
    """The folder to show for "saves", "backups" or "library" (the last two are made first); None when no save exists."""
    folders = sorted({p.parent for p in loc.save_files()})
    if which == "saves":
        return folders[0] if folders else None
    if which == "backups":
        found = saves_service.backup_folders(loc=loc)
        target = found[0] if found else None
    else:
        target = save_library.folder_for(folders[0]) if folders else None
    if target is not None:
        target.mkdir(parents=True, exist_ok=True)
    return target


# ----------------------------------------------------------------------------- copying in and backing up (C, D)
def failure_code(e: BaseException) -> str:
    """The OperationError code of a failure to read a source save or to keep its copy (Save a copy, Import, Back
    up). Codes, never words: the client says them."""
    if isinstance(e, Unsettled):
        return "source_locked" if e.locked else "source_changed"
    if isinstance(e, FileNotFoundError):
        return "not_found"
    if isinstance(e, save_library.NotASave):
        return "not_a_save"
    if isinstance(e, save_library.LibraryUnreadable):
        return "library_unreadable"
    if isinstance(e, (save_library.LibraryBusy, filelock.Busy)):
        return "library_busy"
    return "failed"


def _coded(e: Exception, **details: Any) -> OperationError:
    if isinstance(e, OperationError):
        return e
    # the code is for the player; the traceback stays in the job's log for whoever reads it
    run_logging.get_logger("job").error("error: %s", e, exc_info=e)
    return OperationError(failure_code(e), str(e), details)


def back_up(saves: list[Path], *, loc: Locations) -> dict:
    """Back up each live save as it is now, in order: {"saves", "backups"} (paths, one backup per save). The saves
    are only read. A failure part way raises the failure's code; the backups already taken stay (they are harmless)
    and its details name them."""
    made: list[str] = []

    def body(loc: Locations) -> Written:
        for save in saves:
            try:
                made.append(str(saves_service.back_up_now(save, loc=loc)))
            except Exception as e:
                raise _coded(e, save=str(save), backed_up=list(made)) from e
        return Written(f"backed up {len(made)} save file(s)")

    # the progress words are the jobs index's title, which Activity lists (worded here until records carry facts)
    if len(saves) == 1:
        logged_write(f"back up {saves[0].name}", f"Backing up {saves[0].name}...", loc, body)
    else:
        logged_write("back up now", "Backing up saves...", loc, body)
    return {"saves": [str(s) for s in saves], "backups": made}


def save_copy(save: Path, name: str, *, loc: Locations) -> dict:
    """Add a copy of a live save to the Library (its folder's): {"source", "entry_id", "name"}. The save is only
    read, as one consistent snapshot (allowed while the game runs: a read that keeps changing is source_changed)."""
    out: dict = {"source": str(save)}

    def body(loc: Locations) -> Written:
        try:
            e = save_library.add(save.parent, save, name, loc.game, action="save copy")
        except Exception as e:
            raise _coded(e, source=str(save)) from e
        out.update(entry_id=e["id"], name=e["name"])
        return Written(f"saved a copy of {save.name} as '{e['name']}'")

    logged_write(f"save a copy of {save.name}", f"Saving a copy of {save.name}...", loc, body)
    return out


def import_files(files: list[Path], name: str | None, folder: Path, *, loc: Locations) -> dict:
    """Import save files into the Library of folder: one under name, or each under its own default name.
    {"imported": [{"file", "entry_id", "name"}], "failed": [{"file", "code"}]}. The files are only read. One that
    fails is listed and the rest go on; none at all is not_imported (details: failed)."""
    imported: list[dict] = []
    failed: list[dict] = []

    def body(loc: Locations) -> Written:
        for src in files:
            try:
                given = name if name is not None and len(files) == 1 else None
                got = save_library.add(
                    folder, src, given or save_library.default_name(src, loc.game), loc.game, action="import"
                )
                imported.append({"file": str(src), "entry_id": got["id"], "name": got["name"]})
            except Exception as e:
                run_logging.log(f"error: {src.name}: {e}")
                failed.append({"file": str(src), "code": failure_code(e)})
        if not imported:
            raise OperationError("not_imported", "None of these files could be imported.", {"failed": failed})
        return Written(f"imported {len(imported)} file(s), {len(failed)} not imported")

    if len(files) == 1:
        one = files[0].name
        logged_write(f"import {one} into the Library", f"Importing {one}...", loc, body)
    else:
        logged_write("import several files into the Library", f"Importing {len(files)} files...", loc, body)
    return {"imported": imported, "failed": failed}


def plan_character_copy(source: Path, src_slot: int, target: Path, dst_slot: int) -> dict:
    """What copying one character would do. Reads both saves; raises when it cannot be done."""
    return save_transfer.plan_character_copy(Path(source), src_slot, Path(target), dst_slot)


def copy_character(source: Path, src_slot: int, target: Path, dst_slot: int, *, loc: Locations) -> Written:
    src, dst = Path(source), Path(target)

    def body(loc: Locations) -> Written:
        saves_service.assert_writable(dst, loc=loc)
        out = save_transfer.copy_character(src, src_slot, dst, dst_slot)
        who = (out["character"] or {}).get("name", "?")
        return Written(
            f"{who} is in slot {dst_slot} of {dst.name}",
            {"character": who, "slot": dst_slot, "file": dst.name},
            dst,
            out["backup"],
        )

    return logged_write(
        f"copy slot {src_slot} of {src.name} into slot {dst_slot} of {dst.name}",
        f"Copying a character into {dst.name}...",
        loc,
        body,
    )


def _replace(target: Path, label: str, loc: Locations, run: Callable[[], dict]) -> Written:
    def body(loc: Locations) -> Written:
        saves_service.assert_writable(target, loc=loc)
        out = run()
        return Written(
            f"{target.name} now holds {label}", {"file": target.name, "source": label}, target, out["backup"]
        )

    return logged_write(f"replace {target.name} with {label}", f"Replacing {target.name}...", loc, body)


def replace_with_file(source: Path, target: Path, *, loc: Locations) -> Written:
    """Put a save file over a live save. The live one goes into the Library and a backup is taken first."""
    src, tgt = Path(source), Path(target)
    return _replace(tgt, src.name, loc, lambda: save_transfer.copy_file(src, tgt, loc.game))


def replace_with_copy(folder: Path, entry_id: str, target: Path, label: str, *, loc: Locations) -> Written:
    """Put a Library copy over a live save (same safeguards)."""
    tgt = Path(target)
    return _replace(tgt, label, loc, lambda: save_library.swap_in(Path(folder), entry_id, tgt, None, loc.game))


def restore_from_backup(backup: Path, target: Path, *, loc: Locations) -> Written:
    bak, tgt = Path(backup), Path(target)

    def body(loc: Locations) -> Written:
        safety = saves_service.restore_backup(bak, tgt, loc=loc)
        return Written(f"{tgt.name} is back as it was in the backup", {"file": tgt.name}, tgt, safety)

    return logged_write(f"restore backup {bak.name}", f"Restoring {tgt.name}...", loc, body)


def repair_calls(keys: Sequence[Sequence[Any]]) -> dict:
    """The ticked Check & repair boxes as the calls the writers take: {loading: {slot: [issue]}, vanilla: {slot:
    {items, orphans}}, checksums, regulation}."""
    loading: dict[int, list] = {}
    vanilla: dict[int, dict] = {}
    out = {"loading": loading, "vanilla": vanilla, "checksums": False, "regulation": False}
    for k in keys:
        if k[0] == "loading":
            loading.setdefault(k[1], []).append(k[2])
        elif k[0] == "item":
            vanilla.setdefault(k[1], {"items": set(), "orphans": False})["items"].add(k[2])
        elif k[0] == "orphans":
            vanilla.setdefault(k[1], {"items": set(), "orphans": False})["orphans"] = True
        elif k[0] == "checksum":
            out["checksums"] = True
        elif k[0] == "regulation":
            out["regulation"] = True
    return out


def apply_repairs(path: Path, calls: dict, *, loc: Locations) -> Path | None:
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


def repair(path: Path, calls: dict, count: int, *, loc: Locations) -> Written:
    save = Path(path)

    def body(loc: Locations) -> Written:
        return Written(f"repaired {save.name}", {"file": save.name}, save, apply_repairs(save, calls, loc=loc))

    return logged_write(f"repair {count} item(s) in {save.name}", f"Repairing {save.name}...", loc, body)


def post_session_repair(*, loc: Locations) -> Written:
    def body(loc: Locations) -> Written:
        save_repair.repair_all(loc)
        return Written("post-session repair finished")

    return logged_write("post-session repair", "Repairing saves...", loc, body)


def undo_change(save: Path, backup: Path, *, loc: Locations) -> dict:
    """The toast's Undo: put the backup taken before a save write back. Returns {"file"}."""
    progress = f"Undoing the change to {Path(save).name}..."
    # no job id: nothing in the jobs index to mark undone, so no activity log is needed
    activity_service.run_undo(restore_record(save, backup), "", Path(save).name, loc, progress, None)
    return {"file": Path(save).name}


def stamp_of(path: Path) -> tuple[int, int] | None:
    """A cheap read of a file for a write's staleness: (mtime_ns, size), None when it cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


@dataclass(frozen=True)
class CopyCheck:
    """What copying a character would do, and the stamp of both files as they were read (what the client confirms)."""

    plan: dict
    source: Path
    target: Path
    same_file: bool
    stamp: tuple


@dataclass(frozen=True)
class ReplaceCheck:
    """What Replace / Restore shows before it writes. from_library: the source is a Library copy (a Restore)."""

    source: Path
    target: Path
    label: str
    from_library: bool
    changed_outside: bool
    rows: list[dict]
    signed: bool
    holders: int
    stamp: tuple


@dataclass(frozen=True)
class RestoreCheck:
    backup: dict
    target: Path
    stamp: tuple


@dataclass(frozen=True)
class RepairCheck:
    info: dict
    keys: list[tuple]
    stamp: tuple


class SavesService:
    """The Saves page for one engine: jobs is its JobManager, locations the current game's Locations (None: no game
    selected). The reads, the upkeep of Bayle's own copies and backups, and the jobs that only read a live save
    (Back up, Save a copy, Import). Returns data and OperationError codes, never wording: the Qt page words them.
    The writes to live saves are a check (the facts the client words, and the stamp of the files read) and a start
    (refused as stale when a file's stamp changed since): each a writing job that backs up first and returns the
    Undo record with its facts.

    The upkeep is not gated on the game or a running job (it never touches a live save; the Library's and the
    backups' own locks keep it apart from a job writing them). It acts only on what the page lists: a Library of one
    of the game's save folders, a backup list_backups returns (anything else is not_found), so a client can never
    point it at another file. The two removals are a check and a start: the start is refused as stale when what the
    client confirmed changed since."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations

    def _loc(self) -> Locations:
        try:
            loc = self._locations()
        except OperationError:
            loc = None
        if loc is None:
            raise OperationError("no_game", "No game is selected.")
        return loc

    def page(self) -> SavesFacts:
        return read_facts(self._loc())

    def save_info(self, path: str | Path) -> dict:
        """One save's facts (the character sheet is made from them by the client)."""
        info = saves_service.save_info(Path(path), loc=self._loc())
        return {**info, "path": str(info["path"])}

    def health_report(self, path: str | Path) -> str:
        """A copyable diagnostic report of one save."""
        return saves_service.health_report(Path(path), loc=self._loc())

    def copy_entry(self, folder: str | Path, entry_id: str) -> dict:
        """One Library copy: {name, path, changed_outside}. Raises copy_unusable."""
        e = library_entry(Path(folder), entry_id)
        return {"name": e["name"], "path": str(e["path"]), "changed_outside": e["changed_outside"]}

    def default_name(self, path: str | Path) -> str:
        return library_default_name(Path(path), self._loc())

    def folder(self, which: str) -> Path | None:
        """The Saves, Backups or Library folder to show (the last two are created when missing); None: no save yet."""
        return open_folder(which, loc=self._loc())

    # ---- the upkeep of copies and backups
    def _folder(self, folder: str | Path) -> Path:
        """folder, when it is one of the game's save folders (each has its Library). Raises not_found."""
        want = os.path.normcase(str(Path(folder)))
        for d in {p.parent for p in self._loc().save_files()}:
            if os.path.normcase(str(d)) == want:
                return d
        raise OperationError("not_found", "That save folder is not listed.", {"folder": str(folder)})

    def _backup(self, backup: str | Path) -> dict:
        """backup's row of list_backups. Raises not_found when it is not listed (gone, or not a backup)."""
        want = os.path.normcase(str(Path(backup)))
        for b in saves_service.list_backups(loc=self._loc()):
            if os.path.normcase(str(b["path"])) == want:
                return b
        raise OperationError("not_found", "That backup is no longer listed.", {"backup": str(backup)})

    def _entry(self, folder: Path, entry_id: str) -> dict:
        entry = next((e for e in save_library.load(folder).get("entries", []) if e["id"] == entry_id), None)
        if entry is None:
            raise OperationError("not_found", "That copy is no longer listed.", {"entry_id": entry_id})
        return entry

    def adopt_legacy(self) -> list[str]:
        """Take in the backup folders older tools left beside the saves; returns the save folders looked in."""
        return adopt_legacy_folders(self._loc())

    def keep_backup(self, backup: str | Path, keep: bool = True) -> None:
        """Keep a backup whatever its age, or let it age out again. Raises not_found, failed."""
        b = self._backup(backup)
        try:
            saves_service.keep_backup(b["path"], keep)
        except OSError as e:
            raise OperationError("failed", str(e)) from e

    def label_backup(self, backup: str | Path, name: str) -> str:
        """Name a backup (empty: shown by its time again). Returns the name it got. Raises not_found, failed."""
        b = self._backup(backup)
        try:
            return saves_service.label_backup(b["path"], name)
        except OSError as e:
            raise OperationError("failed", str(e)) from e

    def keep_as(self, backup: str | Path, name: str) -> str:
        """Copy a backup into the Library under name (the backup stays and ages out as usual). Returns the name it got.
        Raises not_found, failed."""
        b = self._backup(backup)
        try:
            return saves_service.keep_backup_as_copy(b["path"], name, loc=self._loc())["name"]
        except Exception as e:
            raise OperationError("failed", str(e)) from e

    def rename_copy(self, folder: str | Path, entry_id: str, name: str) -> str:
        """Rename a Library copy. Returns the name it got. Raises not_found, failed (a name that can't be used)."""
        d = self._folder(folder)
        self._entry(d, entry_id)
        try:
            return save_library.rename(d, entry_id, name)["name"]
        except Exception as e:
            raise OperationError("failed", str(e)) from e

    def check_remove_copy(self, folder: str | Path, entry_id: str) -> str:
        """The name of the copy a removal would take out (what the client confirms). Raises not_found."""
        return self._entry(self._folder(folder), entry_id)["name"]

    def remove_copy(self, folder: str | Path, entry_id: str, expect: str) -> None:
        """Take a copy out of the Library: its file moves to the Library's removed folder with a note (a removal cut
        short is finished by finish_stranded). expect: the name the client confirmed. Raises not_found, stale, failed."""
        d = self._folder(folder)
        if self._entry(d, entry_id)["name"] != expect:
            raise OperationError("stale", "That copy changed since you were asked. Ask again.")
        try:
            save_library.remove(d, entry_id)
        except Exception as e:
            raise OperationError("failed", str(e)) from e

    def finish_stranded(self, folder: str | Path, entry_id: str, restore: bool) -> str:
        """Finish a removal that was cut short: put the copy back (restore) or let it go. Returns "" or, when only the
        Library's history has to wait, why (a diagnostic naming where the record is kept). Raises not_found, failed."""
        d = self._folder(folder)
        self._entry(d, entry_id)
        try:
            if restore:
                return save_library.restore_removed(d, entry_id) or ""
            save_library.finish_removal(d, entry_id)
        except Exception as e:
            raise OperationError("failed", str(e)) from e
        return ""

    # ---- copying in and backing up: each a job; its result is the dict the module function above returns
    def _live(self, path: str | Path) -> Path:
        """path, when it is one of the game's live saves (what the page lists). Raises not_found."""
        want = os.path.normcase(str(Path(path)))
        for p in live_saves(self._loc()):
            if os.path.normcase(str(p)) == want:
                return p
        raise OperationError("not_found", "That save is not listed.", {"path": str(path)})

    def back_up(self, paths: Sequence[str | Path] = (), *, everything: bool = False, title: str = "") -> str:
        """Back up live saves now (everything: every live save of the game) as a writing job; returns its id. Only
        the page's live saves: anything else is not_found. Refused while the game runs (busy, reason game_running)
        or another write runs (busy). Raises invalid_params, not_found, no_saves, busy."""
        loc = self._loc()
        if everything:
            saves = live_saves(loc)
            if not saves:
                raise OperationError("no_saves", "There is no save to back up.")
        elif paths:
            saves = [self._live(p) for p in paths]
        else:
            raise OperationError("invalid_params", "Say which saves to back up.")
        return self._jobs.start(lambda _ctx: back_up(saves, loc=loc), title=title or "Backing up saves...", quiet=True)

    def save_copy(self, path: str | Path, name: str, title: str = "") -> str:
        """Add a copy of a live save to the Library as a job; returns its id. Allowed while the game runs (it only
        reads the save), never beside another write. Raises not_found, invalid_name, busy."""
        save = self._live(path)
        try:
            name = save_library.clean_name(name)
        except save_library.LibraryError as e:
            raise OperationError("invalid_name", str(e)) from e
        loc = self._loc()
        return self._jobs.start(
            lambda _ctx: save_copy(save, name, loc=loc),
            title=title or "Saving a copy...",
            while_game_runs=True,
            quiet=True,
        )

    def import_files(self, files: Sequence[str | Path], name: str | None = None, title: str = "") -> str:
        """Import save files the player picked (anywhere on disk; they are only read) into the Library of the
        game's first save folder, as a job; returns its id. name: for a single file. Allowed while the game runs,
        never beside another write. Raises invalid_params, invalid_name, not_found (a single file that isn't there),
        no_saves, busy."""
        srcs = [Path(f) for f in files]
        if not srcs:
            raise OperationError("invalid_params", "Say which files to import.")
        if name is not None:
            if len(srcs) != 1:
                raise OperationError("invalid_params", "A name is for a single file.")
            try:
                name = save_library.clean_name(name)
            except save_library.LibraryError as e:
                raise OperationError("invalid_name", str(e)) from e
        if len(srcs) == 1 and not srcs[0].is_file():
            raise OperationError("not_found", "That file is not there.", {"path": str(srcs[0])})
        loc = self._loc()
        folder = library_folder(loc)
        return self._jobs.start(
            lambda _ctx: import_files(srcs, name, folder, loc=loc),
            title=title or "Importing...",
            while_game_runs=True,
            quiet=True,
        )

    def check_delete_backup(self, backup: str | Path) -> BackupFacts:
        """The backup a removal would delete (what the client confirms: its stamp). Raises not_found."""
        b = self._backup(backup)
        return BackupFacts(b["path"], b["save_name"], b["when"], b["action"], b["size"], b["mtime"])

    def delete_backup(self, backup: str | Path, expect: tuple[int, float]) -> None:
        """Delete a backup and its notes, for good (there is no removed folder for backups). expect: the stamp the
        client confirmed. Raises not_found, stale (it was replaced or changed since), failed."""
        got = self.check_delete_backup(backup)
        if got.stamp != (int(expect[0]), float(expect[1])):
            raise OperationError("stale", "That backup changed since you were asked. Ask again.")
        try:
            saves_service.delete_backup(got.path)
        except Exception as e:
            raise OperationError("failed", str(e)) from e

    # ---- the writes to live saves: each a check (facts and stamp) and a start (refused as stale), then a writing job
    def _source(self, path: str | Path) -> Path:
        """path, when it is a live save, a listed backup or the file of a listed Library copy (a character may come
        from any of them; it is only read). Raises not_found."""
        try:
            return self._live(path)
        except OperationError:
            pass
        try:
            return Path(self._backup(path)["path"])
        except OperationError:
            pass
        want = os.path.normcase(str(Path(path)))
        for d in {p.parent for p in self._loc().save_files()}:
            try:
                entries = save_library.load(d).get("entries", [])
                files = [save_library.entry_path(d, e) for e in entries]
            except Exception:
                continue
            for f in files:
                if os.path.normcase(str(f)) == want:
                    return f
        raise OperationError("not_found", "That save is not listed.", {"path": str(path)})

    @staticmethod
    def _picked(path: str | Path) -> Path:
        """A save file the player picked (anywhere on disk; it is only read), when it is a file a save could be.
        Raises not_found, not_a_save (far too big, as Import says)."""
        src = Path(path)
        if not src.is_file():
            raise OperationError("not_found", "That file is not there.", {"path": str(src)})
        if src.stat().st_size > save_library.MAX_SAVE_BYTES:
            raise OperationError("not_a_save", f"{src.name} is far too big to be a save.", {"path": str(src)})
        return src

    @staticmethod
    def _stale(files: Sequence[Path], expect: Sequence[Sequence[int] | None]) -> None:
        """Raises stale unless every file still has the stamp the client confirmed (None: it was not there)."""
        now = [stamp_of(f) for f in files]
        then = [None if e is None else (int(e[0]), int(e[1])) for e in expect]
        if now != then:
            raise OperationError("stale", "A file changed since you were asked. Ask again.")

    def _replace_check(
        self, source: Path, target: Path, label: str, *, from_library: bool, changed_outside: bool = False
    ) -> ReplaceCheck:
        try:
            facts = replace_facts(source, target, loc=self._loc())
        except Exception as e:
            raise OperationError("not_possible", str(e)) from e
        return ReplaceCheck(
            source, target, label, from_library, changed_outside, **facts, stamp=(stamp_of(source), stamp_of(target))
        )

    def _write(self, work: Callable[[], Written], title: str) -> str:
        return self._jobs.start(lambda _ctx: work().result(), title=title, quiet=True)

    def check_copy_character(self, source: str | Path, src_slot: int, target: str | Path, dst_slot: int) -> CopyCheck:
        """What copying one character would do (it reads both saves). source: a live save or a Library copy's file;
        target: a live save. Raises not_found, not_possible (the reason is the message)."""
        src, dst = self._source(source), self._live(target)
        try:
            plan = plan_character_copy(src, src_slot, dst, dst_slot)
        except Exception as e:
            raise OperationError("not_possible", str(e)) from e
        return CopyCheck(plan, src, dst, src.resolve() == dst.resolve(), (stamp_of(src), stamp_of(dst)))

    def copy_character(
        self,
        source: str | Path,
        src_slot: int,
        target: str | Path,
        dst_slot: int,
        expect: Sequence[Sequence[int] | None],
        title: str = "",
    ) -> str:
        """Copy a character into a live slot as a writing job; returns its id. expect: the stamp check_copy_character
        gave. Raises not_found, stale, busy (the game runs, or another write)."""
        src, dst = self._source(source), self._live(target)
        self._stale([src, dst], expect)
        loc = self._loc()
        return self._write(
            lambda: copy_character(src, src_slot, dst, dst_slot, loc=loc), title or "Copying a character..."
        )

    def check_replace_from_library(self, folder: str | Path, entry_id: str, target: str | Path) -> ReplaceCheck:
        """What putting a Library copy over a live save would do. Raises not_found, copy_unusable, not_possible."""
        d, tgt = self._folder(folder), self._live(target)
        self._entry(d, entry_id)
        e = library_entry(d, entry_id)
        return self._replace_check(e["path"], tgt, e["name"], from_library=True, changed_outside=e["changed_outside"])

    def replace_from_library(
        self,
        folder: str | Path,
        entry_id: str,
        target: str | Path,
        expect: Sequence[Sequence[int] | None],
        title: str = "",
    ) -> str:
        """Put a Library copy over a live save as a writing job (the live one goes into the Library, a backup is
        taken first); returns its id. Raises not_found, copy_unusable, stale, busy."""
        d, tgt = self._folder(folder), self._live(target)
        self._entry(d, entry_id)
        e = library_entry(d, entry_id)
        self._stale([e["path"], tgt], expect)
        loc = self._loc()
        return self._write(
            lambda: replace_with_copy(d, entry_id, tgt, e["name"], loc=loc), title or "Replacing a save..."
        )

    def check_replace_from_file(self, source: str | Path, target: str | Path) -> ReplaceCheck:
        """What putting a picked save file over a live save would do. Raises not_found, not_a_save, not_possible."""
        src, tgt = self._picked(source), self._live(target)
        return self._replace_check(src, tgt, src.name, from_library=False)

    def replace_from_file(
        self, source: str | Path, target: str | Path, expect: Sequence[Sequence[int] | None], title: str = ""
    ) -> str:
        """Put a picked save file over a live save as a writing job; returns its id. Raises not_found, not_a_save,
        stale, busy."""
        src, tgt = self._picked(source), self._live(target)
        self._stale([src, tgt], expect)
        loc = self._loc()
        return self._write(lambda: replace_with_file(src, tgt, loc=loc), title or "Replacing a save...")

    def check_restore_backup(self, backup: str | Path, target: str | Path) -> RestoreCheck:
        """The backup (its row of list_backups) a restore would put back. Raises not_found."""
        row, tgt = self._backup(backup), self._live(target)
        return RestoreCheck(row, tgt, (stamp_of(row["path"]), stamp_of(tgt)))

    def restore_backup(
        self, backup: str | Path, target: str | Path, expect: Sequence[Sequence[int] | None], title: str = ""
    ) -> str:
        """Put a listed backup back over a live save as a writing job (the save as it is now is backed up first);
        returns its id. Raises not_found, stale, busy."""
        row, tgt = self._backup(backup), self._live(target)
        self._stale([row["path"], tgt], expect)
        loc = self._loc()
        return self._write(lambda: restore_from_backup(row["path"], tgt, loc=loc), title or "Restoring a save...")

    @staticmethod
    def _keys(keys: Sequence[Sequence[Any]]) -> list[tuple]:
        if not keys:
            raise OperationError("invalid_params", "Tick at least one item to repair.")
        return [tuple(k) for k in keys]

    def check_repair(self, path: str | Path, keys: Sequence[Sequence[Any]]) -> RepairCheck:
        """The save's facts for the repairs ticked (keys as the Check & repair page names them). Raises invalid_params,
        not_found."""
        save, ticked = self._live(path), self._keys(keys)
        return RepairCheck(saves_service.save_info(save, loc=self._loc()), ticked, (stamp_of(save),))

    def repair(
        self, path: str | Path, keys: Sequence[Sequence[Any]], expect: Sequence[Sequence[int] | None], title: str = ""
    ) -> str:
        """Repair what keys name as a writing job (a backup is taken first); returns its id. Raises invalid_params,
        not_found, stale, busy."""
        save, ticked = self._live(path), self._keys(keys)
        self._stale([save], expect)
        loc, calls = self._loc(), repair_calls(ticked)
        return self._write(lambda: repair(save, calls, len(ticked), loc=loc), title or "Repairing a save...")

    def post_session_repair(self, title: str = "") -> str:
        """Repair the saves a session may have left unsettled, as a writing job; returns its id. Raises busy."""
        loc = self._loc()
        return self._write(lambda: post_session_repair(loc=loc), title or "Repairing saves...")

    def undo_change(self, save: str | Path, backup: str | Path, title: str = "") -> str:
        """Put the backup a write took back over its live save, as a writing job; returns its id. Only a live save and
        a listed backup. Raises not_found, busy."""
        sv, bak = self._live(save), self._backup(backup)["path"]
        loc = self._loc()
        return self._jobs.start(
            lambda _ctx: undo_change(sv, bak, loc=loc), title=title or "Undoing a change...", quiet=True
        )
