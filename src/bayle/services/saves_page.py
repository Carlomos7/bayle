"""What the Saves page reads and the writes it runs, without Qt: the page's facts (live saves, Library, Backups), the
Library's upkeep, and each write as one logged job that backs up first and returns how to take it back. The session's
saves operations call this; nothing here knows a window.

A write is logged_write(): it names the job (start_log), runs the body, records the undo (a save-restore record built
by restore_record, the one place that builds it) and returns Written, which carries that record."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bayle.errors import Cancelled, OperationError
from bayle.game import catalog as games
from bayle.game.locate import Locations
from bayle.platform import logging as run_logging
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


def library_name(folder: Path, entry_id: str) -> str | None:
    entry = next((e for e in save_library.load(folder).get("entries", []) if e["id"] == entry_id), None)
    return None if entry is None else entry["name"]


def rename_copy(folder: Path, entry_id: str, name: str) -> None:
    try:
        save_library.rename(folder, entry_id, name)
    except Exception as e:
        raise OperationError("failed", str(e)) from e


def remove_copy(folder: Path, entry_id: str) -> None:
    try:
        save_library.remove(folder, entry_id)
    except Exception as e:
        raise OperationError("failed", str(e)) from e


def finish_stranded(folder: Path, entry_id: str, restore: bool) -> str:
    """Finish a removal that was cut short (restore the copy, or let it go). Returns a warning to show, or ""."""
    try:
        if restore:
            return save_library.restore_removed(folder, entry_id) or ""
        save_library.finish_removal(folder, entry_id)
    except Exception as e:
        raise OperationError("failed", str(e)) from e
    return ""


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


# ----------------------------------------------------------------------------- the writes (one logged job each)
def back_up(paths: list[Path], *, everything: bool, loc: Locations) -> Written:
    """Back up the given saves (everything: every live save of this game)."""
    saves = live_saves(loc) if everything else [Path(p) for p in paths]
    first = saves[0] if saves else Path("")

    def body(loc: Locations) -> Written:
        made = [saves_service.back_up_now(p, loc=loc) for p in saves]
        if everything:
            return Written(tr("Backed up {n} save file(s).").format(n=len(made)))
        return Written(tr("Backed up {name} ({file})").format(name=first.name, file=made[0].name))

    if everything:
        return logged_write("back up now", tr("Backing up saves..."), loc, body)
    return logged_write(f"back up {first.name}", tr("Backing up {name}...").format(name=first.name), loc, body)


def save_copy(path: Path, name: str, *, loc: Locations) -> Written:
    """Add a copy of a live save to the Library. Only reads the live save."""
    save = Path(path)

    def body(loc: Locations) -> Written:
        e = save_library.add(save.parent, save, name, loc.game, action="save copy")
        return Written(tr("Saved a copy of {file} as '{name}'").format(file=save.name, name=e["name"]))

    return logged_write(
        f"save a copy of {save.name}", tr("Saving a copy of {name}...").format(name=save.name), loc, body
    )


def import_files(files: list[Path], name: str | None, *, loc: Locations) -> Written:
    """Import save files into the Library: one under `name`, or each under its own default name."""
    folder = library_folder(loc)
    if len(files) == 1 and name is not None:
        src = Path(files[0])

        def one(loc: Locations) -> Written:
            e = save_library.add(folder, src, name, loc.game, action="import")
            return Written(tr("Imported '{name}' into the Library").format(name=e["name"]))

        return logged_write(
            f"import {src.name} into the Library", tr("Importing {name}...").format(name=src.name), loc, one
        )

    def many(loc: Locations) -> Written:
        done, failed = [], []
        for src in map(Path, files):
            try:
                save_library.add(folder, src, save_library.default_name(src, loc.game), loc.game, action="import")
                done.append(src.name)
            except Exception as e:
                run_logging.log(f"error: {src.name}: {e}")
                failed.append(src.name)
        if not done:
            raise RuntimeError(tr("None of these files could be imported: {names}").format(names=", ".join(failed)))
        text = tr("Imported {n} files into the Library").format(n=len(done))
        if failed:
            text += tr(". Not imported: {names}").format(names=", ".join(failed))
        return Written(text)

    return logged_write(
        "import several files into the Library", tr("Importing {n} files...").format(n=len(files)), loc, many
    )


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
    """The Saves page's reads for one engine: jobs is its JobManager, locations the current game's Locations (None:
    no game selected). Returns data and OperationError codes, never wording: the Qt page words them. The writes still
    go through the session's operations."""

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
