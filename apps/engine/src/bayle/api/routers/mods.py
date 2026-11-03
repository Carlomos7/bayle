"""mods over HTTP: each route hands its call to the engine's ModsService (see routers/activity.py for the shape).
GET /v1/mods is the Mods page's facts for one profile; the POST routes change a profile or its entries. A plan is a
check (what would change, with a stamp) and a start (with the stamp the client confirmed); the long writes return
{"job_id"}. A change that asks only sometimes answers needs_confirmation (details: the reason and facts) until it is
sent again confirmed. Refusals are OperationError codes. A profile is its .me3 path, sent in every call (the shell owns
which one is current). No wording here; the client words what it gets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import JobStarted as Started
from bayle.api.models import Params, Result
from bayle.modules.mods import mods_page
from bayle.modules.mods.mods_page import ModsPageState, ModsService

router = APIRouter(prefix="/mods", tags=["mods"])
Mods = Annotated[ModsService, Depends(service("mods"))]


# ----------------------------------------------------------------------------- params shared with the other mod routers
class ProfileRef(Params):
    profile: str  # the .me3 path


class LaunchRef(ProfileRef):
    """The profile as the setup the shell launches: kind "me3" or "manifest" (an overhaul installer's), and its source."""

    kind: str = "me3"
    source: str = ""


class EntryRef(ProfileRef):
    index: int  # the entry's block index in the profile


class ModsScope(Params):
    profile: str = ""  # "" = none picked
    kind: str = "me3"
    source: str = ""
    no_profiles: bool = False  # this game has no profile at all (the page says how to start)


class Changed(Result):
    """A command that wrote the profile: the host's other views read it again, and Undo restores the version before."""

    name: str = ""


@router.get("", name="mods")
def page(m: Mods, q: Annotated[ModsScope, Query()]) -> ModsPageState:
    return m.page(q.profile, q.kind, q.source, q.no_profiles)


# ----------------------------------------------------------------------------- notices, hints, the drag table
class NoticeRef(ProfileRef):
    key: str


class NoticeClosed(Result):
    key: str


@router.post("/close_notice", name="mods_close_notice")
def close_notice(m: Mods, p: NoticeRef) -> NoticeClosed:
    m.close_notice(p.profile, p.key)
    return NoticeClosed(key=p.key)


class LibraryHint(Result):
    mods: int
    size: int
    enough: bool  # more than the Library is suggested for
    closed: bool  # the player closed the InfoBar for this profile


@router.post("/library_hint", name="mods_library_hint")
def library_hint(m: Mods, p: ProfileRef) -> LibraryHint:
    """Mods kept as the same Separate copy in several profiles (the disk scan; worked out after the page shows)."""
    return LibraryHint(**vars(m.library_hint(p.profile)))


class DragTable(Result):
    kind: str
    reasons: dict[
        int, str
    ]  # target position (0-based among the kind as shown) -> why a drop there is refused, "" if not


@router.post("/drag", name="mods_drag")
def drag(m: Mods, p: EntryRef) -> DragTable:
    """Ship the ordering so a client drags without asking again: the refusal for every drop spot of this entry."""
    return DragTable(**vars(m.drag(p.profile, p.index)))


# ----------------------------------------------------------------------------- an entry on or off, and its Undo
class EnabledParams(EntryRef):
    enabled: bool
    expect: str | None = None  # the entry's name when the player chose it: a changed profile is stale


@router.post("/set_enabled", name="mods_set_enabled")
def set_enabled(m: Mods, p: EnabledParams) -> Changed:
    return Changed(name=m.set_enabled(p.profile, p.index, p.enabled, p.expect))


class Undone(Result):
    restored: bool  # there was a copy to put back


@router.post("/undo_change", name="mods_undo_change")
def undo_change(m: Mods, p: ProfileRef) -> Undone:
    """Put back the copy kept just before the last change to the profile."""
    return Undone(restored=m.undo_change(p.profile))


# ----------------------------------------------------------------------------- removing an entry
class RemoveParams(EntryRef):
    name: str  # the entry's name when the player chose it: a changed profile is stale
    confirmed: bool = False
    delete_folder: bool | None = None  # the check box; None = the folder goes to the Recycle Bin when that is safe


@router.post("/remove", name="mods_remove")
def remove(m: Mods, p: RemoveParams) -> Started:
    """A job; its result is {"name", "undo"} (the record undo_removal takes back). Without confirmed it answers
    needs_confirmation (details: the facts to ask about) unless Undo brings everything back. Errors: not_found, stale."""
    return Started(job_id=m.remove(p.profile, p.index, p.name, p.delete_folder, p.confirmed))


class UndoParams(Params):
    undo: dict[str, Any]


@router.post("/undo_removal", name="mods_undo_removal")
def undo_removal(m: Mods, p: UndoParams) -> Changed:
    return Changed(name=m.undo_removal(p.undo))


class HolderPlan(Result):
    name: str
    needs: tuple[str, ...]  # the packages whose dependency on it goes too
    stamp: tuple[int, int] | None


@router.post("/check_remove_holder", name="mods_check_remove_holder")
def check_remove_holder(m: Mods, p: EntryRef) -> HolderPlan:
    """An entry that only points at a folder of mods: taking it out changes nothing in the game."""
    return HolderPlan(**vars(m.check_remove_holder(p.profile, p.index)))


class RemoveHolderParams(EntryRef):
    expect: tuple[int, int] | None  # the stamp check_remove_holder gave and the client confirmed


@router.post("/remove_holder", name="mods_remove_holder")
def remove_holder(m: Mods, p: RemoveHolderParams) -> Started:
    """A job; its result is {"name"}. Errors: not_found, stale, busy."""
    return Started(job_id=m.remove_holder(p.profile, p.index, p.expect))


# ----------------------------------------------------------------------------- the load order
class MoveParams(EntryRef):
    to: int  # 0-based position among its kind as the page shows them
    expect: str | None = None


class MoveResult(Result):
    moved: bool
    name: str = ""
    problem: str = ""  # why me3 would not keep it there (moved is False)
    decided_by: int = -1  # the entry whose options decide: "Edit options" opens it (-1: none)


@router.post("/move", name="mods_move")
def move(m: Mods, p: MoveParams) -> MoveResult:
    return MoveResult(**vars(m.move(p.profile, p.index, p.to, p.expect)))


@router.post("/fix_order", name="mods_fix_order")
def fix_order(m: Mods, p: ProfileRef) -> Changed:
    """Put the mod that must stay last back last."""
    m.fix_order(p.profile)
    return Changed()


# ----------------------------------------------------------------------------- renaming one mod
class RenameStart(Result):
    name: str  # the entry's folder name: where the Rename dialog starts


@router.post("/rename_start", name="mods_rename_start")
def rename_start(m: Mods, p: EntryRef) -> RenameStart:
    return RenameStart(name=m.folder_name(p.profile, p.index))


class ModFiles(Result):
    files: list[str]  # relative to the mod's folder, "/" separated, in order
    truncated: bool  # there are more files than were listed
    native: bool  # the mod is one DLL


@router.post("/files", name="mods_files")
def files(m: Mods, p: EntryRef) -> ModFiles:
    listed, more, native = m.files(p.profile, p.index)
    return ModFiles(files=listed, truncated=more, native=native)


class RenameParams(EntryRef):
    name: str
    expect: str | None = None


class RenamePreview(Result):
    ok: bool
    lines: tuple[str, ...]
    refusals: tuple[str, ...]


@router.post("/rename_preview", name="mods_rename_preview")
def rename_preview(m: Mods, p: RenameParams) -> RenamePreview:
    """Whether renaming to the name is allowed and what it would change; nothing is written."""
    return RenamePreview(**vars(m.rename_preview(p.profile, p.index, p.name)))


@router.post("/rename", name="mods_rename")
def rename(m: Mods, p: RenameParams) -> Started:
    """A job; its result is {"name", "to"}. Errors: not_found, stale, busy."""
    return Started(job_id=m.rename(p.profile, p.index, p.name, p.expect))


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


@router.post("/options", name="mods_options")
def options(m: Mods, p: EntryRef) -> OptionsView:
    return OptionsView(**vars(m.options(p.profile, p.index)))


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


@router.post("/save_options", name="mods_save_options")
def save_options(m: Mods, p: OptionsInput) -> Changed:
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
    return Changed(name=m.save_options(p.profile, p.index, change, p.expect))


# ----------------------------------------------------------------------------- the profile's own history and files
class VersionList(Result):
    versions: tuple[mods_page.VersionRow, ...]


@router.post("/versions", name="mods_versions")
def versions(m: Mods, p: ProfileRef) -> VersionList:
    return VersionList(versions=m.versions(p.profile))


class RestoreParams(ProfileRef):
    path: str  # one of versions' paths


class Restored(Result):
    before: str | None  # the copy of the profile as it was: restoring it undoes this restore


@router.post("/restore_version", name="mods_restore_version")
def restore_version(m: Mods, p: RestoreParams) -> Restored:
    return Restored(before=m.restore_version(p.profile, p.path))


class KindParams(ProfileRef):
    kind: str  # package | native


class Unlisted(Result):
    folders: tuple[mods_page.UnlistedFolder, ...]  # in the profile's folders, loaded by no entry


@router.post("/unlisted", name="mods_unlisted")
def unlisted(m: Mods, p: KindParams) -> Unlisted:
    return Unlisted(folders=m.unlisted(p.profile, p.kind))


class AddParams(KindParams):
    paths: list[str]  # some of unlisted's paths


class Added(Result):
    names: tuple[str, ...]
    loose_dlls: bool  # DLLs not in a folder of their own: the page offers to put them in folders


@router.post("/add_existing", name="mods_add_existing")
def add_existing(m: Mods, p: AddParams) -> Added:
    return Added(**vars(m.add_existing(p.profile, p.kind, p.paths)))


# ----------------------------------------------------------------------------- Edit as text
class TextView(Result):
    text: str  # with LF line ends
    crlf: bool  # the file had CRLF: saving puts them back


@router.post("/text", name="mods_text")
def read_text(m: Mods, p: ProfileRef) -> TextView:
    return TextView(**vars(m.read_text(p.profile)))


class CheckParams(Params):
    text: str


class TextCheck(Result):
    problem: str  # why it does not parse as TOML (the parser's words), "" when it does


@router.post("/check_text", name="mods_check_text")
def check_text(m: Mods, p: CheckParams) -> TextCheck:
    """The parse gate of the editor: pure, nothing is read from disk."""
    return TextCheck(problem=m.check_text(p.text))


class SaveTextParams(ProfileRef):
    text: str
    crlf: bool = False


@router.post("/save_text", name="mods_save_text")
def save_text(m: Mods, p: SaveTextParams) -> Changed:
    """The profile as the player wrote it (a Version is kept first). Errors: invalid_toml (details: why)."""
    m.save_text(p.profile, p.text, p.crlf)
    return Changed()


# ----------------------------------------------------------------------------- the combined parameters
class RebuildParams(ProfileRef):
    combine: bool | None = None  # True/null as the Parameters card says ("stacked": combine them)
    allow: bool = False  # the player allowed the profile's rebuild tool to run (asked when it is not yet)


@router.post("/rebuild", name="mods_rebuild")
def rebuild(m: Mods, p: RebuildParams) -> Started:
    """A job. Errors: rebuild_game_running, rebuild_blocked, nothing_to_rebuild (details: detail), tool_cannot_run,
    busy, and needs_confirmation (details: reason "allow_tool", tool) before a rebuild tool that is not allowed yet
    runs: answer with allow=True."""
    return Started(job_id=m.rebuild(p.profile, p.combine, p.allow))


class ToolInfo(Result):
    label: str
    package: str
    what: str  # what the tool runs
    key: str  # tells another version of the tool


@router.post("/check_allow_tool", name="mods_check_allow_tool")
def check_allow_tool(m: Mods, p: ProfileRef) -> ToolInfo:
    """The rebuild tool the profile would run. Errors: no_tool."""
    return ToolInfo(**vars(m.check_allow_tool(p.profile)))


class AllowParams(ProfileRef):
    expect: str  # the key check_allow_tool gave and the client confirmed


class Allowed(Result):
    ok: bool = True


@router.post("/allow_tool", name="mods_allow_tool")
def allow_tool(m: Mods, p: AllowParams) -> Allowed:
    """Remembered for this version of the tool. Errors: no_tool, stale."""
    m.allow_tool(p.profile, p.expect)
    return Allowed()


class TrimPlan(Result):
    count: int  # rebuild backups beyond the ones kept
    size: int  # bytes
    keep: int


@router.post("/check_trim_backups", name="mods_check_trim_backups")
def check_trim_backups(m: Mods, p: ProfileRef) -> TrimPlan:
    """Errors: nothing_to_trim (details: keep)."""
    return TrimPlan(**vars(m.check_trim_backups(p.profile)))


class TrimParams(ProfileRef):
    expect: int  # the count check_trim_backups gave and the client confirmed


@router.post("/trim_backups", name="mods_trim_backups")
def trim_backups(m: Mods, p: TrimParams) -> Started:
    """A job; its result is {"moved"}. Errors: nothing_to_trim, stale."""
    return Started(job_id=m.trim_backups(p.profile, p.expect))


# ----------------------------------------------------------------------------- the profile's folders
@router.post("/rename_folder", name="mods_rename_folder")
def rename_folder(m: Mods, p: ProfileRef) -> Started:
    """Rename the profile's folder to the profile's name (Undo in Activity). Errors: folder_refused."""
    return Started(job_id=m.rename_folder(p.profile))


class FolderPlan(Result):
    """A change to the profile's folder: the counts say how much changes, refusals why a start would be refused."""

    refusals: tuple[str, ...]
    moves: int
    copies: int
    files: int  # DLL folders only: files moved
    stamp: tuple[int, int] | None
    profiles: int = 0  # split only: the profiles that each get a folder


class StartParams(ProfileRef):
    expect: tuple[int, int] | None  # the stamp the check gave and the client confirmed


@router.post("/check_split_folder", name="mods_check_split_folder")
def check_split_folder(m: Mods, p: ProfileRef) -> FolderPlan:
    """What giving every profile of a crowded folder its own folder would do."""
    return FolderPlan(**vars(m.check_split_folder(p.profile)))


@router.post("/split_folder", name="mods_split_folder")
def split_folder(m: Mods, p: StartParams) -> Started:
    """A job. Errors: cannot_split (details: refusals), stale."""
    return Started(job_id=m.split_folder(p.profile, p.expect))


@router.post("/check_dll_folders", name="mods_check_dll_folders")
def check_dll_folders(m: Mods, p: ProfileRef) -> FolderPlan:
    """What giving each loose DLL mod a folder of its own would do."""
    return FolderPlan(**vars(m.check_dll_folders(p.profile)))


@router.post("/dll_folders", name="mods_dll_folders")
def dll_folders(m: Mods, p: StartParams) -> Started:
    """A job. Errors: cannot_move (details: refusals), stale."""
    return Started(job_id=m.dll_folders(p.profile, p.expect))


class SeamlessPlan(Result):
    kind: str  # move (into the profile) | cleanup (of the game folder)
    folder: str
    files: int
    launcher: str


@router.post("/check_seamless", name="mods_check_seamless")
def check_seamless(m: Mods, p: LaunchRef) -> SeamlessPlan:
    """What of Seamless Co-op sits in the game folder. Errors: busy, nothing_to_do."""
    return SeamlessPlan(**vars(m.check_seamless(p.profile, p.kind, p.source)))


class SeamlessParams(LaunchRef):
    expect: tuple[str, int]  # the (kind, files) check_seamless gave and the client confirmed


@router.post("/seamless", name="mods_seamless")
def seamless(m: Mods, p: SeamlessParams) -> Started:
    """Move Seamless Co-op from the game folder into this profile, or clean up what it left there (the files go to the
    Recycle Bin; the profile's own copy and the settings file in use are never touched). A job; its result is
    {"kind"}. Errors: busy, nothing_to_do, stale."""
    return Started(job_id=m.seamless(p.profile, p.expect, p.kind, p.source))


# ----------------------------------------------------------------------------- me3 settings
class Me3SettingsView(Result):
    savefile: str
    start_online: int  # the three-way ones: 0 me3 default, 1 on, 2 off
    disable_arxan: int
    mem_patch: int
    mem_patch_heap_size: int
    heap_applies: bool  # me3 uses the heap size only with the memory patch on
    heap_shown: bool  # this game has a heap size setting


@router.post("/settings", name="mods_settings")
def settings(m: Mods, p: ProfileRef) -> Me3SettingsView:
    return Me3SettingsView(**vars(m.settings(p.profile)))


class SettingParams(ProfileRef):
    key: str
    value: int | str | None = None  # the three-way ones come as 0 (me3 default) / 1 (on) / 2 (off)
    confirmed: bool = False


class SettingResult(Result):
    changed: bool
    key: str


@router.post("/set_setting", name="mods_set_setting")
def set_setting(m: Mods, p: SettingParams) -> SettingResult:
    """One me3 option of the profile, comments kept. Turning online matchmaking on answers needs_confirmation
    (details: reason "online") until confirmed=True. Errors: unknown_setting, profile_write_failed."""
    got = m.set_setting(p.profile, p.key, p.value, p.confirmed)
    return SettingResult(changed=got.changed, key=got.key)


# ----------------------------------------------------------------------------- the profile itself
class ProfileBlock(Result):
    reason: str  # why it can't be renamed, copied or moved now: "" | no-profile | managed | busy | game-running


@router.post("/profile_block", name="mods_profile_block")
def profile_block(m: Mods, p: LaunchRef) -> ProfileBlock:
    """Why the profile can't be renamed or copied now: no profile, run by an installer, a job, the game running."""
    return ProfileBlock(reason=m.profile_block(p.profile, p.kind, p.source))


class NameParams(LaunchRef):
    name: str


class NameCheck(Result):
    code: str  # "" when the name can be the profile's | no_profile | empty | invalid
    reason: str = ""  # invalid only: why, in plain words


@router.post("/profile_name_check", name="mods_profile_name_check")
def profile_name_check(m: Mods, p: NameParams) -> NameCheck:
    """Reads the profile's folder only."""
    return NameCheck(**vars(m.check_profile_name(p.profile, p.name)))


@router.post("/rename_profile", name="mods_rename_profile")
def rename_profile(m: Mods, p: NameParams) -> Started:
    """Rename the profile (its Undo is in Activity). A job; its result is {"profile": the new path, "name"}. Errors:
    profile_blocked (details: reason), invalid_name (details: code, reason)."""
    return Started(job_id=m.rename_profile(p.profile, p.name, p.kind, p.source))


class DuplicateParams(LaunchRef):
    share: bool | None = None  # the check box: share the game-file mods with the original instead of copying them


@router.post("/duplicate_profile", name="mods_duplicate_profile")
def duplicate_profile(m: Mods, p: DuplicateParams) -> Started:
    """Copy the profile as "<name> copy". A job; its result is {"profile", "name"}. Asks (needs_confirmation, details:
    reason "share") only when its packages could be shared and share is null. Errors: profile_blocked."""
    return Started(job_id=m.duplicate_profile(p.profile, p.share, p.kind, p.source))


@router.post("/check_move_in", name="mods_check_move_in")
def check_move_in(m: Mods, p: LaunchRef) -> FolderPlan:
    """What moving a profile outside Bayle's folder into it would do. Errors: profile_blocked."""
    return FolderPlan(**vars(m.check_move_in(p.profile, p.kind, p.source)))


class StartLaunchParams(LaunchRef):
    expect: tuple[int, int] | None  # the stamp the check gave and the client confirmed


@router.post("/move_in", name="mods_move_in")
def move_in(m: Mods, p: StartLaunchParams) -> Started:
    """Move a profile outside Bayle's folder into it (its Undo is in Activity). A job; its result is {"profile"}.
    Errors: profile_blocked, cannot_move_in (details: refusals), stale."""
    return Started(job_id=m.move_in(p.profile, p.expect, p.kind, p.source))


class DeletePlan(Result):
    name: str
    keeps: str  # the overhaul the launcher installed whose shared files stay ("" when none)
    stamp: tuple[int, int] | None


@router.post("/check_delete_profile", name="mods_check_delete_profile")
def check_delete_profile(m: Mods, p: LaunchRef) -> DeletePlan:
    """What deleting the profile would do (it moves to Deleted profiles; its mod folders stay). Errors: no_profile,
    managed (its installer owns it), busy."""
    return DeletePlan(**vars(m.check_delete_profile(p.profile, p.kind, p.source)))


@router.post("/delete_profile", name="mods_delete_profile")
def delete_profile(m: Mods, p: StartLaunchParams) -> Started:
    """Move the profile to Deleted profiles. A job; its result is {"moved_to"}. Errors: what the check gives, stale."""
    return Started(job_id=m.delete_profile(p.profile, p.expect, p.kind, p.source))
