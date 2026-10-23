"""The Saves page's operations: its snapshot (live saves, Library, Backups), the reads (health report, character
sheet, one Library copy), the Library's and Backups' upkeep, and every write to a live save.

A write to a live save is a job (a logged one that backs up first and returns how to take it back: Written.undo) or a
plan whose answer starts that job; the session's gate (no game, no other writing job) is the job manager's. A plan
checks the same gate first so the player is told why before being asked. Errors are OperationError codes.

The reads and the upkeep are handed straight to the session's SavesService (services.saves_page), with no wording:
the two removals are a check (what would go) and a start (with what the client confirmed). Temporary, as for
Settings: the Qt page calls the service itself."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from bayle.errors import OperationError
from bayle.platform.text import tr
from bayle.services import saves as saves_service
from bayle.services import saves_page as svc
from bayle.services.saves_page import SavesService
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry
from bayle.views.common import Refusal
from bayle.views.saves import SavesPresenter
from bayle.work.prompts import Answer, Proposal


# ----------------------------------------------------------------------------- models
@dataclass(frozen=True)
class SavesState:
    """The page's facts. The presenter (views.saves) words them; which save the profile plays on is the host's."""

    infos: list[dict[str, Any]]
    libraries: dict[str, dict[str, Any]]
    backups: list[dict[str, Any]]


class Written(Result):
    """What a save write did. undo is the record the jobs index holds (Activity's Undo and saves.undo_change use it)."""

    text: str
    save: str | None = None
    backup: str | None = None
    undo: dict[str, Any] | None = None


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


class CharacterParams(Params):
    source: str
    src_slot: int
    target: str
    dst_slot: int


class CopyRef(Params):
    folder: str
    entry_id: str


class ReplaceCopyParams(CopyRef):
    target: str


class ReplaceFileParams(Params):
    source: str
    target: str


class RestoreParams(Params):
    backup: str
    target: str


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


class RepairParams(PathParams):
    keys: list[list[str | int]]  # the ticked boxes as the presenter names them (("checksum", 2), ("item", 1, 500))


class SheetParams(PathParams):
    slot: int


class FolderParams(Params):
    which: Literal["saves", "backups", "library"]


class UndoParams(Params):
    save: str
    backup: str


# ----------------------------------------------------------------------------- helpers
def _presenter() -> SavesPresenter:
    return SavesPresenter()


def _written(w: svc.Written) -> Written:
    return Written(
        text=w.text,
        save=None if w.save is None else str(w.save),
        backup=None if w.backup is None else str(w.backup),
        undo=w.undo,
    )


def _gate(session: Session, read_only: bool = False) -> Refusal | None:
    """Why a write cannot start now (a job runs; the game runs, unless the write only reads the live save)."""
    jobs = session.jobs
    if jobs.busy or (jobs.game_running and not read_only):
        return _presenter().refusal_busy(session.locations().game.name, jobs.game_running and not jobs.busy)
    return None


def _stamp(path: Path) -> object:
    """A cheap read of a file for a plan's staleness: it is refused when the file changed since the question."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def _start(session: Session, title: str, write: Any) -> str:
    """Start a save write (write(loc) -> svc.Written) as a session job."""
    loc = session.locations()
    return session.start(lambda _ctx: _written(write(loc)), title=title)


def _unusable(e: OperationError) -> Refusal:
    return Refusal(tr("This copy cannot be used"), e.message)


def _plan_failed(e: Exception) -> Refusal:
    return Refusal(tr("This cannot be done"), str(e))


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


@operation(
    "saves.post_session_repair", result=Written, kind="job", writes=True, title=lambda p: tr("Repairing saves...")
)
def post_session_repair(call: Call, p: NoParams) -> Written:
    return _written(svc.post_session_repair(loc=call.session.locations()))


@operation("saves.save_copy", params=SaveCopyParams, result=SavesJob, kind="command", writes=True)
def save_copy(call: Call, p: SaveCopyParams) -> SavesJob:
    """A job; its result is {"source", "entry_id", "name"}."""
    return SavesJob(job_id=_saves(call.session).save_copy(p.path, p.name))


@operation("saves.import_files", params=ImportParams, result=SavesJob, kind="command", writes=True)
def import_files(call: Call, p: ImportParams) -> SavesJob:
    """A job; its result is {"imported": [{"file", "entry_id", "name"}], "failed": [{"file", "code"}]}."""
    return SavesJob(job_id=_saves(call.session).import_files(p.files, p.name))


@operation(
    "saves.undo_change",
    params=UndoParams,
    result=Said,
    kind="job",
    writes=True,
    title=lambda p: tr("Undoing the change to {name}...").format(name=Path(p.save).name),
)
def undo_change(call: Call, p: UndoParams) -> Said:
    """The toast's Undo: put the backup taken before a write back over the save."""
    return Said(text=svc.undo_change(Path(p.save), Path(p.backup), loc=call.session.locations()))


# ----------------------------------------------------------------------------- plans: ask, then a job
@operation("saves.copy_character", params=CharacterParams, result=Written, kind="plan", writes=True)
def copy_character(call: Call, p: CharacterParams) -> Proposal | Refusal:
    session = call.session
    if (no := _gate(session)) is not None:
        return no
    src, dst = Path(p.source), Path(p.target)
    try:
        plan = svc.plan_character_copy(src, p.src_slot, dst, p.dst_slot)
    except Exception as e:
        return _plan_failed(e)
    same = src.resolve() == dst.resolve()
    words = _presenter().character_copy(plan, src.name, dst.name, p.dst_slot, same)

    def run(_a: Answer) -> str:
        return _start(
            session,
            tr("Copying a character into {name}...").format(name=dst.name),
            lambda loc: svc.copy_character(src, p.src_slot, dst, p.dst_slot, loc=loc),
        )

    return Proposal(words, run, stale=lambda: (_stamp(src), _stamp(dst)), destructive=bool(plan["replaces"]))


def _replace_plan(
    session: Session, source: Path, target: Path, label: str, restore: bool, start: Any
) -> Proposal | Refusal:
    if (no := _gate(session)) is not None:
        return no
    loc = session.locations()
    try:
        facts = svc.replace_facts(source, target, loc=loc)
    except Exception as e:
        return _plan_failed(e)
    pres = _presenter()
    kinds = None
    if source.suffix.lower() != target.suffix.lower():
        kinds = (pres.kind_of(source), pres.kind_of(target))
    words = pres.replace(
        label,
        target.name,
        facts["rows"],
        facts["signed"],
        facts["holders"],
        target.suffix.lower() == ".sl2",
        restore=restore,
        kinds=kinds,
    )

    def run(_a: Answer) -> str:
        return _start(session, tr("Replacing {name}...").format(name=target.name), start)

    return Proposal(words, run, stale=lambda: (_stamp(source), _stamp(target)), destructive=True)


@operation("saves.replace_from_library", params=ReplaceCopyParams, result=Written, kind="plan", writes=True)
def replace_from_library(call: Call, p: ReplaceCopyParams) -> Proposal | Refusal:
    session = call.session
    if (no := _gate(session)) is not None:
        return no
    folder_, tgt = Path(p.folder), Path(p.target)
    try:
        entry = svc.library_entry(folder_, p.entry_id)
    except OperationError as e:
        return _unusable(e)
    return _replace_plan(
        session,
        entry["path"],
        tgt,
        entry["name"],
        True,
        lambda loc: svc.replace_with_copy(folder_, p.entry_id, tgt, entry["name"], loc=loc),
    )


@operation("saves.replace_from_file", params=ReplaceFileParams, result=Written, kind="plan", writes=True)
def replace_from_file(call: Call, p: ReplaceFileParams) -> Proposal | Refusal:
    src, tgt = Path(p.source), Path(p.target)
    return _replace_plan(call.session, src, tgt, src.name, False, lambda loc: svc.replace_with_file(src, tgt, loc=loc))


@operation("saves.restore_backup", params=RestoreParams, result=Written, kind="plan", writes=True)
def restore_backup(call: Call, p: RestoreParams) -> Proposal | Refusal:
    session = call.session
    if (no := _gate(session)) is not None:
        return no
    bak, tgt = Path(p.backup), Path(p.target)
    row = next((b for b in saves_service.list_backups(loc=session.locations()) if str(b["path"]) == p.backup), None)
    if row is None:
        raise OperationError("not_found", tr("That backup is no longer listed."), {"backup": p.backup})

    def run(_a: Answer) -> str:
        return _start(
            session,
            tr("Restoring {name}...").format(name=tgt.name),
            lambda loc: svc.restore_from_backup(bak, tgt, loc=loc),
        )

    return Proposal(_presenter().restore(row, tgt.name), run, stale=lambda: (_stamp(bak), _stamp(tgt)))


@operation("saves.repair", params=RepairParams, result=Written, kind="plan", writes=True)
def repair(call: Call, p: RepairParams) -> Proposal | Refusal:
    session = call.session
    if (no := _gate(session)) is not None:
        return no
    path = Path(p.path)
    keys = [tuple(k) for k in p.keys]
    if not keys:
        raise OperationError("invalid_params", tr("Tick at least one item to repair."))
    pres = _presenter()
    info = saves_service.save_info(path, loc=session.locations())
    calls = pres.calls(keys)

    def run(_a: Answer) -> str:
        return _start(
            session,
            tr("Repairing {name}...").format(name=path.name),
            lambda loc: svc.repair(path, calls, len(keys), loc=loc),
        )

    return Proposal(pres.repair_confirm(info, keys), run, stale=lambda: _stamp(path))
