"""What the Saves page reads and the writes it runs, without Qt: the page's facts (live saves, Library, Backups), the
Library's upkeep, and each write as one logged job that backs up first and returns how to take it back. The session's
saves operations call this; nothing here knows a window.

A write is logged_write(): it names the job (start_log), runs the body, records the undo (a save-restore record built
by restore_record, the one place that builds it) and returns Written, which carries that record."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bayle.errors import Cancelled, OperationError
from bayle.game import catalog as games
from bayle.game.locate import Locations
from bayle.platform import filelock
from bayle.platform import logging as run_logging
from bayle.platform.files import Unsettled
from bayle.platform.text import tr
from bayle.saves import backups as save_backups
from bayle.saves import library as save_library
from bayle.saves import repair as save_repair
from bayle.saves import transfer as save_transfer
from bayle.services import activity as activity_service
from bayle.services import saves as saves_service
from bayle.work.jobs import JobManager
from bayle.work.runner import run_job_result, run_logged


@dataclass(frozen=True)
class Written:
    """What a save write did: the words for the toast, and how to take it back (save and the backup taken first, and
    the undo record the jobs index holds for it)."""

    text: str
    save: Path | None = None
    backup: Path | None = None
    undo: dict | None = None


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
        with run_logged(f"launcher: {log_title}", loc.game.key):
            out = body(loc)
        if out.backup is not None and out.save is not None:
            run_logging.set_undo(restore_record(out.save, out.backup))
        run_logging.log(f"done: {out.text}")
        return out

    done = run_job_result(job, None, loc, progress)
    if done.state == "done":
        return replace(done.result, undo=done.undo)
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError(done.error.code if done.error else "failed", done.error.message if done.error else "Failed.")


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
        raise OperationError("no_saves", tr("Play once so the game creates its save folder."))
    return folders[0]


def library_entry(folder: Path, entry_id: str) -> dict:
    """One Library copy: {name, path, changed_outside}. Raises OperationError when the copy cannot be used."""
    try:
        entry = save_library.find(save_library.load(folder), entry_id)
        path = save_library.entry_path(folder, entry)
    except Exception as e:
        raise OperationError("copy_unusable", str(e)) from e
    if not path.is_file():
        raise OperationError("copy_unusable", tr("Its file is missing from the Library."))
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
        logged_write(f"back up {saves[0].name}", tr("Backing up {name}...").format(name=saves[0].name), loc, body)
    else:
        logged_write("back up now", tr("Backing up saves..."), loc, body)
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

    logged_write(f"save a copy of {save.name}", tr("Saving a copy of {name}...").format(name=save.name), loc, body)
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
        logged_write(f"import {one} into the Library", tr("Importing {name}...").format(name=one), loc, body)
    else:
        logged_write(
            "import several files into the Library", tr("Importing {n} files...").format(n=len(files)), loc, body
        )
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
            tr("{who} is in slot {n} of {file}").format(who=who, n=dst_slot, file=dst.name), dst, out["backup"]
        )

    return logged_write(
        f"copy slot {src_slot} of {src.name} into slot {dst_slot} of {dst.name}",
        tr("Copying a character into {name}...").format(name=dst.name),
        loc,
        body,
    )


def _replace(target: Path, label: str, loc: Locations, run: Callable[[], dict]) -> Written:
    def body(loc: Locations) -> Written:
        saves_service.assert_writable(target, loc=loc)
        out = run()
        return Written(
            tr("{target} now holds {source}").format(target=target.name, source=label), target, out["backup"]
        )

    return logged_write(
        f"replace {target.name} with {label}", tr("Replacing {name}...").format(name=target.name), loc, body
    )


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
        return Written(tr("{name} is back as it was in the backup").format(name=tgt.name), tgt, safety)

    return logged_write(f"restore backup {bak.name}", tr("Restoring {name}...").format(name=tgt.name), loc, body)


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
        return Written(tr("Repaired {name}").format(name=save.name), save, apply_repairs(save, calls, loc=loc))

    return logged_write(
        f"repair {count} item(s) in {save.name}", tr("Repairing {name}...").format(name=save.name), loc, body
    )


def post_session_repair(*, loc: Locations) -> Written:
    def body(loc: Locations) -> Written:
        save_repair.repair_all(loc)
        return Written(tr("Post-session repair finished"))

    return logged_write("post-session repair", tr("Repairing saves..."), loc, body)


def undo_change(save: Path, backup: Path, *, loc: Locations) -> str:
    """The toast's Undo: put the backup taken before a save write back. Returns what was done, in words."""
    progress = tr("Undoing the change to {name}...").format(name=Path(save).name)
    # no job id: nothing in the jobs index to mark undone, so no activity log is needed
    return activity_service.run_undo(restore_record(save, backup), "", Path(save).name, loc, progress, None)


class SavesService:
    """The Saves page for one engine: jobs is its JobManager, locations the current game's Locations (None: no game
    selected). The reads, the upkeep of Bayle's own copies and backups, and the jobs that only read a live save
    (Back up, Save a copy, Import). Returns data and OperationError codes, never wording: the Qt page words them.
    The writes to live saves still go through the session's operations.

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
        return self._jobs.start(lambda _ctx: back_up(saves, loc=loc), title=title or "Backing up saves...")

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
            lambda _ctx: save_copy(save, name, loc=loc), title=title or "Saving a copy...", while_game_runs=True
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
            lambda _ctx: import_files(srcs, name, folder, loc=loc), title=title or "Importing...", while_game_runs=True
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
