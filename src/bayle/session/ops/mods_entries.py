"""The Mods page's operations on the entries of a profile for the HTTP layer, each handed to the session's ModsService:
on or off, remove (and take it back), move, rename, the Mod options, the profile's earlier versions, Add existing, and
editing the profile as text. See ops/mods.py for the conventions (checks and starts, confirm-and-retry, codes)."""

from __future__ import annotations

from typing import Any

from bayle.services import mods_page
from bayle.session.operations import Call, Params, Result, operation
from bayle.session.ops.mods import Changed, EntryRef, ModsJob, ProfileRef, svc


# ----------------------------------------------------------------------------- an entry on or off, and its Undo
class EnabledParams(EntryRef):
    enabled: bool
    expect: str | None = None  # the entry's name when the player chose it: a changed profile is stale


@operation("mods.set_enabled", params=EnabledParams, result=Changed, kind="command", writes=True)
def set_enabled(call: Call, p: EnabledParams) -> Changed:
    return Changed(name=svc(call.session).set_enabled(p.profile, p.index, p.enabled, p.expect))


class Undone(Result):
    restored: bool  # there was a copy to put back


@operation("mods.undo_change", params=ProfileRef, result=Undone, kind="command", writes=True)
def undo_change(call: Call, p: ProfileRef) -> Undone:
    """Put back the copy kept just before the last change to the profile."""
    return Undone(restored=svc(call.session).undo_change(p.profile))


# ----------------------------------------------------------------------------- removing an entry
class RemoveParams(EntryRef):
    name: str  # the entry's name when the player chose it: a changed profile is stale
    confirmed: bool = False
    delete_folder: bool | None = None  # the check box; None = the folder goes to the Recycle Bin when that is safe


@operation("mods.remove", params=RemoveParams, result=ModsJob, kind="command", writes=True)
def remove(call: Call, p: RemoveParams) -> ModsJob:
    """A job; its result is {"name", "undo"} (the record mods.undo_removal takes back). Without confirmed it raises
    needs_confirmation (details: the facts to ask about) unless Undo brings everything back. Errors: not_found, stale."""
    return ModsJob(job_id=svc(call.session).remove(p.profile, p.index, p.name, p.delete_folder, p.confirmed))


class UndoParams(Params):
    undo: dict[str, Any]


@operation("mods.undo_removal", params=UndoParams, result=Changed, kind="command", writes=True)
def undo_removal(call: Call, p: UndoParams) -> Changed:
    return Changed(name=svc(call.session).undo_removal(p.undo))


class HolderPlan(Result):
    name: str
    needs: tuple[str, ...]  # the packages whose dependency on it goes too
    stamp: tuple[int, int] | None


@operation("mods.check_remove_holder", params=EntryRef, result=HolderPlan)
def check_remove_holder(call: Call, p: EntryRef) -> HolderPlan:
    """An entry that only points at a folder of mods: taking it out changes nothing in the game."""
    return HolderPlan(**vars(svc(call.session).check_remove_holder(p.profile, p.index)))


class RemoveHolderParams(EntryRef):
    expect: tuple[int, int] | None  # the stamp check_remove_holder gave and the client confirmed


@operation("mods.remove_holder", params=RemoveHolderParams, result=ModsJob, kind="command", writes=True)
def remove_holder(call: Call, p: RemoveHolderParams) -> ModsJob:
    """A job; its result is {"name"}. Errors: not_found, stale, busy."""
    return ModsJob(job_id=svc(call.session).remove_holder(p.profile, p.index, p.expect))


# ----------------------------------------------------------------------------- the load order
class MoveParams(EntryRef):
    to: int  # 0-based position among its kind as the page shows them
    expect: str | None = None


class MoveResult(Result):
    moved: bool
    name: str = ""
    problem: str = ""  # why me3 would not keep it there (moved is False)
    decided_by: int = -1  # the entry whose options decide: "Edit options" opens it (-1: none)


@operation("mods.move", params=MoveParams, result=MoveResult, kind="command", writes=True)
def move(call: Call, p: MoveParams) -> MoveResult:
    return MoveResult(**vars(svc(call.session).move(p.profile, p.index, p.to, p.expect)))


@operation("mods.fix_order", params=ProfileRef, result=Changed, kind="command", writes=True)
def fix_order(call: Call, p: ProfileRef) -> Changed:
    """Put the mod that must stay last back last."""
    svc(call.session).fix_order(p.profile)
    return Changed()


# ----------------------------------------------------------------------------- renaming one mod
class RenameStart(Result):
    name: str  # the entry's folder name: where the Rename dialog starts


@operation("mods.rename_start", params=EntryRef, result=RenameStart)
def rename_start(call: Call, p: EntryRef) -> RenameStart:
    return RenameStart(name=svc(call.session).folder_name(p.profile, p.index))


class RenameParams(EntryRef):
    name: str
    expect: str | None = None


class RenamePreview(Result):
    ok: bool
    lines: tuple[str, ...]
    refusals: tuple[str, ...]


@operation("mods.rename_preview", params=RenameParams, result=RenamePreview)
def rename_preview(call: Call, p: RenameParams) -> RenamePreview:
    """Whether renaming to the name is allowed and what it would change; nothing is written."""
    return RenamePreview(**vars(svc(call.session).rename_preview(p.profile, p.index, p.name)))


@operation("mods.rename", params=RenameParams, result=ModsJob, kind="command", writes=True)
def rename(call: Call, p: RenameParams) -> ModsJob:
    """A job; its result is {"name", "to"}. Errors: not_found, stale, busy."""
    return ModsJob(job_id=svc(call.session).rename(p.profile, p.index, p.name, p.expect))


# ----------------------------------------------------------------------------- Mod options
class Dependency(Params):
    id: str
    optional: bool = False


class OptionsView(Result):
    """What the Mod options dialog shows for one entry. init_kind: 0 none, 1 call a function, 2 wait (ms); overlay:
    null when it does not apply, else whether the parameter overlay is set by hand."""

    index: int
    name: str
    kind: str
    enabled: bool
    id: str
    load_after: tuple[mods_page.Dependency, ...]
    load_before: tuple[mods_page.Dependency, ...]
    optional: bool
    load_early: bool
    init_kind: int
    init_value: str
    finalizer: str
    others: tuple[str, ...]
    overlay: bool | None
    rebuild_file: str


@operation("mods.options", params=EntryRef, result=OptionsView)
def options(call: Call, p: EntryRef) -> OptionsView:
    return OptionsView(**vars(svc(call.session).options(p.profile, p.index)))


class OptionsInput(EntryRef):
    enabled: bool = True
    id: str = ""  # a package's id
    load_after: tuple[Dependency, ...] = ()
    load_before: tuple[Dependency, ...] = ()
    optional: bool = False  # natives from here on
    load_early: bool = False
    finalizer: str = ""
    init_kind: int = 0
    init_value: str = ""
    overlay: bool | None = None  # null leaves the parameter overlay as it is
    rebuild_file: str = ""
    expect: str | None = None


@operation("mods.save_options", params=OptionsInput, result=Changed, kind="command", writes=True)
def save_options(call: Call, p: OptionsInput) -> Changed:
    """Errors: not_found, stale, invalid_wait, options_not_saved."""
    change = mods_page.OptionsChange(
        enabled=p.enabled,
        id=p.id,
        load_after=tuple(mods_page.Dependency(d.id, d.optional) for d in p.load_after),
        load_before=tuple(mods_page.Dependency(d.id, d.optional) for d in p.load_before),
        optional=p.optional,
        load_early=p.load_early,
        finalizer=p.finalizer,
        init_kind=p.init_kind,
        init_value=p.init_value,
        overlay=p.overlay,
        rebuild_file=p.rebuild_file,
    )
    return Changed(name=svc(call.session).save_options(p.profile, p.index, change, p.expect))


# ----------------------------------------------------------------------------- the profile's own history and files
class VersionList(Result):
    versions: tuple[mods_page.VersionRow, ...]


@operation("mods.versions", params=ProfileRef, result=VersionList)
def versions(call: Call, p: ProfileRef) -> VersionList:
    return VersionList(versions=svc(call.session).versions(p.profile))


class RestoreParams(ProfileRef):
    path: str  # one of mods.versions' paths


class Restored(Result):
    before: str | None  # the copy of the profile as it was: restoring it undoes this restore


@operation("mods.restore_version", params=RestoreParams, result=Restored, kind="command", writes=True)
def restore_version(call: Call, p: RestoreParams) -> Restored:
    return Restored(before=svc(call.session).restore_version(p.profile, p.path))


class KindParams(ProfileRef):
    kind: str  # package | native


class Unlisted(Result):
    folders: tuple[mods_page.UnlistedFolder, ...]  # in the profile's folders, loaded by no entry


@operation("mods.unlisted", params=KindParams, result=Unlisted)
def unlisted(call: Call, p: KindParams) -> Unlisted:
    return Unlisted(folders=svc(call.session).unlisted(p.profile, p.kind))


class AddParams(KindParams):
    paths: list[str]  # some of mods.unlisted's paths


class Added(Result):
    names: tuple[str, ...]
    loose_dlls: bool  # DLLs not in a folder of their own: the page offers to put them in folders


@operation("mods.add_existing", params=AddParams, result=Added, kind="command", writes=True)
def add_existing(call: Call, p: AddParams) -> Added:
    return Added(**vars(svc(call.session).add_existing(p.profile, p.kind, p.paths)))


# ----------------------------------------------------------------------------- Edit as text
class TextView(Result):
    text: str  # with LF line ends
    crlf: bool  # the file had CRLF: saving puts them back


@operation("mods.text", params=ProfileRef, result=TextView)
def read_text(call: Call, p: ProfileRef) -> TextView:
    return TextView(**vars(svc(call.session).read_text(p.profile)))


class CheckParams(Params):
    text: str


class TextCheck(Result):
    problem: str  # why it does not parse as TOML (the parser's words), "" when it does


@operation("mods.check_text", params=CheckParams, result=TextCheck)
def check_text(call: Call, p: CheckParams) -> TextCheck:
    """The parse gate of the editor: pure, nothing is read from disk."""
    return TextCheck(problem=svc(call.session).check_text(p.text))


class SaveTextParams(ProfileRef):
    text: str
    crlf: bool = False


@operation("mods.save_text", params=SaveTextParams, result=Changed, kind="command", writes=True)
def save_text(call: Call, p: SaveTextParams) -> Changed:
    """The profile as the player wrote it (a Version is kept first). Errors: invalid_toml (details: why)."""
    svc(call.session).save_text(p.profile, p.text, p.crlf)
    return Changed()
