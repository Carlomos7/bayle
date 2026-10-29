"""Saves over HTTP: the page (live saves, Library, Backups), the reads (health report, character sheet, one Library
copy), the Library's and Backups' upkeep, and every write to a live save, each handed straight to the engine's
SavesService (modules.saves.saves_page), with no wording. A write to a live save is a check (the facts a client words,
and the stamp of the files read) and a start (with what the client confirmed: refused as stale when a file changed
since) that returns a job id; the job's result holds the facts and the Undo record. The game gate and the other-write
gate are the job manager's. Errors are OperationError codes."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import JobStarted, NoParams, Params, Result
from bayle.modules.saves.saves_page import SavesFacts, SavesService

router = APIRouter(prefix="/saves", tags=["saves"])
Saves = Annotated[SavesService, Depends(service("saves"))]


class SavesSaid(Result):
    text: str


class SavesSheet(Result):
    data: dict[str, Any]  # modules.saves.service.save_info: the save's facts; the client makes the sheet of a slot


class CopyEntry(Result):
    name: str
    path: str
    changed_outside: bool


class SavesFolder(Result):
    path: str | None  # None when no save exists yet


class SavesWarned(Result):
    warning: str = ""


class Adopted(Result):
    folders: list[str]


class SavesPathParams(Params):
    path: str


class SavesBackUpParams(Params):
    paths: list[str] = []
    everything: bool = False  # every live save of the game; paths is then ignored


class SaveCopyParams(SavesPathParams):
    name: str


class SaveImportParams(Params):
    files: list[str]
    name: str | None = None  # a name for a single file; None: each is named by default


Stamp = list[tuple[int, int] | None]  # (mtime_ns, size) of each file a check read, None: it was not there


class CharacterRef(Params):
    source: str
    src_slot: int
    target: str
    dst_slot: int


class CharacterParams(CharacterRef):
    expect: Stamp  # the stamp check_copy_character gave and the client confirmed


class CopyRef(Params):
    folder: str
    entry_id: str


class ReplaceCopyRef(CopyRef):
    target: str


class ReplaceCopyParams(ReplaceCopyRef):
    expect: Stamp


class ReplaceFileRef(Params):
    source: str
    target: str


class ReplaceFileParams(ReplaceFileRef):
    expect: Stamp


class RestoreRef(Params):
    backup: str
    target: str


class RestoreBackupParams(RestoreRef):
    expect: Stamp


class BackupRef(Params):
    backup: str


class KeepAsParams(BackupRef):
    name: str


class KeepParams(BackupRef):
    keep: bool = True


class DeleteBackupParams(BackupRef):
    expect: tuple[int, float]  # the stamp (size, mtime) check_delete_backup gave and the client confirmed


class RemoveCopyParams(CopyRef):
    expect: str  # the name check_remove_copy gave and the client confirmed


class CopyCheck(Result):
    plan: dict[str, Any]  # modules.saves.saves_page.plan_character_copy: the character, what it replaces, the signing
    source: str
    target: str
    same_file: bool
    stamp: Stamp


class ReplaceCheck(Result):
    source: str
    target: str
    label: str
    from_library: bool
    changed_outside: bool
    rows: list[dict[str, Any]]
    signed: bool
    holders: int
    stamp: Stamp


class RestoreCheck(Result):
    backup: dict[str, Any]  # the backup's row of list_backups
    target: str
    stamp: Stamp


class RepairCheck(Result):
    info: dict[str, Any]  # modules.saves.service.save_info
    keys: list[list[str | int]]
    stamp: Stamp


class BackupFacts(Result):
    path: str
    save_name: str
    when: str
    action: str
    stamp: tuple[int, float]


class RenameCopyParams(CopyRef):
    name: str


class StrandedParams(CopyRef):
    restore: bool


class RepairRef(SavesPathParams):
    keys: list[list[str | int]]  # the ticked boxes as the presenter names them (("checksum", 2), ("item", 1, 500))


class RepairParams(RepairRef):
    expect: Stamp


class SheetParams(SavesPathParams):
    slot: int


class SavesFolderParams(Params):
    which: Literal["saves", "backups", "library"]


class UndoChangeParams(Params):
    save: str
    backup: str


# ----------------------------------------------------------------------------- helpers
def _facts(checked: Any) -> dict[str, Any]:
    """A check's fields for its Result model (paths as text)."""
    return {k: str(v) if isinstance(v, Path) else v for k, v in vars(checked).items()}


# ----------------------------------------------------------------------------- the page and its reads
@router.get("", name="saves")
def page(s: Saves, _q: Annotated[NoParams, Query()]) -> SavesFacts:
    return s.page()


@router.post("/adopt_legacy", name="saves_adopt_legacy")
def adopt_legacy(s: Saves) -> Adopted:
    """Take in backup folders older tools left beside the saves (also a start-up step; Refresh asks for it too)."""
    return Adopted(folders=s.adopt_legacy())


@router.post("/health_report", name="saves_health_report")
def health_report(s: Saves, p: SavesPathParams) -> SavesSaid:
    return SavesSaid(text=s.health_report(p.path))


@router.post("/sheet", name="saves_sheet")
def sheet(s: Saves, p: SheetParams) -> SavesSheet:
    """The save's facts; which slot to show is the client's (the Qt page words the sheet itself)."""
    return SavesSheet(data=s.save_info(p.path))


@router.post("/copy_entry", name="saves_copy_entry")
def copy_entry(s: Saves, p: CopyRef) -> CopyEntry:
    """One Library copy, for a client to ask about it first (it was changed outside the launcher)."""
    return CopyEntry(**s.copy_entry(p.folder, p.entry_id))


@router.post("/folder", name="saves_folder")
def folder(s: Saves, p: SavesFolderParams) -> SavesFolder:
    """The Saves, Backups or Library folder to show (the last two are created if they do not exist yet)."""
    got = s.folder(p.which)
    return SavesFolder(path=None if got is None else str(got))


@router.post("/default_name", name="saves_default_name")
def default_name(s: Saves, p: SavesPathParams) -> SavesSaid:
    return SavesSaid(text=s.default_name(p.path))


# ----------------------------------------------------------------------------- the upkeep of copies and backups
@router.post("/keep_as", name="saves_keep_as")
def keep_as(s: Saves, p: KeepAsParams) -> SavesSaid:
    """Copy a backup into the Library under a name (the backup stays and ages out as usual); text is the name."""
    return SavesSaid(text=s.keep_as(p.backup, p.name))


@router.post("/keep_backup", name="saves_keep_backup")
def keep_backup(s: Saves, p: KeepParams) -> SavesSaid:
    """Keep a backup whatever its age, or let it age out again."""
    s.keep_backup(p.backup, p.keep)
    return SavesSaid(text="")


@router.post("/label_backup", name="saves_label_backup")
def label_backup(s: Saves, p: KeepAsParams) -> SavesSaid:
    """Name a backup (an empty name shows it by its time again); text is the name it got."""
    return SavesSaid(text=s.label_backup(p.backup, p.name))


@router.post("/rename_copy", name="saves_rename_copy")
def rename_copy(s: Saves, p: RenameCopyParams) -> SavesSaid:
    return SavesSaid(text=s.rename_copy(p.folder, p.entry_id, p.name))


@router.post("/finish_stranded", name="saves_finish_stranded")
def finish_stranded(s: Saves, p: StrandedParams) -> SavesWarned:
    return SavesWarned(warning=s.finish_stranded(p.folder, p.entry_id, p.restore))


@router.post("/check_delete_backup", name="saves_check_delete_backup")
def check_delete_backup(s: Saves, p: BackupRef) -> BackupFacts:
    """The backup a removal would delete; the client confirms its stamp."""
    got = s.check_delete_backup(p.backup)
    return BackupFacts(path=str(got.path), save_name=got.save_name, when=got.when, action=got.action, stamp=got.stamp)


@router.post("/delete_backup", name="saves_delete_backup")
def delete_backup(s: Saves, p: DeleteBackupParams) -> SavesSaid:
    s.delete_backup(p.backup, p.expect)
    return SavesSaid(text="")


@router.post("/check_remove_copy", name="saves_check_remove_copy")
def check_remove_copy(s: Saves, p: CopyRef) -> SavesSaid:
    """The name of the copy a removal would take out; the client confirms it."""
    return SavesSaid(text=s.check_remove_copy(p.folder, p.entry_id))


@router.post("/remove_copy", name="saves_remove_copy")
def remove_copy(s: Saves, p: RemoveCopyParams) -> SavesSaid:
    s.remove_copy(p.folder, p.entry_id, p.expect)
    return SavesSaid(text="")


# ----------------------------------------------------------------------------- jobs that write or add copies
@router.post("/back_up", name="saves_back_up")
def back_up(s: Saves, p: SavesBackUpParams) -> JobStarted:
    """A job; its result is {"saves", "backups"}."""
    return JobStarted(job_id=s.back_up(p.paths, everything=p.everything))


@router.post("/post_session_repair", name="saves_post_session_repair")
def post_session_repair(s: Saves) -> JobStarted:
    return JobStarted(job_id=s.post_session_repair())


@router.post("/save_copy", name="saves_save_copy")
def save_copy(s: Saves, p: SaveCopyParams) -> JobStarted:
    """A job; its result is {"source", "entry_id", "name"}."""
    return JobStarted(job_id=s.save_copy(p.path, p.name))


@router.post("/import_files", name="saves_import_files")
def import_files(s: Saves, p: SaveImportParams) -> JobStarted:
    """A job; its result is {"imported": [{"file", "entry_id", "name"}], "failed": [{"file", "code"}]}."""
    return JobStarted(job_id=s.import_files(p.files, p.name))


@router.post("/undo_change", name="saves_undo_change")
def undo_change(s: Saves, p: UndoChangeParams) -> JobStarted:
    """The toast's Undo: put the backup taken before a write back over the save. The job's result is {"file"}."""
    return JobStarted(job_id=s.undo_change(p.save, p.backup))


# ----------------------------------------------------------------------------- writes to live saves: check, then start
# Each start's job result is the write's facts plus "save", "backup" and "undo" (the record Activity's Undo uses).
@router.post("/check_copy_character", name="saves_check_copy_character")
def check_copy_character(s: Saves, p: CharacterRef) -> CopyCheck:
    return CopyCheck(**_facts(s.check_copy_character(p.source, p.src_slot, p.target, p.dst_slot)))


@router.post("/copy_character", name="saves_copy_character")
def copy_character(s: Saves, p: CharacterParams) -> JobStarted:
    """A job; its result is {"character", "slot", "file", "save", "backup", "undo"}."""
    return JobStarted(job_id=s.copy_character(p.source, p.src_slot, p.target, p.dst_slot, p.expect))


@router.post("/check_replace_from_library", name="saves_check_replace_from_library")
def check_replace_from_library(s: Saves, p: ReplaceCopyRef) -> ReplaceCheck:
    return ReplaceCheck(**_facts(s.check_replace_from_library(p.folder, p.entry_id, p.target)))


@router.post("/replace_from_library", name="saves_replace_from_library")
def replace_from_library(s: Saves, p: ReplaceCopyParams) -> JobStarted:
    """A job; its result is {"file", "source", "save", "backup", "undo"}."""
    return JobStarted(job_id=s.replace_from_library(p.folder, p.entry_id, p.target, p.expect))


@router.post("/check_replace_from_file", name="saves_check_replace_from_file")
def check_replace_from_file(s: Saves, p: ReplaceFileRef) -> ReplaceCheck:
    return ReplaceCheck(**_facts(s.check_replace_from_file(p.source, p.target)))


@router.post("/replace_from_file", name="saves_replace_from_file")
def replace_from_file(s: Saves, p: ReplaceFileParams) -> JobStarted:
    """A job; its result is {"file", "source", "save", "backup", "undo"}."""
    return JobStarted(job_id=s.replace_from_file(p.source, p.target, p.expect))


@router.post("/check_restore_backup", name="saves_check_restore_backup")
def check_restore_backup(s: Saves, p: RestoreRef) -> RestoreCheck:
    return RestoreCheck(**_facts(s.check_restore_backup(p.backup, p.target)))


@router.post("/restore_backup", name="saves_restore_backup")
def restore_backup(s: Saves, p: RestoreBackupParams) -> JobStarted:
    """A job; its result is {"file", "save", "backup", "undo"}."""
    return JobStarted(job_id=s.restore_backup(p.backup, p.target, p.expect))


@router.post("/check_repair", name="saves_check_repair")
def check_repair(s: Saves, p: RepairRef) -> RepairCheck:
    return RepairCheck(**_facts(s.check_repair(p.path, p.keys)))


@router.post("/repair", name="saves_repair")
def repair(s: Saves, p: RepairParams) -> JobStarted:
    """A job; its result is {"file", "save", "backup", "undo"}."""
    return JobStarted(job_id=s.repair(p.path, p.keys, p.expect))
