"""The Mods page's operations on the profile as a whole: rebuild the combined parameters (and allow its tool), trim
the rebuild backups, fix the profile's folder and the DLLs' folders, move Seamless Co-op in, the me3 settings, and
renaming, copying, deleting and moving in the profile. See ops/mods.py for the conventions."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from bayle.mods import move_in
from bayle.platform import logging as run_logging
from bayle.platform.text import tr
from bayle.services import coop as coop_service
from bayle.services import mods as mod_service
from bayle.services import mods_page, profile_mods
from bayle.services import profile_rename as rename_service
from bayle.services import shared_mods as library_service
from bayle.services.errors import OperationError
from bayle.services.jobs import run_job_result
from bayle.session.operations import Call, Result, Session, operation
from bayle.session.ops.mods import (
    Done,
    LaunchRef,
    ProfileRef,
    idle,
    needs_confirmation,
    refusing,
    run_logged_job,
    stamp,
    start_logged,
)
from bayle.session.plans import Proposal
from bayle.views.common import Refusal
from bayle.views.mods import ModsPresenter

# ----------------------------------------------------------------------------- the combined parameters
_REBUILD_CODES = {
    profile_mods.REBUILD_GAME_RUNNING: "rebuild_game_running",
    profile_mods.REBUILD_BLOCKED: "rebuild_blocked",
    profile_mods.REBUILD_NOTHING: "nothing_to_rebuild",
}


class RebuildParams(ProfileRef):
    combine: bool | None = None  # True/None as the Parameters card says ("stacked": combine them)
    allow: bool = False  # the player allowed the profile's rebuild tool to run (asked when it is not yet)
    confirmed: bool = False  # sent along with allow when the question was answered


def _check_rebuild(call: Call, p: RebuildParams) -> None:
    session, loc = call.session, call.session.locations()
    combine = True if p.combine else None
    refusal = profile_mods.rebuild_refusal(p.profile, loc=loc, game_running=session.jobs.game_running, combine=combine)
    if refusal is not None:
        code, detail = refusal
        raise OperationError(_REBUILD_CODES[code], ModsPresenter.rebuild_refusal(code, detail), {"detail": detail})
    state = profile_mods.tool_state(p.profile, loc=loc)
    if state.problem:
        raise OperationError(
            "tool_cannot_run", tr("{tool} cannot run: {why}").format(tool=state.tool.label, why=state.problem)
        )
    if not state.ready:
        if not p.allow:
            raise needs_confirmation(ModsPresenter().tool(state.tool))
        profile_mods.allow_tool(state.tool)  # the player confirmed: remembered for this version of the tool


def _rebuild_title(call: Call, p: RebuildParams) -> str:
    uses_tool = profile_mods.rebuild_uses_tool(p.profile, loc=call.session.locations())
    return tr("Rebuilding combined parameters...") if uses_tool else tr("Combining parameters...")


@operation(
    "mods.rebuild",
    params=RebuildParams,
    result=Done,
    kind="job",
    writes=True,
    title=_rebuild_title,
    check=_check_rebuild,
)
def rebuild(call: Call, p: RebuildParams) -> Done:
    """Rebuild (or first combine) the profile's parameters. Raises needs_confirmation before a rebuild tool that is
    not allowed yet runs; answer with allow=True."""
    job = profile_mods.rebuild_job(p.profile, True if p.combine else None)
    done = run_job_result(job, None, call.session.locations(), _rebuild_title(call, p))
    if done.state != "done":
        raise OperationError(
            done.error.code if done.error else "failed", done.error.message if done.error else "Failed."
        )
    return Done(note="rebuilt")


class Allowed(Result):
    tool: str


@operation("mods.allow_tool", params=ProfileRef, result=Allowed, kind="plan", writes=True)
def allow_tool(call: Call, p: ProfileRef) -> Proposal | Refusal:
    """The InfoBar's Allow: what the tool runs, then remembered once the player confirms."""
    state = profile_mods.tool_state(p.profile, loc=call.session.locations())
    if state.tool is None:
        return Refusal(tr("Nothing to allow"), tr("This profile has no rebuild tool."))
    words = dataclasses.replace(ModsPresenter().tool(state.tool), apply=tr("Allow"))

    def run(_answer: Any) -> None:
        profile_mods.allow_tool(state.tool)

    return Proposal(words, run)


class Trimmed(Result):
    moved: int


@operation("mods.trim_backups", params=ProfileRef, result=Trimmed, kind="plan", writes=True)
def trim_backups(call: Call, p: ProfileRef) -> Proposal | Refusal:
    extra = profile_mods.tool_backups_to_trim(p.profile)
    if not extra:
        keep = profile_mods.KEEP_TOOL_BACKUPS
        return Refusal(
            tr("Nothing to trim"), tr("Nothing to trim. {n} or fewer backups are kept.").format(n=keep), info=True
        )

    def run(_answer: Any) -> str:
        return start_logged(
            call.session,
            tr("Trimming rebuild backups..."),
            "launcher: trim rebuild backups",
            lambda _loc: Trimmed(moved=len(profile_mods.trim_tool_backups(p.profile))).model_dump(),
            quiet=True,
        )

    return Proposal(ModsPresenter().trim(extra), run)


# ----------------------------------------------------------------------------- the profile's folders
def _check_rename_folder(call: Call, p: ProfileRef) -> None:
    why = rename_service.rename_folder_refusal(Path(p.profile), loc=call.session.locations())
    if why:
        raise OperationError("folder_refused", why)


@operation(
    "mods.rename_folder",
    params=ProfileRef,
    result=Done,
    kind="job",
    writes=True,
    title=lambda _c, _p: tr("Renaming the folder..."),
    check=_check_rename_folder,
)
def rename_folder(call: Call, p: ProfileRef) -> Done:
    """Rename the profile's folder to the profile's name (Undo in Activity)."""
    run_logged_job(
        call.session.locations(),
        tr("Renaming the folder..."),
        "launcher: fix the profile's folder",
        lambda loc: rename_service.rename_folder(Path(p.profile), loc=loc),
    )
    return Done(note="renamed the folder")


@operation("mods.split_folder", params=ProfileRef, result=Done, kind="plan", writes=True)
def split_folder(call: Call, p: ProfileRef) -> Proposal | Refusal:
    """Give every profile of a crowded folder its own folder."""
    old = Path(p.profile)
    plan = rename_service.split_preview(old, loc=call.session.locations())
    if not plan.ok:
        return Refusal(tr("Folder not split"), " ".join(plan.refusals))

    def work(loc: Any) -> dict:
        rename_service.split_folder(old, loc=loc)
        return Done(note="split the folder").model_dump()

    def run(_answer: Any) -> str:
        return start_logged(call.session, tr("Splitting the folder..."), "launcher: fix the profile's folder", work)

    return Proposal(
        ModsPresenter.split_confirm(plan.profiles, plan.copies, plan.moves), run, stale=lambda: stamp(p.profile)
    )


@operation("mods.dll_folders", params=ProfileRef, result=Done, kind="plan", writes=True)
def dll_folders(call: Call, p: ProfileRef) -> Proposal | Refusal:
    """Give each loose DLL mod a folder of its own."""
    old = Path(p.profile)
    plan = profile_mods.dll_folders_preview(old, loc=call.session.locations())
    if not plan.ok:
        return Refusal(tr("DLLs not moved"), " ".join(plan.refusals) or tr("Every DLL is in its own folder."))

    def work(loc: Any) -> dict:
        profile_mods.put_dlls_in_folders(old, loc=loc)
        return Done(note="moved the DLLs").model_dump()

    def run(_answer: Any) -> str:
        return start_logged(call.session, tr("Moving the DLLs..."), "launcher: fix the profile's folder", work)

    return Proposal(
        ModsPresenter.dll_folders_confirm(len(plan.moves), plan.files_moved, plan.files_copied),
        run,
        stale=lambda: stamp(p.profile),
    )


@operation("mods.seamless", params=LaunchRef, result=Done, kind="plan", writes=True)
def seamless(call: Call, p: LaunchRef) -> Proposal | Refusal:
    """Move Seamless Co-op from the game folder into this profile, or clean up what it left there (the files go to
    the Recycle Bin; the profile's own copy and the settings file in use are never touched)."""
    session = call.session
    if session.jobs.busy:
        return Refusal(tr("Not now"), tr("Wait for the current job to finish."))
    if session.jobs.game_running:
        return Refusal(tr("Not now"), tr("Close the game first. It has these files open."))
    launch = mods_page.launch_for(session.locations(), p.profile, p.kind, p.source)
    found = coop_service.game_folder_seamless(launch)
    if found is None:
        return Refusal(tr("Nothing to do"), tr("Seamless Co-op is not in the game folder."))
    move = found.kind == "move"
    changes = ModsPresenter.seamless_changes(
        move, found.folder, len(found.files), found.launcher.name if found.launcher is not None else ""
    )

    def work(_loc: Any) -> dict:
        if move:
            coop_service.move_seamless_into_profile(launch, found, run_logging.log)
        else:
            coop_service.clean_up_game_folder_seamless(launch, found, run_logging.log)
        return Done(note="moved" if move else "cleaned up").model_dump()

    def run(_answer: Any) -> str:
        title = tr("Moving Seamless Co-op...") if move else tr("Cleaning up the game folder...")
        return start_logged(session, title, "launcher: seamless co-op in the game folder", work)

    return Proposal(ModsPresenter.seamless_confirm(move, changes), run)


# ----------------------------------------------------------------------------- me3 settings
_TRI = ("start_online", "disable_arxan", "mem_patch")  # 0 me3 default, 1 on, 2 off


class SettingsView(Result):
    savefile: str
    start_online: int
    disable_arxan: int
    mem_patch: int
    mem_patch_heap_size: int
    heap_applies: bool  # me3 uses the heap size only with the memory patch on
    heap_shown: bool  # this game has a heap size setting


@operation("mods.settings", params=ProfileRef, result=SettingsView)
def settings(call: Call, p: ProfileRef) -> SettingsView:
    vals = mod_service.read_profile_settings(p.profile)

    def tri(value: Any) -> int:
        return {True: 1, False: 2}.get(value, 0)

    return SettingsView(
        savefile=str(vals.get("savefile") or ""),
        start_online=tri(vals.get("start_online")),
        disable_arxan=tri(vals.get("disable_arxan")),
        mem_patch=tri(vals.get("mem_patch")),
        mem_patch_heap_size=int(vals.get("mem_patch_heap_size") or 0),
        heap_applies=profile_mods.heap_size_applies(vals),
        heap_shown=bool(getattr(call.session.locations().game, "me3_heap_setting", True)),
    )


class SettingParams(ProfileRef):
    key: str
    value: int | str | None = None  # the three-way ones come as 0 (me3 default) / 1 (on) / 2 (off)
    confirmed: bool = False


class SettingResult(Result):
    changed: bool
    key: str
    note: str = ""


@operation("mods.set_setting", params=SettingParams, result=SettingResult, kind="command", writes=True)
def set_setting(call: Call, p: SettingParams) -> SettingResult:
    """One me3 option of the profile, comments kept. Turning online matchmaking on raises needs_confirmation (a ban
    risk with modded data) until confirmed=True."""
    from bayle.mods.profile import SETTING_TEXT

    idle(call.session)
    value: Any = p.value
    if p.key not in SETTING_TEXT:
        raise OperationError("unknown_setting", tr("That is not a profile setting."), {"key": p.key})
    if p.key in _TRI:
        value = {1: True, 2: False}.get(int(value or 0))
    elif p.key == "mem_patch_heap_size":
        value = int(value or 0) or None
    else:
        value = str(value or "").strip() or None
    if profile_mods.setting_needs_confirmation(p.key, value) and not p.confirmed:
        raise needs_confirmation(ModsPresenter().online())
    with refusing("profile_write_failed"):
        changed = mod_service.write_profile_setting(p.profile, p.key, value)
    shown = value if value not in (None, "") else "me3 default"
    return SettingResult(changed=changed, key=p.key, note=f"profile: {p.key} = {shown}")


# ----------------------------------------------------------------------------- the profile itself
class ProfileBlock(Result):
    reason: str  # why it can't be renamed, copied or moved now ("" when it can)


def _block(session: Session, p: LaunchRef) -> str:
    if not p.profile or not Path(p.profile).is_file():
        return tr("Pick a profile first.")
    launch = mods_page.launch_for(session.locations(), p.profile, p.kind, p.source)
    code = rename_service.refusal(launch, session.jobs.busy, loc=session.locations())
    return ModsPresenter().rename_block(code, Path(p.profile).stem, session.jobs.game_running)


@operation("mods.profile_block", params=LaunchRef, result=ProfileBlock)
def profile_block(call: Call, p: LaunchRef) -> ProfileBlock:
    """Why the profile can't be renamed or copied now: no profile, run by an installer, a job, the game running."""
    return ProfileBlock(reason=_block(call.session, p))


class NameParams(LaunchRef):
    name: str


class NameCheck(Result):
    problem: str  # why the name can't be the profile's new name ("" when it can)


def _name_problem(p: ProfileRef, name: str) -> str:
    if not p.profile or not Path(p.profile).is_file():
        return tr("Pick a profile first.")
    if not name.strip():
        return tr("Type a new name.")
    return rename_service.name_problem(Path(p.profile), name) or ""


@operation("mods.profile_name_check", params=NameParams, result=NameCheck)
def profile_name_check(call: Call, p: NameParams) -> NameCheck:
    """Reads the profile's folder only."""
    return NameCheck(problem=_name_problem(p, p.name))


class ProfileRenamed(Result):
    profile: str  # the profile's new path
    name: str


def _check_rename_profile(call: Call, p: NameParams) -> None:
    if block := _block(call.session, p):
        raise OperationError("profile_blocked", block)
    if why := _name_problem(p, p.name):
        raise OperationError("invalid_name", why)


@operation(
    "mods.rename_profile",
    params=NameParams,
    result=ProfileRenamed,
    kind="job",
    writes=True,
    title=lambda _c, p: tr("Renaming {name}...").format(name=Path(p.profile).stem),
    check=_check_rename_profile,
)
def rename_profile(call: Call, p: NameParams) -> ProfileRenamed:
    """Rename the profile (its Undo is in Activity)."""
    old = Path(p.profile)

    def work(loc: Any) -> dict:
        out = rename_service.rename(old, p.name, loc=loc)
        run_logging.log(f"done: {old.stem} is now {out['new']}")
        return out

    out = run_logged_job(
        call.session.locations(),
        tr("Renaming {name}...").format(name=old.stem),
        f"launcher: rename profile {old.stem} to {p.name.strip()}",
        work,
    )
    return ProfileRenamed(profile=str(out["profile"]), name=str(out["new"]))


class DuplicateParams(LaunchRef):
    share: bool | None = None  # the check box: share the game-file mods with the original instead of copying them
    confirmed: bool = False


class ProfileCopied(Result):
    profile: str
    name: str


def _check_duplicate(call: Call, p: DuplicateParams) -> None:
    if block := _block(call.session, p):
        raise OperationError("profile_blocked", block)
    old = Path(p.profile)
    if p.share is None and library_service.separate_copies(old, loc=call.session.locations()):
        raise needs_confirmation(
            ModsPresenter().duplicate_confirm(old.stem)
        )  # packages can be shared: ask, never force


@operation(
    "mods.duplicate_profile",
    params=DuplicateParams,
    result=ProfileCopied,
    kind="job",
    writes=True,
    title=lambda _c, p: tr("Copying {name}...").format(name=Path(p.profile).stem),
    check=_check_duplicate,
)
def duplicate_profile(call: Call, p: DuplicateParams) -> ProfileCopied:
    """Copy the profile as "<name> copy". Asks (needs_confirmation) only when its packages could be shared."""
    old = Path(p.profile)

    def work(loc: Any) -> dict:
        out = rename_service.duplicate(old, loc=loc, share=bool(p.share))
        run_logging.log(f"done: {out['name']} is a copy of {old.stem}")
        return out

    out = run_logged_job(
        call.session.locations(),
        tr("Copying {name}...").format(name=old.stem),
        f"launcher: duplicate profile {old.stem}",
        work,
    )
    return ProfileCopied(profile=str(out["profile"]), name=str(out["name"]))


class ProfileMoved(Result):
    profile: str


@operation("mods.move_in", params=LaunchRef, result=ProfileMoved, kind="plan", writes=True)
def move_in_(call: Call, p: LaunchRef) -> Proposal | Refusal:
    """Move a profile outside Bayle's folder into it (its Undo is in Activity)."""
    if block := _block(call.session, p):
        return Refusal(tr("Not moved"), block)
    old, loc = Path(p.profile), call.session.locations()
    plan = mod_service.move_in_plan(loc, old)
    if not plan.ok:
        return Refusal(tr("Not moved"), " ".join(plan.refusals))
    words = ModsPresenter().move_in_confirm(old.stem, old.parent.name, *move_in.counts(plan))

    def work(jloc: Any) -> dict:
        return ProfileMoved(profile=str(mod_service.move_into_launcher_folder(jloc, old)["profile"])).model_dump()

    def run(_answer: Any) -> str:
        title = tr("Moving {name}...").format(name=old.stem)
        return start_logged(call.session, title, f"launcher: move profile {old.stem} into Bayle's folder", work)

    return Proposal(words, run, stale=lambda: stamp(p.profile))


class Deleted(Result):
    moved_to: str  # where the profile went (Deleted profiles)


@operation("mods.delete_profile", params=LaunchRef, result=Deleted, kind="plan", writes=True)
def delete_profile(call: Call, p: LaunchRef) -> Proposal | Refusal:
    """Move the profile to Deleted profiles (its mod folders stay)."""
    session, pres = call.session, ModsPresenter()
    loc = session.locations()
    launch = mods_page.launch_for(loc, p.profile, p.kind, p.source)
    refusal = pres.delete_refusal(
        profile_mods.delete_refusal(launch, session.jobs.busy, loc=loc), Path(p.profile).stem if p.profile else ""
    )
    if refusal is not None:
        return refusal
    kept = profile_mods.overhaul_to_keep(p.profile, loc=loc)
    name = Path(p.profile).stem

    def run(_answer: Any) -> str:
        return start_logged(
            session,
            tr("Deleting profile {name}...").format(name=name),
            f"launcher: delete profile {name}",
            lambda _loc: Deleted(moved_to=str(mod_service.delete_profile(p.profile))).model_dump(),
            quiet=True,
        )

    return Proposal(pres.delete_profile(p.profile, kept), run, stale=lambda: stamp(p.profile))
