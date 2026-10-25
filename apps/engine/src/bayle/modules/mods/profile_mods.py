"""The Mods page's decisions, below the UI (technical specification §8.6 step 10): what removing an entry touches and
the undo record it leaves, taking out an entry that only points at a folder of mods, the install's undo record, how
many rebuild backups are kept, whether a rebuild tool still needs the user's permission, and the rules for deleting a
profile and changing its me3 options.

Both the Widgets Mods page and the Qt Quick Mods page call these, so the two never disagree. They return facts, not
sentences: the words are the presenter's (views/mods.py) and, until it replaces it, the Widgets view's.
modules/mods/service.py keeps install and the plain profile operations; this module only adds the page's decisions."""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bayle.adapters.system import logging as run_logging
from bayle.adapters.system.threads import assert_not_ui_thread
from bayle.modules.games import catalog as games
from bayle.modules.launch import game_checks
from bayle.modules.mods import checks as mod_checks
from bayle.modules.mods import configs as mod_configs
from bayle.modules.mods import conflicts as mod_overview
from bayle.modules.mods import dll_folders, folder_check, move_in, profile_edit, profile_writer, shared_mods
from bayle.modules.mods import history as mod_history
from bayle.modules.mods import install as mod_install
from bayle.modules.mods import models as mod_models
from bayle.modules.mods import order as mod_order
from bayle.modules.mods import rebuild as mod_merge
from bayle.modules.mods import remove as mod_remove
from bayle.modules.mods import rename as mod_rename
from bayle.modules.mods import shared_mods_page as shared_service
from bayle.modules.mods import undo as mod_undo
from bayle.modules.mods.overhaul_manifest import launcher_installed
from bayle.modules.mods.service import (
    install_mod,
    profile_entries,
    profile_overhaul,
    set_mod_options,
    uninstall_mod,
)
from bayle.work import runner as jobs

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

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


def removal_undoable(profile, plan: Removal, *, loc: Locations) -> bool:
    """Whether Remove may skip its confirm because Undo brings everything back: not when another entry or profile
    keeps the folder, not in a profile with an overhaul (its installer manages entries), and not when the folder
    would be deleted for good (no Recycle Bin)."""
    from bayle.adapters.filesystem import trash

    if plan.users or profile_overhaul(profile, loc=loc) is not None:
        return False
    return not plan.can_recycle or trash.available()


def undo_removal(undo: dict, *, loc: Locations, log: Callable[[str], None] | None = None) -> str:
    """Take back exactly one removal (the record remove_entry returned): the entry where it was, with later edits to
    the profile kept, and the folder from the Recycle Bin. Raises mods.models.UndoError, touching nothing, when the
    profile or the bin no longer allow it."""

    mod_undo.check_removed(undo)
    return mod_undo.run(undo, log or (lambda _s: None), loc=loc)


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
    out["undo"] = {
        "type": "remove",
        "profile": str(prof),
        "name": plan.name,
        "path": out["path"],
        "entry_text": out["entry_text"],
        "where": out["where"],
        "trash": out.get("trash"),
        "merged": bool(plan.merged),
    }
    run_logging.set_undo(out["undo"])
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


# ----------------------------------------------------------------------------- renaming a mod
def rename_preview(profile, index: int, new_name: str, *, loc: Locations) -> mod_rename.RenamePreview:
    """What renaming the entry's folder and id to new_name does, with every refusal (mods.rename.preview)."""
    return mod_rename.preview(Path(profile), index, new_name, loc=loc)


def rename_mod(profile, index: int, new_name: str, *, loc: Locations, log: Callable[[str], None] | None = None) -> dict:
    """Rename (run inside a logged job): the folder, the entry and everything that names it as one operation, and the
    undo record Activity offers ("type": "rename", mods.undo). Raises ModError with the reasons when it is refused."""
    log = log or run_logging.log
    pre = mod_rename.preview(Path(profile), index, new_name, loc=loc)
    if not pre.ok:
        raise mod_models.ModError(" ".join(pre.refusals) or "Nothing to rename.")
    out = mod_rename.apply(pre, loc=loc, log=log)
    run_logging.set_undo(
        {"type": "rename", "profile": out["profile"], "name": out["name"], "operation": out["operation"]}
    )
    log(f"done: renamed {out['name']} to {out['new']}")
    log("note: the merged mods are rebuilt before the next Play")
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
    goes, the folder and its mods stay, and the dependency on it is taken out of the packages in needs, in one
    profile write (mods.remove.remove_holder)."""
    mod_remove.remove_holder(Path(profile), index, profile_edit.entry_ref(entry), needs, loc=loc)


# ----------------------------------------------------------------------------- install
def install_and_record(profile, plan: dict, *, loc: Locations) -> dict:
    """Install the planned mod (run inside a logged job) and leave the undo record Activity offers ("install" for a
    new mod, "update" for one replaced; mods.undo). A new version of a Shared mod goes into the Library instead
    (plan["library_choice"] "here" or "everywhere"); "share" shares the new package with the identical copies in
    other profiles."""
    facts = plan.get("library") or {}
    choice = plan.get("library_choice") or ""
    if facts.get("shared") and facts.get("blocked"):
        raise shared_service.Error(f"{facts['shared']['name']} is Shared; use a separate copy before installing this.")
    if facts.get("shared"):
        try:
            out = shared_mods.update(
                Path(profile),
                facts["shared"]["index"],
                Path(plan["root"]),
                everywhere=choice == "everywhere",
                loc=loc,
            )
            run_logging.log(f"updated Shared mod {facts['shared']['name']} in {', '.join(out['profiles'])}")
        finally:
            if plan.get("staging"):
                shutil.rmtree(plan["staging"], ignore_errors=True)
        out = {**out, "update": True}
        run_logging.set_undo(
            {"type": "library-update", "profile": str(profile), "name": plan["name"], "operation": out["operation"]}
        )
        return out
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
    if choice == "share" and facts.get("identical"):
        more = _share_with_twins(Path(profile), plan, facts["identical"], loc=loc)
        if more:  # the install and the sharing are one job: one Undo takes back both
            first = {
                "type": "update" if out["update"] else "install",
                "profile": str(profile),
                "name": plan["name"],
                "operation": out["operation"],
                "rebuild": bool(plan.get("merge")),
            }
            run_logging.set_undo(shared_service.chain(plan["name"], first, *more))
    return out


def _share_with_twins(profile: Path, plan: dict, others: list[str], *, loc: Locations) -> list[dict]:
    """The mod just installed becomes Shared, and the other profiles' identical Separate copies are switched to it. A
    failure here leaves the install as it is (Separate), and is logged. Returns the undo records of what was shared."""
    undos: list[dict] = []
    try:
        index = next(
            e["index"]
            for e in profile_edit.entries(profile)
            if e["kind"] == "package" and e["path"] and Path(e["path"]).name.lower() == Path(plan["dest"]).name.lower()
        )
        done = shared_mods.share(profile, [index], loc=loc)
        undos.append(shared_service.undo_of("library-share", done))
        name = done["shared"][0].lower()
        twins = {
            c.profile: True
            for c in shared_mods.separate_copies(loc)
            if c.profile.stem in others and c.name.lower() == name
        }
        if twins:
            undos.append(
                shared_service.undo_of("library-use", shared_mods.use_in(name, done["versions"][0], twins, loc=loc))
            )
    except Exception as e:  # the install itself succeeded
        run_logging.log(f"warning: could not share {plan['name']} with the other profiles: {e}")
    return undos


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
    assert_not_ui_thread("profile_mods.tool_to_offer")
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


def delete_refusal(launch, busy: bool, *, loc: Locations) -> str | None:
    """Why the setup's profile cannot be deleted now (one of the DELETE_* codes), or None. A profile belongs to an
    installer that manages it when an overhaul's own installer made the setup (the overhaul configs' [recognise]
    data: its manifest is there and the launcher did not install it), whether the setup was picked as the .me3 or
    through the installer's manifest. A setup the launcher installed can be deleted (overhaul_to_keep)."""
    if launch is None or not getattr(launch, "profile", None) or not Path(launch.profile).is_file():
        return DELETE_NO_PROFILE
    if getattr(launch, "kind", "") == "manifest" and not _launcher_manifest(Path(launch.source)):
        return DELETE_MANAGED
    has = profile_overhaul(launch.profile, loc=loc)
    if has is not None and has["legacy"]:
        return DELETE_MANAGED
    if busy:
        return DELETE_BUSY
    return None


def _launcher_manifest(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return False
    return isinstance(data, dict) and launcher_installed(data)


def overhaul_to_keep(profile, *, loc: Locations) -> str:
    """The label of an overhaul the launcher installed in the profile (its shared files stay when the profile is
    deleted), or ""."""
    has = profile_overhaul(profile, loc=loc)
    return has["label"] if has is not None and not has["legacy"] else ""


def setting_needs_confirmation(key: str, value) -> bool:
    """Turning online matchmaking on asks first: me3 blocks it by default (a ban risk with modded data)."""
    return key == "start_online" and value is True


def heap_size_applies(settings: dict) -> bool:
    """me3 uses the heap size only with the memory patch on (unset counts as on: me3's default)."""
    return settings.get("mem_patch") is not False


# ----------------------------------------------------------------------------- what the page shows, read in one pass
@dataclass(frozen=True)
class PageFacts:
    """Everything the Mods page shows about one profile, read from disk at once (run it off the UI thread); the
    presenter turns it into rows and words. Indexes are the profile's block indexes."""

    profile: Path
    entries: tuple[dict, ...]
    display: dict[str, tuple[int, ...]]  # kind -> indexes in the order the page shows (mods.order.display_order)
    problems: dict[int, tuple[str, ...]]  # what makes me3 refuse or skip an entry (mods.checks.entry_problems)
    loads_nothing: tuple[int, ...]  # entries for a folder of mods or the profile folder (shown as a line, not a row)
    stays_last: tuple[int, ...]  # the locked rows
    missing: tuple[int, ...]  # the folder or DLL is not there
    empty: dict[int, str]  # package folders with no game files of their own: "empty" or "no-game-folders"
    configs: dict[int, tuple[str, ...]]  # a DLL's config files (found beside it or attached)
    not_loaded: dict[str, int]  # kind -> mod folders (or DLLs) in the profile no entry loads
    error: str = ""  # why the profile could not be read ("" when it was)
    online_with: str = ""  # the package whose parameters the profile goes online with (game_checks.online_risk)
    fingerprint: game_checks.Fingerprint | None = None  # the parameters the game will use (co-op partners compare)
    regulation: str = games.REGULATION  # the game's parameters file name
    folder: folder_check.FolderCheck = (
        folder_check.FolderCheck()
    )  # whether the profile's folder is named and used right
    loose_dlls: tuple[int, ...] = ()  # DLL entries not in a folder of their own (mods.dll_folders)
    shared: dict[int, int] = field(default_factory=dict)  # entry -> profiles using that Shared mod (the Library)
    can_share: tuple[int, ...] = ()  # Separate packages that can be shared
    library_used: bool = False  # some profile uses a Shared mod: Separate rows say so
    outside: bool = False  # the profile is not in Bayle's folder (it can be moved in)


def page_facts(profile, *, loc: Locations, settings=None) -> PageFacts:
    """The page's facts for profile. settings: the launcher settings (attached config files); None reads them."""
    assert_not_ui_thread("profile_mods.page_facts")

    prof = Path(profile)
    empty_facts = PageFacts(prof, (), {"package": (), "native": ()}, {}, (), (), (), {}, {}, {})
    try:
        text = profile_edit.read_text(prof)
        entries = profile_entries(prof)
        tree = mod_checks.package_tree(prof, entries)
        problems = mod_checks.entry_problems(prof, entries)
        folders = mod_checks.folder_overview(prof, entries, tree)
    except (OSError, ValueError) as e:
        return PageFacts(**{**empty_facts.__dict__, "error": str(e)})
    display = {
        kind: tuple(r["index"] for r in mod_order.display_order(prof, text, kind)) for kind in ("package", "native")
    }
    try:
        tgt = mod_order.target(prof, loc)
    except Exception:
        tgt = None
    if settings is None:
        from bayle.modules import ports

        settings = ports.load_settings()
    missing, empty, configs = [], {}, {}
    for e in entries:
        where = profile_edit.resolve(prof, e["path"]) if e.get("path") else None
        if where is None or not where.exists():
            missing.append(e["index"])
            continue
        node = tree.get(e["index"])
        if node and node["folder"].is_dir() and not node["own_files"] and not node["holder"]:
            empty[e["index"]] = "empty" if not any(node["folder"].iterdir()) else "no-game-folders"
        if e["kind"] == "native":
            files = mod_configs.files_for(settings, where)
            if files:
                configs[e["index"]] = tuple(Path(f["path"]).name for f in files)
    pk, nt = folders.get("packages") or {}, folders.get("natives") or {}
    try:
        shared, can_share, library_used = shared_mods.page_info(loc, prof, entries)
    except OSError:
        shared, can_share, library_used = {}, (), False
    return PageFacts(
        profile=prof,
        entries=tuple(entries),
        display=display,
        problems={i: tuple(p) for i, p in problems.items() if p},
        loads_nothing=tuple(mod_checks.loads_nothing(prof, entries, tree)),
        stays_last=tuple(sorted(mod_order.stays_last_entries(prof, text, tgt))),
        missing=tuple(missing),
        empty=empty,
        configs=configs,
        not_loaded={"package": len(pk.get("unlisted") or []), "native": len(nt.get("unlisted") or [])},
        online_with=risk.source if (risk := game_checks.online_risk(prof, loc)) is not None else "",
        fingerprint=game_checks.regulation_fingerprint(prof, loc),
        regulation=loc.game.regulation,
        folder=_folder_check(prof, loc),
        loose_dlls=tuple(sorted(i for idx in loose_dlls_of(prof).values() for i in idx)),
        shared=shared,
        can_share=can_share,
        library_used=library_used,
        outside=_outside(prof, loc),
    )


def _outside(profile: Path, loc: Locations) -> bool:
    try:
        return move_in.outside(profile, loc)
    except OSError:
        return False


def _folder_check(profile: Path, loc: Locations) -> folder_check.FolderCheck:
    try:
        return folder_check.check(profile, loc)
    except OSError, ValueError:
        return folder_check.FolderCheck()


def loose_dlls_of(profile: Path) -> dict[Path, list[int]]:
    try:
        return dll_folders.loose(profile)
    except OSError, ValueError:
        return {}


def dll_folders_preview(profile: Path, *, loc: Locations) -> dll_folders.Plan:
    return dll_folders.preview(profile, loc)


def put_dlls_in_folders(profile: Path, *, loc: Locations) -> dict:
    """Give every loose DLL mod a folder of its own (mods.dll_folders). Raises dll_folders.DllFolderError."""
    out = dll_folders.move(profile, loc, run_logging.log)
    out["undo"] = {
        "type": dll_folders.KIND,
        "profile": out["profile"],
        "name": out["name"],
        "operation": out["operation"],
    }
    run_logging.set_undo(out["undo"])
    return out


# ----------------------------------------------------------------------------- rebuilding the combined parameters
REBUILD_GAME_RUNNING = "game-running"
REBUILD_BLOCKED = "blocked"
REBUILD_NOTHING = "nothing"


def rebuild_refusal(
    profile, *, loc: Locations, game_running: bool, combine: bool | None = None
) -> tuple[str, str] | None:
    """Why the combined parameters cannot be rebuilt now: (one of the REBUILD_* codes, the detail), or None."""
    prof = Path(profile)
    if game_running:
        return REBUILD_GAME_RUNNING, ""
    blocked = mod_merge.setup_problem(prof, loc=loc)
    if blocked:
        return REBUILD_BLOCKED, str(blocked)
    tool = mod_merge.find_backend(prof, loc=loc)
    health = mod_merge.health(prof, loc=loc)
    if tool is None and not (health.get("combine") or health.get("can_combine") or combine):
        return REBUILD_NOTHING, ""
    return None


def rebuild_uses_tool(profile, *, loc: Locations) -> bool:
    """A rebuild tool (or the launcher's own combine already set up) does it, rather than a first combine."""
    prof = Path(profile)
    return mod_merge.find_backend(prof, loc=loc) is not None or bool(mod_merge.health(prof, loc=loc).get("combine"))


def rebuild_job(profile, combine: bool | None = None):
    """The logged job that rebuilds (or combines) the parameters and leaves the rebuild's undo record."""
    prof = Path(profile)

    def job(_launch, loc):
        with jobs.run_logged("launcher: rebuild combined parameters", loc.game.key):
            out = mod_merge.rebuild(prof, run_logging.log, combine=combine, loc=loc)
            run_logging.set_undo(out.get("undo"))
            run_logging.log(f"done: combined parameters rebuilt by {out['backend']}; {out['profile_note']}")

    return job


def last_rebuild_undo(profile, store: run_logging.JobStore | None = None) -> dict | None:
    """The newest finished rebuild of this profile that can still be taken back (its job record), or None."""
    assert_not_ui_thread("profile_mods.last_rebuild_undo")

    prof = Path(profile)
    for rec in run_logging.read_jobs_from(store):
        undo = rec.get("undo") or {}
        if undo.get("type") != "rebuild" or rec.get("outcome") not in ("done", "warnings"):
            continue
        if not mod_checks.same_folder(Path(undo.get("profile") or ""), prof):
            continue
        return rec if mod_undo.available(undo) else None
    return None


# ----------------------------------------------------------------------------- the profile's own history
def undo_last_change(profile) -> Path | None:
    """Put back the copy kept just before the last change to the profile (mods.history); the copy of the profile as
    it was (so this can be undone too), or None when there is no copy."""

    prof = Path(profile)
    copy = mod_history.latest(prof)
    return mod_history.restore(prof, copy) if copy is not None else None


# ----------------------------------------------------------------------------- Mod options
@dataclass(frozen=True)
class OptionsFacts:
    """What the Mod options dialog offers for one entry: the other entries it can depend on (same kind; a package is
    named by its id), and for an Elden Ring package whether it is the parameter overlay (the mod that must stay last,
    set by hand) with its rebuild-tool file; overlay None when that does not apply."""

    others: tuple[str, ...]
    overlay: bool | None
    rebuild_file: str


def options_facts(profile, entry: dict) -> OptionsFacts:
    prof = Path(profile)
    others = tuple(
        profile_edit.entry_ref(e)
        for e in profile_entries(prof)
        if e["index"] != entry["index"] and e["kind"] == entry["kind"] and (e["kind"] == "native" or e.get("id"))
    )
    folder = profile_edit.resolve(prof, entry["path"]) if entry.get("path") else None
    overlay, rebuild_file = None, ""
    if entry["kind"] == "package" and folder is not None and mod_merge.is_elden_ring(prof):
        mark = mod_merge.overlay_mark(prof)
        overlay = mark is not None and mod_checks.same_folder(mark["package"], folder)
        rebuild_file = str(mark["rebuild"]) if overlay and mark and mark["rebuild"] else ""
    return OptionsFacts(others, overlay, rebuild_file)


def save_options(
    profile, index: int, entry: dict, opts: dict, *, loc: Locations, overlay: bool | None = None, rebuild_file: str = ""
) -> None:
    """Write the entry's me3 options (opts: the keys set_mod_options takes) and, for a package where it applies, the
    parameter overlay set by hand (overlay True/False; None leaves it as it is)."""
    prof = Path(profile)
    if overlay is not None:
        facts = options_facts(prof, entry)
        if facts.overlay is not None and (overlay != facts.overlay or rebuild_file != facts.rebuild_file):
            folder = profile_edit.resolve(prof, entry["path"])
            mod_merge.set_overlay_override(
                prof, folder if overlay else None, Path(rebuild_file) if overlay and rebuild_file else None
            )
    set_mod_options(prof, index, opts, loc=loc)


# ----------------------------------------------------------------------------- folders no entry loads
def unlisted(profile, kind: str) -> list[tuple[str, Path]]:
    """The mod folders (packages) or DLLs (natives) in the profile no entry loads: (label relative to their root,
    path), for Add existing."""
    prof = Path(profile)
    entries = profile_entries(prof)
    overview = mod_checks.folder_overview(prof, entries)
    part = overview.get("packages" if kind == "package" else "natives") or {}
    root = part.get("root")
    out = []
    for f in part.get("unlisted") or []:
        try:
            label = Path(f).relative_to(root).as_posix() if root else str(f)
        except ValueError:
            label = str(f)
        out.append((label, Path(f)))
    return out


def add_existing(profile, paths: list[Path], kind: str, *, loc: Locations) -> list[str]:
    """List folders (or DLLs) that already sit in place as entries, last in the load order; the names added."""

    out = mod_install.add_existing(Path(profile), list(paths), kind=kind, loc=loc)
    return [r.get("id") or Path(r["path"]).name for r in out["entries"]]


# ----------------------------------------------------------------------------- versions
def versions(profile) -> list[dict]:
    """The copies kept of the profile, newest first: {path, when, why} (mods.history)."""

    return mod_history.versions(Path(profile))


def restore_version(profile, copy) -> Path | None:
    """Put a copy back as the profile; the copy of the profile as it was (so the restore can be undone)."""

    return mod_history.restore(Path(profile), Path(copy))
