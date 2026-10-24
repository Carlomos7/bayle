"""The Mods page's operations on the profile as a whole for the HTTP layer, each handed to the session's ModsService:
rebuild the combined parameters (and allow its tool), trim the rebuild backups, fix the profile's folder and the DLLs'
folders, move Seamless Co-op in, the me3 settings, and renaming, copying, deleting and moving in the profile. A plan
is a check (what would change, with a stamp) and a start (with the stamp the client confirmed). See ops/mods.py for
the conventions."""

from __future__ import annotations

from bayle.session.operations import Call, Result, operation
from bayle.session.ops.mods import LaunchRef, ModsJob, ProfileRef, svc


# ----------------------------------------------------------------------------- the combined parameters
class RebuildParams(ProfileRef):
    combine: bool | None = None  # True/null as the Parameters card says ("stacked": combine them)
    allow: bool = False  # the player allowed the profile's rebuild tool to run (asked when it is not yet)


@operation("mods.rebuild", params=RebuildParams, result=ModsJob, kind="command", writes=True)
def rebuild(call: Call, p: RebuildParams) -> ModsJob:
    """A job. Errors: rebuild_game_running, rebuild_blocked, nothing_to_rebuild (details: detail), tool_cannot_run,
    busy, and needs_confirmation (details: reason "allow_tool", tool) before a rebuild tool that is not allowed yet
    runs: answer with allow=True."""
    return ModsJob(job_id=svc(call.session).rebuild(p.profile, p.combine, p.allow))


class ToolInfo(Result):
    label: str
    package: str
    what: str  # what the tool runs
    key: str  # tells another version of the tool


@operation("mods.check_allow_tool", params=ProfileRef, result=ToolInfo)
def check_allow_tool(call: Call, p: ProfileRef) -> ToolInfo:
    """The rebuild tool the profile would run. Errors: no_tool."""
    return ToolInfo(**vars(svc(call.session).check_allow_tool(p.profile)))


class AllowParams(ProfileRef):
    expect: str  # the key check_allow_tool gave and the client confirmed


class Allowed(Result):
    ok: bool = True


@operation("mods.allow_tool", params=AllowParams, result=Allowed, kind="command", writes=True)
def allow_tool(call: Call, p: AllowParams) -> Allowed:
    """Remembered for this version of the tool. Errors: no_tool, stale."""
    svc(call.session).allow_tool(p.profile, p.expect)
    return Allowed()


class TrimPlan(Result):
    count: int  # rebuild backups beyond the ones kept
    size: int  # bytes
    keep: int


@operation("mods.check_trim_backups", params=ProfileRef, result=TrimPlan)
def check_trim_backups(call: Call, p: ProfileRef) -> TrimPlan:
    """Errors: nothing_to_trim (details: keep)."""
    return TrimPlan(**vars(svc(call.session).check_trim_backups(p.profile)))


class TrimParams(ProfileRef):
    expect: int  # the count check_trim_backups gave and the client confirmed


@operation("mods.trim_backups", params=TrimParams, result=ModsJob, kind="command", writes=True)
def trim_backups(call: Call, p: TrimParams) -> ModsJob:
    """A job; its result is {"moved"}. Errors: nothing_to_trim, stale."""
    return ModsJob(job_id=svc(call.session).trim_backups(p.profile, p.expect))


# ----------------------------------------------------------------------------- the profile's folders
@operation("mods.rename_folder", params=ProfileRef, result=ModsJob, kind="command", writes=True)
def rename_folder(call: Call, p: ProfileRef) -> ModsJob:
    """Rename the profile's folder to the profile's name (Undo in Activity). Errors: folder_refused."""
    return ModsJob(job_id=svc(call.session).rename_folder(p.profile))


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


@operation("mods.check_split_folder", params=ProfileRef, result=FolderPlan)
def check_split_folder(call: Call, p: ProfileRef) -> FolderPlan:
    """What giving every profile of a crowded folder its own folder would do."""
    return FolderPlan(**vars(svc(call.session).check_split_folder(p.profile)))


@operation("mods.split_folder", params=StartParams, result=ModsJob, kind="command", writes=True)
def split_folder(call: Call, p: StartParams) -> ModsJob:
    """A job. Errors: cannot_split (details: refusals), stale."""
    return ModsJob(job_id=svc(call.session).split_folder(p.profile, p.expect))


@operation("mods.check_dll_folders", params=ProfileRef, result=FolderPlan)
def check_dll_folders(call: Call, p: ProfileRef) -> FolderPlan:
    """What giving each loose DLL mod a folder of its own would do."""
    return FolderPlan(**vars(svc(call.session).check_dll_folders(p.profile)))


@operation("mods.dll_folders", params=StartParams, result=ModsJob, kind="command", writes=True)
def dll_folders(call: Call, p: StartParams) -> ModsJob:
    """A job. Errors: cannot_move (details: refusals), stale."""
    return ModsJob(job_id=svc(call.session).dll_folders(p.profile, p.expect))


class SeamlessPlan(Result):
    kind: str  # move (into the profile) | cleanup (of the game folder)
    folder: str
    files: int
    launcher: str


@operation("mods.check_seamless", params=LaunchRef, result=SeamlessPlan)
def check_seamless(call: Call, p: LaunchRef) -> SeamlessPlan:
    """What of Seamless Co-op sits in the game folder. Errors: busy, nothing_to_do."""
    return SeamlessPlan(**vars(svc(call.session).check_seamless(p.profile, p.kind, p.source)))


class SeamlessParams(LaunchRef):
    expect: tuple[str, int]  # the (kind, files) check_seamless gave and the client confirmed


@operation("mods.seamless", params=SeamlessParams, result=ModsJob, kind="command", writes=True)
def seamless(call: Call, p: SeamlessParams) -> ModsJob:
    """Move Seamless Co-op from the game folder into this profile, or clean up what it left there (the files go to the
    Recycle Bin; the profile's own copy and the settings file in use are never touched). A job; its result is
    {"kind"}. Errors: busy, nothing_to_do, stale."""
    return ModsJob(job_id=svc(call.session).seamless(p.profile, p.expect, p.kind, p.source))


# ----------------------------------------------------------------------------- me3 settings
class SettingsView(Result):
    savefile: str
    start_online: int  # the three-way ones: 0 me3 default, 1 on, 2 off
    disable_arxan: int
    mem_patch: int
    mem_patch_heap_size: int
    heap_applies: bool  # me3 uses the heap size only with the memory patch on
    heap_shown: bool  # this game has a heap size setting


@operation("mods.settings", params=ProfileRef, result=SettingsView)
def settings(call: Call, p: ProfileRef) -> SettingsView:
    return SettingsView(**vars(svc(call.session).settings(p.profile)))


class SettingParams(ProfileRef):
    key: str
    value: int | str | None = None  # the three-way ones come as 0 (me3 default) / 1 (on) / 2 (off)
    confirmed: bool = False


class SettingResult(Result):
    changed: bool
    key: str


@operation("mods.set_setting", params=SettingParams, result=SettingResult, kind="command", writes=True)
def set_setting(call: Call, p: SettingParams) -> SettingResult:
    """One me3 option of the profile, comments kept. Turning online matchmaking on raises needs_confirmation (details:
    reason "online") until confirmed=True. Errors: unknown_setting, profile_write_failed."""
    got = svc(call.session).set_setting(p.profile, p.key, p.value, p.confirmed)
    return SettingResult(changed=got.changed, key=got.key)


# ----------------------------------------------------------------------------- the profile itself
class ProfileBlock(Result):
    reason: str  # why it can't be renamed, copied or moved now: "" | no-profile | managed | busy | game-running


@operation("mods.profile_block", params=LaunchRef, result=ProfileBlock)
def profile_block(call: Call, p: LaunchRef) -> ProfileBlock:
    """Why the profile can't be renamed or copied now: no profile, run by an installer, a job, the game running."""
    return ProfileBlock(reason=svc(call.session).profile_block(p.profile, p.kind, p.source))


class NameParams(LaunchRef):
    name: str


class NameCheck(Result):
    code: str  # "" when the name can be the profile's | no_profile | empty | invalid
    reason: str = ""  # invalid only: why, in plain words


@operation("mods.profile_name_check", params=NameParams, result=NameCheck)
def profile_name_check(call: Call, p: NameParams) -> NameCheck:
    """Reads the profile's folder only."""
    return NameCheck(**vars(svc(call.session).check_profile_name(p.profile, p.name)))


@operation("mods.rename_profile", params=NameParams, result=ModsJob, kind="command", writes=True)
def rename_profile(call: Call, p: NameParams) -> ModsJob:
    """Rename the profile (its Undo is in Activity). A job; its result is {"profile": the new path, "name"}. Errors:
    profile_blocked (details: reason), invalid_name (details: code, reason)."""
    return ModsJob(job_id=svc(call.session).rename_profile(p.profile, p.name, p.kind, p.source))


class DuplicateParams(LaunchRef):
    share: bool | None = None  # the check box: share the game-file mods with the original instead of copying them


@operation("mods.duplicate_profile", params=DuplicateParams, result=ModsJob, kind="command", writes=True)
def duplicate_profile(call: Call, p: DuplicateParams) -> ModsJob:
    """Copy the profile as "<name> copy". A job; its result is {"profile", "name"}. Asks (needs_confirmation, details:
    reason "share") only when its packages could be shared and share is null. Errors: profile_blocked."""
    return ModsJob(job_id=svc(call.session).duplicate_profile(p.profile, p.share, p.kind, p.source))


@operation("mods.check_move_in", params=LaunchRef, result=FolderPlan)
def check_move_in(call: Call, p: LaunchRef) -> FolderPlan:
    """What moving a profile outside Bayle's folder into it would do. Errors: profile_blocked."""
    return FolderPlan(**vars(svc(call.session).check_move_in(p.profile, p.kind, p.source)))


class StartLaunchParams(LaunchRef):
    expect: tuple[int, int] | None  # the stamp the check gave and the client confirmed


@operation("mods.move_in", params=StartLaunchParams, result=ModsJob, kind="command", writes=True)
def move_in_(call: Call, p: StartLaunchParams) -> ModsJob:
    """Move a profile outside Bayle's folder into it (its Undo is in Activity). A job; its result is {"profile"}.
    Errors: profile_blocked, cannot_move_in (details: refusals), stale."""
    return ModsJob(job_id=svc(call.session).move_in(p.profile, p.expect, p.kind, p.source))


class DeletePlan(Result):
    name: str
    keeps: str  # the overhaul the launcher installed whose shared files stay ("" when none)
    stamp: tuple[int, int] | None


@operation("mods.check_delete_profile", params=LaunchRef, result=DeletePlan)
def check_delete_profile(call: Call, p: LaunchRef) -> DeletePlan:
    """What deleting the profile would do (it moves to Deleted profiles; its mod folders stay). Errors: no_profile,
    managed (its installer owns it), busy."""
    return DeletePlan(**vars(svc(call.session).check_delete_profile(p.profile, p.kind, p.source)))


@operation("mods.delete_profile", params=StartLaunchParams, result=ModsJob, kind="command", writes=True)
def delete_profile(call: Call, p: StartLaunchParams) -> ModsJob:
    """Move the profile to Deleted profiles. A job; its result is {"moved_to"}. Errors: what the check gives, stale."""
    return ModsJob(job_id=svc(call.session).delete_profile(p.profile, p.expect, p.kind, p.source))
