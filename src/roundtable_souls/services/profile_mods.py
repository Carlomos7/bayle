"""The Mods page's decisions, below the UI (technical specification §8.6 step 10): what removing an entry touches and
the undo record it leaves, taking out an entry that only points at a folder of mods, the install's undo record, how
many rebuild backups are kept, whether a rebuild tool still needs the user's permission, and the rules for deleting a
profile and changing its me3 options.

Both the Widgets Mods page and the Qt Quick Mods page call these, so the two never disagree. They return facts, not
sentences: the words are the presenter's (ui/pages/mods/presenter.py) and, until it replaces it, the Widgets view's.
services/mods.py keeps install and the plain profile operations; this module only adds the page's decisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from roundtable_souls.game import catalog as games
from roundtable_souls.mods import checks as mod_checks
from roundtable_souls.mods import conflicts as mod_overview
from roundtable_souls.mods import order as mod_order
from roundtable_souls.mods import profile_edit, profile_writer
from roundtable_souls.mods import rebuild as mod_merge
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services.mods import install_mod, profile_entries, set_mod_options, uninstall_mod

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KEEP_TOOL_BACKUPS = 3  # rebuild-tool backups kept when older ones are trimmed: the latest rebuilds stay undoable


# ----------------------------------------------------------------------------- removing an entry
@dataclass(frozen=True)
class Removal:
    """What removing one entry touches. folder: the mod's own folder (a package's folder, a DLL's parent); users:
    the other entries that still load from it (then it stays); merged: the package's files a combined result was
    built from (Play rebuilds before the game starts); can_recycle: the folder may go to the Recycle Bin with it."""

    kind: str
    name: str
    folder: Path | None
    users: tuple[str, ...]
    merged: tuple[str, ...]
    can_recycle: bool


def removal(profile, entry: dict, *, loc: Locations, scan: dict | None = None) -> Removal:
    """What removing entry from profile would touch. scan: a Load order scan of this profile already made
    (mods.conflicts.overview), reused for the merged files when it is for the same profile."""
    prof = Path(profile)
    where = profile_edit.resolve(prof, entry["path"]) if entry.get("path") else None
    folder = (where if entry["kind"] == "package" else where.parent) if where else None
    users: list[str] = []
    if folder is not None:
        for other in profile_entries(prof):
            if other["index"] == entry["index"] or not other.get("path"):
                continue
            path = profile_edit.resolve(prof, other["path"])
            if path == folder or folder in path.parents:
                users.append(other["name"])
    merged = merged_from(prof, entry, loc=loc, scan=scan)
    return Removal(
        kind=entry["kind"],
        name=entry["name"],
        folder=folder,
        users=tuple(users),
        merged=tuple(merged),
        can_recycle=bool(folder is not None and folder.is_dir() and not users),
    )


def merged_from(profile, entry: dict, *, loc: Locations, scan: dict | None = None) -> list[str]:
    """The files of a package that a combined result was built from ([] for natives, other games, or when the
    combined result cannot be read)."""
    prof = Path(profile)
    if entry.get("kind") != "package" or not mod_merge.is_elden_ring(prof):
        return []
    if not scan or scan.get("error") or not mod_checks.same_folder(Path(scan.get("profile") or ""), prof):
        scan = None
    try:
        return list(mod_overview.merged_from(prof, entry["name"], scan, loc=loc))
    except Exception:
        return []


def remove_entry(
    profile,
    index: int,
    plan: Removal,
    *,
    delete_folder: bool,
    loc: Locations,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Remove the entry (run inside a logged job): the entry out of the profile, the folder to the Recycle Bin when
    asked and nothing else loads from it, and the undo record Activity offers ("type": "remove", mods.undo). log
    defaults to the job's log, looked up when called."""
    log = log or run_logging.log
    prof = Path(profile)
    out = uninstall_mod(prof, index, delete_folder=delete_folder, loc=loc)
    run_logging.set_undo(
        {
            "type": "remove",
            "profile": str(prof),
            "name": plan.name,
            "path": out["path"],
            "entry_text": out["entry_text"],
            "where": out["where"],
            "trash": out.get("trash"),
            "merged": bool(plan.merged),
        }
    )
    gone = out.get("trash") and out["trash"].get("kind") == "gone"
    log(
        f"done: removed {plan.name}"
        + (
            ""
            if not out["removed_folder"]
            else "; its folder was deleted (the Recycle Bin could not take it)"
            if gone
            else "; its folder is in the Recycle Bin"
        )
    )
    if delete_folder and not out["removed_folder"] and not plan.users:
        log("warning: the folder was kept (the Recycle Bin did not take it)")
    if plan.merged:
        log(f"note: the merged mods still hold {plan.name}'s files; Play rebuilds them before the game starts")
    return out


# ----------------------------------------------------------------------------- an entry for a folder of mods
def holder_dependents(profile, entry: dict) -> list[str]:
    """The packages that must load after (or before) this entry without it being optional: removing the entry takes
    that setting out of them too."""
    ref = profile_edit.entry_ref(entry).lower()
    return [
        other["name"]
        for other in profile_entries(profile)
        if other["kind"] == "package"
        and any(
            str(dep["id"]).lower() == ref and not dep.get("optional")
            for dep in (other.get("load_after") or []) + (other.get("load_before") or [])
        )
    ]


def remove_holder(profile, index: int, entry: dict, needs: list[str], *, loc: Locations) -> None:
    """Take out an entry that points at a folder of mods (it loaded nothing, so the game does not change): the entry
    goes, the folder and its mods stay, and the dependency on it is taken out of the packages in needs. The
    dependencies go first: the profile writer refuses a profile in which a package must load after an entry that is
    not there.

    TODO(after 3.22-A): one write instead of several (the dependencies, then the entry), as a single ProfileWriter
    edit inside an S3i operation; today a failure between them leaves the profile valid but only half changed."""
    ref = profile_edit.entry_ref(entry).lower()

    def keep(deps: list) -> list:
        return [dep for dep in deps if str(dep["id"]).lower() != ref]

    for other in profile_entries(profile):
        if other["name"] in needs:
            set_mod_options(
                profile,
                other["index"],
                {
                    "load_after": keep(other.get("load_after") or []),
                    "load_before": keep(other.get("load_before") or []),
                },
                loc=loc,
            )
    uninstall_mod(profile, index, delete_folder=False, loc=loc)


# ----------------------------------------------------------------------------- install
def install_and_record(profile, plan: dict, *, loc: Locations) -> dict:
    """Install the planned mod (run inside a logged job) and leave the undo record Activity offers ("install" for a
    new mod, "update" for one replaced; mods.undo)."""
    out = install_mod(Path(profile), plan, overwrite=bool(plan.get("exists")), rebuild=bool(plan.get("merge")), loc=loc)
    run_logging.set_undo(
        {
            "type": "update" if out["update"] else "install",
            "profile": str(profile),
            "name": plan["name"],
            "operation": out["operation"],
            "rebuild": bool(plan.get("merge")),
        }
    )
    return out


# ----------------------------------------------------------------------------- rebuild tools
def tool_backups_to_trim(profile) -> list[dict]:
    """The rebuild tool's backups beyond the newest KEEP_TOOL_BACKUPS (each {folder, size, ...}), oldest last."""
    return list(mod_merge.tool_backups(Path(profile)))[KEEP_TOOL_BACKUPS:]


def trim_tool_backups(profile) -> list:
    """Move the backups beyond the newest KEEP_TOOL_BACKUPS to the Recycle Bin; the ones moved."""
    return list(mod_merge.trim_tool_backups(Path(profile), keep=KEEP_TOOL_BACKUPS))


@dataclass(frozen=True)
class ToolState:
    """The profile's rebuild tool: None when there is none (the launcher's own combine needs no permission);
    problem: why it cannot run; allowed: the user allowed this version of it."""

    tool: Any
    problem: str
    allowed: bool

    @property
    def ready(self) -> bool:
        return self.tool is None or (not self.problem and self.allowed)


def tool_state(profile, *, loc: Locations) -> ToolState:
    tool = mod_merge.find_backend(Path(profile), loc=loc)
    if tool is None:
        return ToolState(None, "", True)
    return ToolState(tool, tool.problem() or "", bool(mod_merge.approved(tool)))


def tool_to_offer(profile, game, *, loc: Locations) -> Any:
    """The rebuild tool to ask about now (Elden Ring only; found, able to run and not allowed yet), else None. A
    tool that cannot be read counts as nothing to ask about."""
    if game is not games.ELDEN_RING:
        return None
    try:
        state = tool_state(profile, loc=loc)
    except Exception:
        return None
    if state.tool is None or state.problem or state.allowed:
        return None
    return state.tool


def allow_tool(tool) -> None:
    """Remember that the user allowed this version of the tool."""
    mod_merge.approve(tool)


# ----------------------------------------------------------------------------- the load order (drag)
def plan_move(profile, kind: str, index: int, to: int, *, loc: Locations) -> mod_order.Move:
    """Where a dragged entry would go (mods.order.move): the new text, or why me3 would not keep it there."""
    prof = Path(profile)
    text = profile_edit.read_text(prof)
    return mod_order.move(prof, text, kind, index, to, mod_order.target(prof, loc))


def move_entry(profile, kind: str, index: int, to: int, *, loc: Locations) -> mod_order.Move:
    """Move the entry to position `to` among its kind as the page shows them, through the profile writer (a .bak,
    a Version, refused when the file changed outside the launcher since it was read). The plan, written or not."""
    prof = Path(profile)
    plan = plan_move(prof, kind, index, to, loc=loc)
    if plan.text is None:
        return plan
    writer = profile_writer.ProfileWriter(prof, loc)
    writer.replace_text(plan.text)
    writer.write("before moving an entry in the load order")
    return plan


# ----------------------------------------------------------------------------- profiles and their me3 options
DELETE_NO_PROFILE = "no-profile"
DELETE_MANAGED = "managed"  # the profile belongs to an installer that manages it: delete it there
DELETE_BUSY = "busy"


def delete_refusal(setup, busy: bool) -> str | None:
    """Why the setup's profile cannot be deleted now (one of the DELETE_* codes), or None."""
    if setup is None or not getattr(setup, "profile", None) or not Path(setup.profile).is_file():
        return DELETE_NO_PROFILE
    if getattr(setup, "kind", "") == "revive":
        return DELETE_MANAGED
    if busy:
        return DELETE_BUSY
    return None


def setting_needs_confirmation(key: str, value) -> bool:
    """Turning online matchmaking on asks first: me3 blocks it by default (a ban risk with modded data)."""
    return key == "start_online" and value is True


def heap_size_applies(settings: dict) -> bool:
    """me3 uses the heap size only with the memory patch on (unset counts as on: me3's default)."""
    return settings.get("mem_patch") is not False
