"""The Saves page's operations: its snapshot (live saves, Library, Backups), the reads (health report, character
sheet, one Library copy), the Library's and Backups' upkeep, and every write to a live save.

Each is handed straight to the session's SavesService (services.saves_page), with no wording. A write to a live save
is a check (the facts a client words, and the stamp of the files read) and a start (with what the client confirmed:
refused as stale when a file changed since) that returns a job id; the job's result holds the facts and the Undo
record. The game gate and the other-write gate are the job manager's. Errors are OperationError codes. Temporary, as
for Settings: the Qt page calls the service itself."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from bayle.errors import OperationError
from bayle.services.saves_page import SavesService
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry


# ----------------------------------------------------------------------------- models
@dataclass(frozen=True)
class SavesState:
    """The page's facts. The Qt page's presenter words them; which save the profile plays on is the host's."""

    infos: list[dict[str, Any]]
    libraries: dict[str, dict[str, Any]]
    backups: list[dict[str, Any]]


class Said(Result):
    text: str


class SavesJob(Result):
    job_id: str


class Sheet(Result):
    data: dict[str, Any]  # services.saves.save_info: the save's facts; the client makes the sheet of a slot


class CopyEntry(Result):
    name: str
    path: str
    changed_outside: bool


class Folder(Result):
    path: str | None  # None when no save exists yet


class Warned(Result):
    warning: str = ""


class Adopted(Result):
    folders: list[str]


class PathParams(Params):
    path: str


class BackUpParams(Params):
    paths: list[str] = []
    everything: bool = False  # every live save of the game; paths is then ignored


class SaveCopyParams(PathParams):
    name: str


class ImportParams(Params):
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


class RestoreParams(RestoreRef):
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
    plan: dict[str, Any]  # services.saves_page.plan_character_copy: the character, what it replaces, the signing
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
    info: dict[str, Any]  # services.saves.save_info
    keys: list[list[str | int]]
    stamp: Stamp


class BackupFacts(Result):
    path: str
    save_name: str
    when: str
    action: str
    stamp: tuple[int, float]


class RenameParams(CopyRef):
    name: str


class StrandedParams(CopyRef):
    restore: bool


class RepairRef(PathParams):
    keys: list[list[str | int]]  # the ticked boxes as the presenter names them (("checksum", 2), ("item", 1, 500))


class RepairParams(RepairRef):
    expect: Stamp


class SheetParams(PathParams):
    slot: int


class FolderParams(Params):
    which: Literal["saves", "backups", "library"]


class UndoParams(Params):
    save: str
    backup: str


# ----------------------------------------------------------------------------- helpers
def _facts(checked: Any) -> dict[str, Any]:
    """A check's fields for its Result model (paths as text)."""
    return {k: str(v) if isinstance(v, Path) else v for k, v in vars(checked).items()}


# ----------------------------------------------------------------------------- the page and its reads
def _none() -> SavesService:
    raise OperationError("no_saves_service", "This session has no Saves page.")


def _saves(session: Session) -> SavesService:
    return session.service("saves", _none)


@registry.page("saves", view=SavesState)
def snapshot(session: Session) -> SavesState:
    facts = _saves(session).page()
    return SavesState(facts.infos, facts.libraries, facts.backups)


@operation("saves.adopt_legacy", result=Adopted, kind="command", writes=True)
def adopt_legacy(call: Call, p: NoParams) -> Adopted:
    """Take in backup folders older tools left beside the saves (also a start-up step; Refresh asks for it too)."""
    return Adopted(folders=_saves(call.session).adopt_legacy())


@operation("saves.health_report", params=PathParams, result=Said)
def health_report(call: Call, p: PathParams) -> Said:
    return Said(text=_saves(call.session).health_report(p.path))


@operation("saves.sheet", params=SheetParams, result=Sheet)
def sheet(call: Call, p: SheetParams) -> Sheet:
    """The save's facts; which slot to show is the client's (the Qt page words the sheet itself)."""
    return Sheet(data=_saves(call.session).save_info(p.path))


@operation("saves.copy_entry", params=CopyRef, result=CopyEntry)
def copy_entry(call: Call, p: CopyRef) -> CopyEntry:
    """One Library copy, for a client to ask about it first (it was changed outside the launcher)."""
    return CopyEntry(**_saves(call.session).copy_entry(p.folder, p.entry_id))


@operation("saves.folder", params=FolderParams, result=Folder, kind="command", writes=True)
def folder(call: Call, p: FolderParams) -> Folder:
    """The Saves, Backups or Library folder to show (the last two are created if they do not exist yet)."""
    got = _saves(call.session).folder(p.which)
    return Folder(path=None if got is None else str(got))


@operation("saves.default_name", params=PathParams, result=Said)
def default_name(call: Call, p: PathParams) -> Said:
    return Said(text=_saves(call.session).default_name(p.path))


# ----------------------------------------------------------------------------- the upkeep of copies and backups
@operation("saves.keep_as", params=KeepAsParams, result=Said, kind="command", writes=True)
def keep_as(call: Call, p: KeepAsParams) -> Said:
    """Copy a backup into the Library under a name (the backup stays and ages out as usual); text is the name."""
    return Said(text=_saves(call.session).keep_as(p.backup, p.name))


@operation("saves.keep_backup", params=KeepParams, result=Said, kind="command", writes=True)
def keep_backup(call: Call, p: KeepParams) -> Said:
    """Keep a backup whatever its age, or let it age out again."""
    _saves(call.session).keep_backup(p.backup, p.keep)
    return Said(text="")


@operation("saves.rename_copy", params=RenameParams, result=Said, kind="command", writes=True)
def rename_copy(call: Call, p: RenameParams) -> Said:
    return Said(text=_saves(call.session).rename_copy(p.folder, p.entry_id, p.name))


@operation("saves.finish_stranded", params=StrandedParams, result=Warned, kind="command", writes=True)
def finish_stranded(call: Call, p: StrandedParams) -> Warned:
    return Warned(warning=_saves(call.session).finish_stranded(p.folder, p.entry_id, p.restore))


@operation("saves.check_delete_backup", params=BackupRef, result=BackupFacts)
def check_delete_backup(call: Call, p: BackupRef) -> BackupFacts:
    """The backup a removal would delete; the client confirms its stamp."""
    got = _saves(call.session).check_delete_backup(p.backup)
    return BackupFacts(path=str(got.path), save_name=got.save_name, when=got.when, action=got.action, stamp=got.stamp)


@operation("saves.delete_backup", params=DeleteBackupParams, result=Said, kind="command", writes=True)
def delete_backup(call: Call, p: DeleteBackupParams) -> Said:
    _saves(call.session).delete_backup(p.backup, p.expect)
    return Said(text="")


@operation("saves.check_remove_copy", params=CopyRef, result=Said)
def check_remove_copy(call: Call, p: CopyRef) -> Said:
    """The name of the copy a removal would take out; the client confirms it."""
    return Said(text=_saves(call.session).check_remove_copy(p.folder, p.entry_id))


@operation("saves.remove_copy", params=RemoveCopyParams, result=Said, kind="command", writes=True)
def remove_copy(call: Call, p: RemoveCopyParams) -> Said:
    _saves(call.session).remove_copy(p.folder, p.entry_id, p.expect)
    return Said(text="")


# ----------------------------------------------------------------------------- jobs that write or add copies
@operation("saves.back_up", params=BackUpParams, result=SavesJob, kind="command", writes=True)
def back_up(call: Call, p: BackUpParams) -> SavesJob:
    """A job; its result is {"saves", "backups"}."""
    return SavesJob(job_id=_saves(call.session).back_up(p.paths, everything=p.everything))


@operation("saves.post_session_repair", result=SavesJob, kind="command", writes=True)
def post_session_repair(call: Call, p: NoParams) -> SavesJob:
    return SavesJob(job_id=_saves(call.session).post_session_repair())


@operation("saves.save_copy", params=SaveCopyParams, result=SavesJob, kind="command", writes=True)
def save_copy(call: Call, p: SaveCopyParams) -> SavesJob:
    """A job; its result is {"source", "entry_id", "name"}."""
    return SavesJob(job_id=_saves(call.session).save_copy(p.path, p.name))


@operation("saves.import_files", params=ImportParams, result=SavesJob, kind="command", writes=True)
def import_files(call: Call, p: ImportParams) -> SavesJob:
    """A job; its result is {"imported": [{"file", "entry_id", "name"}], "failed": [{"file", "code"}]}."""
    return SavesJob(job_id=_saves(call.session).import_files(p.files, p.name))


@operation("saves.undo_change", params=UndoParams, result=SavesJob, kind="command", writes=True)
def undo_change(call: Call, p: UndoParams) -> SavesJob:
    """The toast's Undo: put the backup taken before a write back over the save. The job's result is {"file"}."""
    return SavesJob(job_id=_saves(call.session).undo_change(p.save, p.backup))


# ----------------------------------------------------------------------------- writes to live saves: check, then start
# Each start's job result is the write's facts plus "save", "backup" and "undo" (the record Activity's Undo uses).
@operation("saves.check_copy_character", params=CharacterRef, result=CopyCheck)
def check_copy_character(call: Call, p: CharacterRef) -> CopyCheck:
    return CopyCheck(**_facts(_saves(call.session).check_copy_character(p.source, p.src_slot, p.target, p.dst_slot)))


@operation("saves.copy_character", params=CharacterParams, result=SavesJob, kind="command", writes=True)
def copy_character(call: Call, p: CharacterParams) -> SavesJob:
    """A job; its result is {"character", "slot", "file", "save", "backup", "undo"}."""
    return SavesJob(job_id=_saves(call.session).copy_character(p.source, p.src_slot, p.target, p.dst_slot, p.expect))


@operation("saves.check_replace_from_library", params=ReplaceCopyRef, result=ReplaceCheck)
def check_replace_from_library(call: Call, p: ReplaceCopyRef) -> ReplaceCheck:
    return ReplaceCheck(**_facts(_saves(call.session).check_replace_from_library(p.folder, p.entry_id, p.target)))


@operation("saves.replace_from_library", params=ReplaceCopyParams, result=SavesJob, kind="command", writes=True)
def replace_from_library(call: Call, p: ReplaceCopyParams) -> SavesJob:
    """A job; its result is {"file", "source", "save", "backup", "undo"}."""
    return SavesJob(job_id=_saves(call.session).replace_from_library(p.folder, p.entry_id, p.target, p.expect))


@operation("saves.check_replace_from_file", params=ReplaceFileRef, result=ReplaceCheck)
def check_replace_from_file(call: Call, p: ReplaceFileRef) -> ReplaceCheck:
    return ReplaceCheck(**_facts(_saves(call.session).check_replace_from_file(p.source, p.target)))


@operation("saves.replace_from_file", params=ReplaceFileParams, result=SavesJob, kind="command", writes=True)
def replace_from_file(call: Call, p: ReplaceFileParams) -> SavesJob:
    """A job; its result is {"file", "source", "save", "backup", "undo"}."""
    return SavesJob(job_id=_saves(call.session).replace_from_file(p.source, p.target, p.expect))


@operation("saves.check_restore_backup", params=RestoreRef, result=RestoreCheck)
def check_restore_backup(call: Call, p: RestoreRef) -> RestoreCheck:
    return RestoreCheck(**_facts(_saves(call.session).check_restore_backup(p.backup, p.target)))


@operation("saves.restore_backup", params=RestoreParams, result=SavesJob, kind="command", writes=True)
def restore_backup(call: Call, p: RestoreParams) -> SavesJob:
    """A job; its result is {"file", "save", "backup", "undo"}."""
    return SavesJob(job_id=_saves(call.session).restore_backup(p.backup, p.target, p.expect))


@operation("saves.check_repair", params=RepairRef, result=RepairCheck)
def check_repair(call: Call, p: RepairRef) -> RepairCheck:
    return RepairCheck(**_facts(_saves(call.session).check_repair(p.path, p.keys)))


@operation("saves.repair", params=RepairParams, result=SavesJob, kind="command", writes=True)
def repair(call: Call, p: RepairParams) -> SavesJob:
    """A job; its result is {"file", "save", "backup", "undo"}."""
    return SavesJob(job_id=_saves(call.session).repair(p.path, p.keys, p.expect))
