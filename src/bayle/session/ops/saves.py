"""The Saves page's operations: its snapshot (live saves, Library, Backups), the reads (health report, character
sheet, one Library copy), the Library's and Backups' upkeep, and every write to a live save.

A write to a live save is a job (a logged one that backs up first and returns how to take it back: Written.undo) or a
plan whose answer starts that job; the session's gate (no game, no other writing job) is the job manager's. A plan
checks the same gate first so the player is told why before being asked. Errors are OperationError codes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from bayle.platform import desktop
from bayle.platform.text import tr
from bayle.services import play as play_service
from bayle.services import saves as saves_service
from bayle.services import saves_page as svc
from bayle.services.errors import Busy, OperationError
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry
from bayle.session.plans import Answer, Proposal
from bayle.views.common import Refusal, prompt_dict
from bayle.views.saves import SavesPresenter


# ----------------------------------------------------------------------------- models
@dataclass(frozen=True)
class SavesState:
    """The page's facts. The presenter (views.saves) words them; which save the profile plays on is the host's."""

    infos: list[dict[str, Any]]
    libraries: dict[str, dict[str, Any]]
    backups: list[dict[str, Any]]
    # What a client without the presenter shows: the page's words and cards, the Library rows, the Backups by day
    # (views.saves, wording included).
    view: dict[str, Any] = field(default_factory=dict)


class Written(Result):
    """What a save write did. undo is the record the jobs index holds (Activity's Undo and saves.undo_change use it)."""

    text: str
    save: str | None = None
    backup: str | None = None
    undo: dict[str, Any] | None = None


class Said(Result):
    text: str


class Sheet(Result):
    data: dict[str, Any]  # views.saves.sheet: overview and stats of one character


class CopyEntry(Result):
    name: str
    path: str
    changed_outside: bool
    outside: dict[str, Any] | None = None  # when changed_outside: the question to ask before using it (a confirm)


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


class RepairViewParams(PathParams):
    slot: int | None = None  # 0-based character; None or negative: the whole file
    ticked: list[str] | None = None  # the boxes ticked now, by key; None: the ones ticked by default


class RepairView(Result):
    data: dict[str, Any]  # views.saves: card, groups, damaged, tuples, ticked, summary, button


class DropParams(Params):
    source: dict[str, Any]  # {type: character|live|copy|backup|copychar, path, slot, folder, id, missing}
    target: dict[str, Any]  # {type: slot|card|library|backups, path, slot, free}


class Dropped(Result):
    reason: str = ""  # why the spot refuses this drag, in words; "" when it takes it
    call: str = ""  # the action the drop means (copyCharacter, copyFromLibrary, replaceFromLibrary, restoreBackup,
    args: list[Any] = []  # backUpNow, askName) and its arguments


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


def _no_shell() -> Any:
    raise OperationError("no_shell", "This session has no shell.")


def _in_use(session: Session) -> dict[str, Any]:
    """The save files the profile in use plays on by name ({} without a shell or a profile)."""
    try:
        state = session.service("shell", _no_shell).state
        return play_service.profile_saves(state.launch_profile, state.game)
    except Exception:
        return {}


def _role(used: dict[str, Any], name: str) -> str:
    if name.lower() == str(used.get("active") or "").lower():
        return tr("Launch Profile uses this")
    if used.get("coop") and name.lower() == str(used.get("standard") or "").lower():
        return tr("Launch Vanilla and Launch Offline use this")
    return ""


def _copy_targets(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where a character can go: every slot of every live save (an empty slot, or one it replaces)."""
    out = []
    for c in cards:
        by_slot = {ch["slot"]: ch for ch in c["characters"]}
        for n in range(1, 11):
            old = by_slot.get(n)
            label = (
                tr("{kind}  \u00b7  slot {n}  \u00b7  replaces {name}").format(kind=c["kind"], n=n, name=old["name"])
                if old
                else tr("{kind}  \u00b7  slot {n}  \u00b7  empty").format(kind=c["kind"], n=n)
            )
            out.append({"path": c["path"], "slot": n, "danger": old is not None, "label": label})
    return out


def _view(session: Session, facts: svc.SavesFacts) -> dict[str, Any]:
    pres, game = _presenter(), session.locations().game
    running, used = bool(session.jobs.game_running), _in_use(session)
    ordered = sorted(facts.infos, key=lambda i: 0 if i["kind"] == "Standard" else 1)  # Standard first
    cards = [pres.card(i, _role(used, i["name"]), running) for i in ordered]
    rows, problems = pres.library_rows(facts.libraries)
    return {
        "words": pres.words(),
        "game_name": game.name,
        "running": running,
        "encrypted": game.save_reader != "eldenring",
        "running_bar": pres.running_bar(game.name),
        "cards": cards,
        "copy_targets": _copy_targets(cards),
        "library_rows": rows,
        "library_problems": problems,
        "backup_days": pres.backup_days(facts.backups),
        "retention": pres.retention(*svc.retention_limits()),
    }


# ----------------------------------------------------------------------------- the page and its reads
@registry.page("saves", view=SavesState)
def snapshot(session: Session) -> SavesState:
    facts = svc.read_facts(session.locations())
    return SavesState(facts.infos, facts.libraries, facts.backups, _view(session, facts))


@operation("saves.adopt_legacy", result=Adopted, kind="command", writes=True)
def adopt_legacy(call: Call, p: NoParams) -> Adopted:
    """Take in backup folders older tools left beside the saves (also a start-up step; Refresh asks for it too)."""
    return Adopted(folders=svc.adopt_legacy_folders(call.session.locations()))


@operation("saves.health_report", params=PathParams, result=Said)
def health_report(call: Call, p: PathParams) -> Said:
    return Said(text=saves_service.health_report(Path(p.path), loc=call.session.locations()))


@operation("saves.sheet", params=SheetParams, result=Sheet)
def sheet(call: Call, p: SheetParams) -> Sheet:
    info = saves_service.save_info(Path(p.path), loc=call.session.locations())
    return Sheet(data=_presenter().sheet(info, p.slot))


@operation("saves.repair_view", params=RepairViewParams, result=RepairView)
def repair_view(call: Call, p: RepairViewParams) -> RepairView:
    """Check & repair for one save: the finding cards for the whole file or one character, what is ticked and what the
    ticked boxes do. The ticks are the client's: it sends them back (None: the ones ticked by default)."""
    session, pres = call.session, _presenter()
    info = saves_service.save_info(Path(p.path), loc=session.locations())
    whole = pres.repair_groups(info)
    every = {i["key"]: i["tuple"] for g in whole for i in g["items"]}
    ticked = pres.default_ticks(whole) if p.ticked is None else sorted(k for k in p.ticked if k in every)
    slot = None if p.slot is None or p.slot < 0 else p.slot
    groups = [
        {
            **g,
            "items": [
                {k: v for k, v in i.items() if k != "tuple"} | {"checked": i["key"] in ticked} for i in g["items"]
            ],
        }
        for g in pres.repair_groups(info, slot)
    ]
    keys = [every[k] for k in ticked]
    return RepairView(
        data={
            "card": pres.card(info, "", bool(session.jobs.game_running)),
            "groups": groups,
            "damaged": pres.damaged(info),
            "tuples": {k: list(v) for k, v in every.items()},
            "ticked": ticked,
            "summary": pres.summary(keys),
            "button": pres.repair_button(len(keys)),
        }
    )


@operation("saves.drop", params=DropParams, result=Dropped)
def drop(call: Call, p: DropParams) -> Dropped:
    """What dropping a source on a target means (the presenter's one rule set): the action to take, or why not."""
    session = call.session
    game, jobs = session.locations().game, session.jobs
    got = _presenter().drop(
        p.source,
        p.target,
        game=game.name,
        running=bool(jobs.game_running),
        busy=bool(jobs.busy),
        encrypted=game.save_reader != "eldenring",
    )
    if isinstance(got, Refusal):
        return Dropped(reason=f"{got.title}. {got.body}")
    return Dropped(call=got.call, args=list(got.args))


@operation("saves.open_folder", params=PathParams, result=Said, kind="command")
def open_folder(call: Call, p: PathParams) -> Said:
    """Show a folder in the desktop's file manager (a folder only: a file would be run)."""
    path = Path(p.path)
    if not path.is_dir():
        raise OperationError("not_found", tr("That folder does not exist."), {"path": p.path})
    desktop.open_path(path)
    return Said(text=str(path))


@operation("saves.copy_entry", params=CopyRef, result=CopyEntry)
def copy_entry(call: Call, p: CopyRef) -> CopyEntry:
    """One Library copy, for a client to ask about it first (it was changed outside the launcher)."""
    e = svc.library_entry(Path(p.folder), p.entry_id)
    outside = prompt_dict(_presenter().changed_outside(e["name"])) if e["changed_outside"] else None
    return CopyEntry(name=e["name"], path=str(e["path"]), changed_outside=e["changed_outside"], outside=outside)


@operation("saves.folder", params=FolderParams, result=Folder, kind="command", writes=True)
def folder(call: Call, p: FolderParams) -> Folder:
    """The Saves, Backups or Library folder to show (the last two are created if they do not exist yet)."""
    got = svc.open_folder(p.which, loc=call.session.locations())
    return Folder(path=None if got is None else str(got))


@operation("saves.default_name", params=PathParams, result=Said)
def default_name(call: Call, p: PathParams) -> Said:
    return Said(text=svc.library_default_name(Path(p.path), call.session.locations()))


# ----------------------------------------------------------------------------- the upkeep of copies and backups
@operation("saves.keep_as", params=KeepAsParams, result=Said, kind="command", writes=True)
def keep_as(call: Call, p: KeepAsParams) -> Said:
    """Copy a backup into the Library under a name (the backup stays and ages out as usual)."""
    try:
        e = saves_service.keep_backup_as_copy(Path(p.backup), p.name, loc=call.session.locations())
    except Exception as ex:
        raise OperationError("failed", str(ex)) from ex
    return Said(text=e["name"])


@operation("saves.keep_backup", params=KeepParams, result=Said, kind="command", writes=True)
def keep_backup(call: Call, p: KeepParams) -> Said:
    """Keep a backup whatever its age, or let it age out again."""
    try:
        saves_service.keep_backup(Path(p.backup), p.keep)
    except OSError as e:
        raise OperationError("failed", str(e)) from e
    return Said(text="")


@operation("saves.rename_copy", params=RenameParams, result=Said, kind="command", writes=True)
def rename_copy(call: Call, p: RenameParams) -> Said:
    svc.rename_copy(Path(p.folder), p.entry_id, p.name)
    return Said(text=p.name)


@operation("saves.finish_stranded", params=StrandedParams, result=Warned, kind="command", writes=True)
def finish_stranded(call: Call, p: StrandedParams) -> Warned:
    return Warned(warning=svc.finish_stranded(Path(p.folder), p.entry_id, p.restore))


@operation("saves.delete_backup", params=BackupRef, result=Said, kind="plan", writes=True)
def delete_backup(call: Call, p: BackupRef) -> Proposal | Refusal:
    session = call.session
    days = _presenter().backup_days(saves_service.list_backups(loc=session.locations()))
    row = next((b for d in days for b in d["rows"] if b["path"] == p.backup), None)
    if row is None:
        raise OperationError("not_found", tr("That backup is no longer listed."), {"backup": p.backup})

    def run(_a: Answer) -> None:
        try:
            saves_service.delete_backup(Path(p.backup))
        except Exception as e:
            raise OperationError("failed", str(e)) from e

    return Proposal(_presenter().delete_backup(row), run, destructive=True)


@operation("saves.remove_copy", params=CopyRef, result=Said, kind="plan", writes=True)
def remove_copy(call: Call, p: CopyRef) -> Proposal | Refusal:
    name = svc.library_name(Path(p.folder), p.entry_id)
    if name is None:
        raise OperationError("not_found", tr("That copy is no longer listed."), {"entry_id": p.entry_id})

    def run(_a: Answer) -> None:
        svc.remove_copy(Path(p.folder), p.entry_id)

    return Proposal(_presenter().remove_copy(name), run, destructive=True)


# ----------------------------------------------------------------------------- jobs that write or add copies
@operation(
    "saves.back_up",
    params=BackUpParams,
    result=Written,
    kind="job",
    writes=True,
    title=lambda p: (
        tr("Backing up {name}...").format(name=Path(p.paths[0]).name)
        if len(p.paths) == 1 and not p.everything
        else tr("Backing up saves...")
    ),
)
def back_up(call: Call, p: BackUpParams) -> Written:
    if not p.everything and not p.paths:
        raise OperationError("invalid_params", tr("Say which saves to back up."))
    return _written(svc.back_up([Path(x) for x in p.paths], everything=p.everything, loc=call.session.locations()))


@operation(
    "saves.post_session_repair", result=Written, kind="job", writes=True, title=lambda p: tr("Repairing saves...")
)
def post_session_repair(call: Call, p: NoParams) -> Written:
    return _written(svc.post_session_repair(loc=call.session.locations()))


# Save a copy and Import only read the live save and add to the Library: the game may run, another write may not.
def _no_other_write(session: Session) -> None:
    if session.jobs.busy:
        raise Busy("Another operation is running.", {"reason": "job"})


@operation("saves.save_copy", params=SaveCopyParams, result=Written, kind="job", title=lambda p: tr("Saving a copy..."))
def save_copy(call: Call, p: SaveCopyParams) -> Written:
    _no_other_write(call.session)
    return _written(svc.save_copy(Path(p.path), p.name, loc=call.session.locations()))


@operation("saves.import_files", params=ImportParams, result=Written, kind="job", title=lambda p: tr("Importing..."))
def import_files(call: Call, p: ImportParams) -> Written:
    _no_other_write(call.session)
    return _written(svc.import_files([Path(x) for x in p.files], p.name, loc=call.session.locations()))


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
