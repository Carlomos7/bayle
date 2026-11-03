"""The Mods page for one engine (the ModsService at the bottom): what the page reads about a profile in one pass and
without writing (the page facts, the Load order scan, the rebuild tool to ask about, the last rebuild that can be
taken back, the overhaul state, whether Seamless Co-op also sits in the game folder), and every change to a profile or
its entries. Facts, codes and jobs only: the Qt presenter (views.mods) turns them into what the page shows. Finishing
an interrupted change (a write) is not part of it: that is mods.recover on the session."""

from __future__ import annotations

import contextlib
import os
import threading
import tomllib
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.adapters.system import logging as run_logging
from bayle.errors import Busy, OperationError
from bayle.modules.coop import service as coop_service
from bayle.modules.games.locate import Locations
from bayle.modules.launch import play as play_service
from bayle.modules.mods import conflicts as mod_overview
from bayle.modules.mods import move_in, profile_edit, profile_mods
from bayle.modules.mods import order as mod_order
from bayle.modules.mods import profile_rename_page as rename_service
from bayle.modules.mods import service as mod_service
from bayle.modules.mods import shared_mods_page as library_service
from bayle.modules.mods.profile import SETTING_TEXT
from bayle.modules.mods.shared_mods import HINT_BYTES
from bayle.work.jobs import JobManager
from bayle.work.runner import run_job_value, run_logged

_TRI = ("start_online", "disable_arxan", "mem_patch")  # 0 me3 default, 1 on, 2 off
_REBUILD_CODES = {
    profile_mods.REBUILD_GAME_RUNNING: "rebuild_game_running",
    profile_mods.REBUILD_BLOCKED: "rebuild_blocked",
    profile_mods.REBUILD_NOTHING: "nothing_to_rebuild",
}
GAME_RUNNING = "game-running"  # profile_block's code beside profile_mods' DELETE_* ones


def stamp(path: str | Path) -> tuple[int, int] | None:
    """A cheap read of a file: a plan is stale once it changed (None when the file is gone)."""
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return st.st_mtime_ns // 1000, st.st_size  # microseconds: nanoseconds pass 2**53 and JSON clients round them


def _unchanged(now: tuple[int, int] | None, expect: Sequence[int] | None) -> bool:
    return now == (tuple(expect) if expect is not None else None)


def run_logged_job(loc: Locations, title: str, log_title: str, body: Callable[[Locations], Any]) -> Any:
    """body(loc) as a logged job of its own (its log file, jobs-index record and undo record: what Activity lists).
    Call it inside a session job; a failure is an OperationError (code and details kept), a stop is Cancelled."""

    def job(_launch: Any, jloc: Locations) -> Any:
        with run_logged(log_title, jloc.game.key):
            return body(jloc)

    return run_job_value(job, loc, title)


@contextlib.contextmanager
def refusing(code: str, **details: Any) -> Iterator[None]:
    """Whatever the layers below raise becomes an OperationError with this code (its text is the message)."""
    try:
        yield
    except OperationError:
        raise
    except Exception as e:
        raise OperationError(code, str(e), details) from e


def launch_for(loc: Locations, profile: str, kind: str = "me3", source: str = ""):
    """The setup the page is about, as the rules about deleting and Seamless Co-op read it."""
    return play_service.LaunchProfile(kind, profile, source=source or None, loc=loc)


def folder_name(profile, entry: dict) -> str:
    """The entry's folder name (a package's folder, a DLL's parent): where the Rename dialog starts; "" without a path."""
    if not entry.get("path"):
        return ""
    folder = profile_edit.resolve(Path(profile), entry["path"])
    return (folder if entry["kind"] == "package" else folder.parent).name


FILES_LIMIT = 2000


def entry_files(profile, entry: dict, limit: int = FILES_LIMIT) -> tuple[list[str], bool]:
    """The files of one entry: a package's folder, relative and in order (at most `limit`; the flag says there were
    more), or the one DLL of a native. Reads only; a folder that is not there lists nothing."""
    if not entry.get("path"):
        return [], False
    target = profile_edit.resolve(Path(profile), entry["path"])
    if entry["kind"] != "package":
        return ([target.name] if target.is_file() else []), False
    out: list[str] = []
    for root, dirs, names in os.walk(target):
        dirs.sort()
        for n in sorted(names):
            if len(out) >= limit:
                return out, True
            out.append((Path(root) / n).relative_to(target).as_posix())
    return out, False


def drop_reasons(profile, kind: str, index: int, *, loc: Locations) -> dict[int, str]:
    """For a drag of entry `index`: why dropping it at each position (0-based among its kind as shown) would be refused,
    "" where it is allowed. The same rules a move applies (mods.order.move), over the profile text read once."""
    prof = Path(profile)
    text = profile_edit.read_text(prof)
    target = mod_order.target(prof, loc)
    shown = mod_order.display_order(prof, text, kind)
    out: dict[int, str] = {}
    for to in range(len(shown)):
        try:
            plan = mod_order.move(prof, text, kind, index, to, target)
            out[to] = plan.problem if plan.text is None and plan.problem else ""
        except Exception as e:
            out[to] = str(e)
    return out


# ----------------------------------------------------------------------------- what the service returns
@dataclass(frozen=True)
class ToolInfo:
    """A mod's rebuild tool: what the player is asked to allow. key tells that it is another version of the tool."""

    label: str
    package: str
    what: str
    key: str


def _tool_info(tool: Any) -> ToolInfo:
    key = tool.approval_key() if hasattr(tool, "approval_key") else tool.label
    return ToolInfo(tool.label, str(tool.package.get("name", "")), tool.describe(), str(key))


@dataclass(frozen=True)
class ModsPageState:
    """The Mods page for one profile. profile is "" (facts None) when none is picked, the file is not there or there
    is no game. rebuild_undo: the newest rebuild's job record that can still be taken back; seamless: "" | "move" |
    "cleanup" (Seamless Co-op also in the game folder); rename_code: why the profile can't be renamed or copied
    whatever is running (a profile_mods.DELETE_* code), or ""; folders: entry -> its folder's name (where the Rename
    dialog starts); closed: the (profile, key) InfoBars the player closed this session."""

    profile: str
    has_profile: bool
    running: bool  # the game runs
    no_profiles: bool  # this game has no profile at all (the page says how to start)
    facts: profile_mods.PageFacts | None = None
    scan: dict | None = None
    tool: ToolInfo | None = None
    rebuild_undo: dict | None = None
    overhaul_on: bool = False
    overhaul: dict | None = None
    leftovers: bool = False
    seamless: str = ""
    rename_code: str = ""
    folders: dict[int, str] | None = None
    closed: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LibraryHint:
    mods: int
    size: int  # bytes wasted by the same Separate copy in several profiles
    enough: bool  # more than the Library is suggested for
    closed: bool  # the player closed the InfoBar for this profile


@dataclass(frozen=True)
class DragTable:
    kind: str
    reasons: dict[int, str]  # target position (0-based among the kind as shown) -> why a drop there is refused, ""


@dataclass(frozen=True)
class RenameFacts:
    ok: bool
    lines: tuple[str, ...]
    refusals: tuple[str, ...]


@dataclass(frozen=True)
class Dependency:
    id: str
    optional: bool = False


@dataclass(frozen=True)
class ModOptions:
    """What the Mod options dialog shows for one entry. init_kind: 0 none, 1 call a function, 2 wait (ms); overlay:
    None when it does not apply, else whether the parameter overlay is set by hand."""

    index: int
    name: str
    kind: str
    enabled: bool
    id: str
    load_after: tuple[Dependency, ...]
    load_before: tuple[Dependency, ...]
    optional: bool
    load_early: bool
    init_kind: int
    init_value: str
    finalizer: str
    others: tuple[str, ...]
    overlay: bool | None
    rebuild_file: str


@dataclass(frozen=True)
class OptionsChange:
    """The Mod options dialog's values to save (natives take optional/load_early/finalizer/init_*; packages the id)."""

    enabled: bool = True
    id: str = ""
    load_after: tuple[Dependency, ...] = ()
    load_before: tuple[Dependency, ...] = ()
    optional: bool = False
    load_early: bool = False
    finalizer: str = ""
    init_kind: int = 0
    init_value: str = ""
    overlay: bool | None = None  # None leaves the overlay as it is
    rebuild_file: str = ""


@dataclass(frozen=True)
class MoveOutcome:
    moved: bool
    name: str
    problem: str = ""  # why me3 would not keep it there (moved is False)
    decided_by: int = -1  # the entry whose options decide ("Edit options" opens it; -1: none)


@dataclass(frozen=True)
class VersionRow:
    path: str
    when: str  # ISO time to the minute
    why: str


@dataclass(frozen=True)
class UnlistedFolder:
    label: str
    path: str


@dataclass(frozen=True)
class Added:
    names: tuple[str, ...]
    loose_dlls: bool  # DLLs not in a folder of their own: the page offers to put them in folders


@dataclass(frozen=True)
class ProfileText:
    text: str  # with LF line ends
    crlf: bool  # the file had CRLF: saving puts them back


@dataclass(frozen=True)
class HolderPlan:
    """Taking out an entry that only points at a folder of mods: needs are the packages whose dependency on it goes."""

    name: str
    needs: tuple[str, ...]
    stamp: tuple[int, int] | None  # of the profile when planned


@dataclass(frozen=True)
class ProfileSettings:
    """The me3 options of the profile; the three-way ones are 0 (me3 default), 1 (on) or 2 (off)."""

    savefile: str
    start_online: int
    disable_arxan: int
    mem_patch: int
    mem_patch_heap_size: int
    heap_applies: bool  # me3 uses the heap size only with the memory patch on
    heap_shown: bool  # this game has a heap size setting


@dataclass(frozen=True)
class SettingChange:
    changed: bool
    key: str
    value: Any  # as written (None: back to me3's default)


@dataclass(frozen=True)
class TrimPlan:
    count: int  # rebuild backups beyond the ones kept
    size: int  # bytes
    keep: int


@dataclass(frozen=True)
class FolderPlan:
    """A change to the profile's folder (split it, give DLLs folders, move in) the client can confirm: the counts say
    how much changes, refusals why it cannot go ahead (a start would be refused)."""

    refusals: tuple[str, ...]
    moves: int
    copies: int
    files: int  # DLL folders only: files moved
    stamp: tuple[int, int] | None
    profiles: int = 0  # split only: the profiles that each get a folder

    @property
    def ok(self) -> bool:
        return not self.refusals


@dataclass(frozen=True)
class SeamlessPlan:
    kind: str  # move (into the profile) | cleanup (of the game folder)
    folder: str
    files: int
    launcher: str


@dataclass(frozen=True)
class NameCheck:
    code: str  # "" | no_profile | empty | invalid
    reason: str = ""  # invalid only: why, in plain words (mods.profile_rename)


@dataclass(frozen=True)
class DeletePlan:
    name: str
    keeps: str  # the overhaul the launcher installed whose shared files stay ("" when none)
    stamp: tuple[int, int] | None


# ----------------------------------------------------------------------------- the engine interface
class ModsService:
    """The Mods page (its facts, the profile's mods, the profile itself) for one engine: jobs is its JobManager,
    locations the current game's Locations (None: no game selected). Returns data and OperationError codes, never
    wording: the Qt page words them.

    Only what a profile lists is touched: a profile is an existing .me3 file and an entry, a version, a folder to add
    or a removal's undo record must be the profile's own (anything else is not_found). A change waits for the running
    job (busy); the long ones are jobs whose id is returned (quiet; their results are dicts, their failures carry a
    code and details). A plan is a check (facts, writes nothing) and a start (with what the client confirmed: stale
    when it changed since); a change that asks only sometimes raises needs_confirmation (details: reason and the
    facts to ask about) until it is sent again confirmed."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations
        self._lock = threading.Lock()
        self._closed: set[tuple[str, str]] = set()

    # ---- the guards
    def _loc(self) -> Locations:
        try:
            loc = self._locations()
        except OperationError:
            loc = None
        if loc is None:
            raise OperationError("no_game", "No game is selected.")
        return loc

    @staticmethod
    def _profile(profile: str | Path) -> Path:
        path = Path(profile) if profile else None
        if path is None or path.suffix.lower() != ".me3" or not path.is_file():
            raise OperationError("not_found", "That profile is not there.", {"profile": str(profile)})
        return path

    def _entry(self, profile: str | Path, index: int, expect: str | None = None) -> dict:
        """The profile's entry at index. Raises not_found (the profile changed since the page was read), stale (expect:
        the name the client chose it by)."""
        entry = next((e for e in mod_service.profile_entries(self._profile(profile)) if e["index"] == index), None)
        if entry is None:
            raise OperationError("not_found", "The profile changed; look again.", {"index": index})
        if expect is not None and entry["name"] != expect:
            raise OperationError("stale", "The profile changed; look again.", {"index": index})
        return entry

    def _idle(self) -> None:
        """A change to a profile waits for the running job (it holds the folder)."""
        if self._jobs.busy:
            raise Busy("Wait for the current job to finish.", {"reason": "job"})

    @staticmethod
    def _fresh(profile: Path, expect: Sequence[int] | None) -> None:
        if not _unchanged(stamp(profile), expect):
            raise OperationError("stale", "The profile changed since you were asked. Ask again.")

    def _start(self, title: str, log_title: str, body: Callable[[Locations], Any]) -> str:
        """body(loc) as a logged job inside a session job (not while the game or another write runs); its id."""
        loc = self._loc()
        return self._jobs.start(lambda _ctx: run_logged_job(loc, title, log_title, body), title=title, quiet=True)

    def _blocked(self, profile: Path, kind: str, source: str) -> str:
        """Why the profile can't be renamed, copied or moved now: "" | a profile_mods DELETE_* code | game-running."""
        loc = self._loc()
        launch = launch_for(loc, str(profile), kind, source)
        code = rename_service.refusal(launch, self._jobs.busy, loc=loc)
        return code or (GAME_RUNNING if self._jobs.game_running else "")

    def _unblocked(self, profile: str | Path, kind: str, source: str) -> Path:
        path = self._profile(profile)
        if code := self._blocked(path, kind, source):
            raise OperationError("profile_blocked", "The profile can't be changed now.", {"reason": code})
        return path

    # ---- the page
    def page(
        self, profile: str | Path = "", kind: str = "me3", source: str = "", no_profiles: bool = False
    ) -> ModsPageState:
        """Reads only. Interrupted changes are put right by the session start-up (the shell), never by a read."""
        running, closed = self._jobs.game_running, self._closed_notices()
        empty = ModsPageState("", False, running, no_profiles, closed=closed)
        try:
            loc = self._loc()
        except OperationError as e:
            if e.code != "no_game":
                raise
            return empty
        prof = Path(profile) if profile else None
        if prof is None or prof.suffix.lower() != ".me3" or not prof.is_file():
            return empty
        launch = launch_for(loc, str(prof), kind, source)
        try:
            seamless = coop_service.game_folder_seamless(launch)
        except Exception:  # a game folder that cannot be read: nothing to offer
            seamless = None
        facts = profile_mods.page_facts(prof, loc=loc)
        try:
            scan = mod_overview.overview(prof, loc=loc)
        except Exception as e:  # a broken profile or record: the page shows what it has
            scan = {"profile": str(prof), "scan": {"error": str(e)}}
        tool = profile_mods.tool_to_offer(prof, loc.game, loc=loc)
        try:
            undo = profile_mods.last_rebuild_undo(prof, self._jobs.store)
        except Exception:
            undo = None
        try:
            on = mod_service.overhaul_preview_on(loc)
            has = mod_service.profile_overhaul(prof, loc=loc) if on else None
            left = bool(mod_service.overhaul_leftovers(prof, loc=loc)) if on else False
        except Exception:  # an overhaul config or record that does not read: no overhaul entries
            on, has, left = False, None, False
        return ModsPageState(
            profile=str(facts.profile),
            has_profile=not facts.error,
            running=running,
            no_profiles=no_profiles,
            facts=facts,
            scan=scan,
            tool=_tool_info(tool) if tool is not None else None,
            rebuild_undo=undo,
            overhaul_on=on,
            overhaul=has,
            leftovers=left,
            seamless=seamless.kind if seamless is not None else "",
            rename_code=profile_mods.delete_refusal(launch, False, loc=loc) or "",
            folders={e["index"]: folder_name(facts.profile, e) for e in facts.entries},
            closed=closed,
        )

    def _closed_notices(self) -> tuple[tuple[str, str], ...]:
        with self._lock:
            return tuple(sorted(self._closed))

    def close_notice(self, profile: str | Path, key: str) -> None:
        """A closed InfoBar stays closed for this profile, for the session (nothing on disk)."""
        with self._lock:
            self._closed.add((str(profile), key))

    def library_hint(self, profile: str | Path) -> LibraryHint:
        """Mods kept as the same Separate copy in several profiles (the disk scan; worked out after the page shows)."""
        mods, size = library_service.duplicates(self._loc())
        with self._lock:
            closed = (str(profile), "library-hint") in self._closed
        return LibraryHint(mods, size, size > HINT_BYTES, closed)

    def drag(self, profile: str | Path, index: int) -> DragTable:
        """Ship the ordering so a client drags without asking again: the refusal for every drop spot of this entry."""
        entry = self._entry(profile, index)
        return DragTable(entry["kind"], drop_reasons(profile, entry["kind"], index, loc=self._loc()))

    # ---- an entry on or off, and its Undo
    def set_enabled(self, profile: str | Path, index: int, enabled: bool, expect: str | None = None) -> str:
        """Switch the entry on or off; its name. Raises not_found, stale, busy, profile_write_failed."""
        self._idle()
        name = self._entry(profile, index, expect)["name"]
        with refusing("profile_write_failed"):
            mod_service.set_mod_options(profile, index, {"enabled": enabled}, loc=self._loc())
        return name

    def undo_change(self, profile: str | Path) -> bool:
        """Put back the copy kept just before the last change to the profile; whether there was one. Raises
        not_found, busy, undo_failed."""
        self._idle()
        path = self._profile(profile)
        with refusing("undo_failed"):
            return profile_mods.undo_last_change(path) is not None

    # ---- removing an entry
    def remove(
        self,
        profile: str | Path,
        index: int,
        name: str,
        delete_folder: bool | None = None,
        confirmed: bool = False,
    ) -> str:
        """Take the entry out of the profile (its folder to the Recycle Bin when asked, or when that is safe and nothing
        else loads from it) as a job; its id. The result is {"name", "undo"}: the record undo_removal takes back.
        name: the entry's name when the player chose it. Unless Undo brings everything back (or confirmed) it raises
        needs_confirmation (details: reason "removal", name, folder, users, merged, can_recycle). Raises not_found,
        stale, busy; the job fails with remove_failed."""
        loc = self._loc()
        plan = profile_mods.removal(profile, self._entry(profile, index, name), loc=loc)
        if not confirmed and not profile_mods.removal_undoable(profile, plan, loc=loc):
            raise OperationError(
                "needs_confirmation",
                "Removing it can't be undone from here.",
                {
                    "reason": "removal",
                    "name": plan.name,
                    "folder": str(plan.folder or ""),
                    "users": list(plan.users),
                    "merged": list(plan.merged),
                    "can_recycle": plan.can_recycle,
                },
            )
        delete = plan.can_recycle if delete_folder is None else delete_folder

        def work(jloc: Locations) -> dict:
            with refusing("remove_failed", name=name):
                out = profile_mods.remove_entry(profile, index, plan, delete_folder=delete, loc=jloc)
            return {"name": name, "undo": out["undo"]}

        return self._start(f"Removing {name}...", f"launcher: remove {name}", work)

    def undo_removal(self, undo: dict[str, Any]) -> str:
        """Take back exactly one removal (the record remove's job returned); the entry's name. Raises not_found (not a
        removal of an existing profile), busy, undo_failed."""
        self._idle()
        if undo.get("type") != "remove":
            raise OperationError("not_found", "That is not a removal.")
        self._profile(undo.get("profile") or "")
        with refusing("undo_failed"):
            profile_mods.undo_removal(undo, loc=self._loc())
        return str(undo.get("name") or "")

    def check_remove_holder(self, profile: str | Path, index: int) -> HolderPlan:
        """An entry that only points at a folder of mods: taking it out changes nothing in the game. Raises not_found."""
        entry = self._entry(profile, index)
        needs = tuple(profile_mods.holder_dependents(profile, entry))
        return HolderPlan(entry["name"], needs, stamp(self._profile(profile)))

    def remove_holder(self, profile: str | Path, index: int, expect: tuple[int, int] | None) -> str:
        """Take the holder out as a job; its id. The result is {"name"}. expect: the stamp check_remove_holder gave.
        Raises not_found, stale, busy; the job fails with remove_failed."""
        entry = self._entry(profile, index)
        self._fresh(self._profile(profile), expect)
        needs = profile_mods.holder_dependents(profile, entry)
        name = entry["name"]

        def work(jloc: Locations) -> dict:
            with refusing("remove_failed", name=name):
                profile_mods.remove_holder(profile, index, entry, needs, loc=jloc)
            return {"name": name}

        return self._start(f"Removing {name}...", f"launcher: remove {name} (a folder of mods)", work)

    # ---- the load order
    def move(self, profile: str | Path, index: int, to: int, expect: str | None = None) -> MoveOutcome:
        """Move the entry to position `to` among its kind as the page shows them. A refusal of me3's rules is not an
        error: moved False, with problem and the entry that decides. Raises not_found, stale, busy, move_failed."""
        self._idle()
        entry = self._entry(profile, index, expect)
        with refusing("move_failed"):
            plan = profile_mods.move_entry(profile, entry["kind"], index, to, loc=self._loc())
        if plan.text is not None:
            return MoveOutcome(True, entry["name"])
        by = next((e["index"] for e in mod_service.profile_entries(profile) if e["name"] == plan.decided_by), -1)
        return MoveOutcome(False, entry["name"], plan.problem, by if plan.decided_by else -1)

    def fix_order(self, profile: str | Path) -> None:
        """Put the mod that must stay last back last. Raises not_found, busy, order_not_fixed."""
        self._idle()
        path = self._profile(profile)
        with refusing("order_not_fixed"):
            problem = mod_order.fix(path, loc=self._loc())
        if problem:
            raise OperationError("order_not_fixed", problem)

    # ---- renaming one mod
    def folder_name(self, profile: str | Path, index: int) -> str:
        """The entry's folder name: where the Rename dialog starts. Raises not_found."""
        return folder_name(self._profile(profile), self._entry(profile, index))

    def files(self, profile: str | Path, index: int) -> tuple[list[str], bool, bool]:
        """The entry's files (see entry_files) and whether it is a native (its one DLL is the main file). Raises
        not_found."""
        entry = self._entry(profile, index)
        listed, more = entry_files(self._profile(profile), entry)
        return listed, more, entry["kind"] != "package"

    def rename_preview(self, profile: str | Path, index: int, name: str) -> RenameFacts:
        """Whether renaming to the name is allowed and what it would change; nothing is written. Raises not_found."""
        self._entry(profile, index)
        try:
            pre = profile_mods.rename_preview(profile, index, name, loc=self._loc())
        except Exception as e:
            return RenameFacts(False, (), (str(e),))
        return RenameFacts(pre.ok, tuple(pre.lines), tuple(pre.refusals))

    def rename(self, profile: str | Path, index: int, name: str, expect: str | None = None) -> str:
        """Rename the mod (its folder, id and everything that names it) as a job; its id. The result is {"name", "to"}.
        Raises not_found, stale, busy; the job fails with rename_failed."""
        old = self._entry(profile, index, expect)["name"]

        def work(jloc: Locations) -> dict:
            with refusing("rename_failed", name=old):
                profile_mods.rename_mod(profile, index, name, loc=jloc)
            return {"name": old, "to": name}

        return self._start(f"Renaming {old}...", f"launcher: rename {old} to {name}", work)

    # ---- Mod options
    def options(self, profile: str | Path, index: int) -> ModOptions:
        """What the Mod options dialog shows for the entry. Raises not_found."""
        entry = self._entry(profile, index)
        facts = profile_mods.options_facts(profile, entry)
        init = entry.get("initializer") or {}
        delay = init.get("delay") if isinstance(init.get("delay"), dict) else None

        def deps(key: str) -> tuple[Dependency, ...]:
            return tuple(Dependency(str(d["id"]), bool(d.get("optional"))) for d in entry.get(key) or [])

        return ModOptions(
            index=index,
            name=entry["name"],
            kind=entry["kind"],
            enabled=entry.get("enabled", True) is not False,
            id=entry.get("id") or "",
            load_after=deps("load_after"),
            load_before=deps("load_before"),
            optional=bool(entry.get("optional")),
            load_early=bool(entry.get("load_early")),
            init_kind=1 if init.get("function") else 2 if delay is not None else 0,
            init_value=str(init.get("function") or (delay or {}).get("ms", "") or ""),
            finalizer=str(entry.get("finalizer") or ""),
            others=facts.others,
            overlay=facts.overlay,
            rebuild_file=facts.rebuild_file,
        )

    def save_options(self, profile: str | Path, index: int, change: OptionsChange, expect: str | None = None) -> str:
        """Save the entry's options; its name. Raises not_found, stale, busy, invalid_wait, options_not_saved."""
        self._idle()
        entry = self._entry(profile, index, expect)
        opts: dict[str, Any] = {
            "enabled": change.enabled,
            "load_after": [{"id": d.id, "optional": d.optional} for d in change.load_after],
            "load_before": [{"id": d.id, "optional": d.optional} for d in change.load_before],
        }
        if entry["kind"] == "package":
            opts["id"] = change.id.strip()
        else:
            value = change.init_value.strip()
            if change.init_kind == 2 and value and not value.isdigit():
                raise OperationError("invalid_wait", "The wait is a number of milliseconds.")
            opts["optional"], opts["load_early"] = change.optional, change.load_early
            opts["finalizer"] = change.finalizer.strip()
            opts["initializer"] = (
                {"function": value}
                if change.init_kind == 1 and value
                else {"delay": {"ms": int(value)}}
                if change.init_kind == 2 and value
                else None
            )
        with refusing("options_not_saved"):
            profile_mods.save_options(
                profile,
                index,
                entry,
                opts,
                loc=self._loc(),
                overlay=change.overlay,
                rebuild_file=change.rebuild_file.strip(),
            )
        return entry["name"]

    # ---- the profile's own history and files
    def versions(self, profile: str | Path) -> tuple[VersionRow, ...]:
        """The copies kept of the profile, newest first. Raises not_found."""
        return tuple(
            VersionRow(str(v["path"]), v["when"].isoformat(timespec="minutes"), str(v.get("why") or ""))
            for v in profile_mods.versions(self._profile(profile))
        )

    def restore_version(self, profile: str | Path, path: str) -> str | None:
        """Put one of versions() back as the profile; the copy of the profile as it was (restoring it undoes this).
        Raises not_found, busy, restore_failed."""
        self._idle()
        if path not in {v.path for v in self.versions(profile)}:
            raise OperationError("not_found", "That earlier copy is no longer there.", {"path": path})
        with refusing("restore_failed"):
            before = profile_mods.restore_version(profile, path)
        return None if before is None else str(before)

    @staticmethod
    def _kind(kind: str) -> str:
        if kind not in ("package", "native"):
            raise OperationError("invalid_params", "Kind is package or native.", {"kind": kind})
        return kind

    def unlisted(self, profile: str | Path, kind: str) -> tuple[UnlistedFolder, ...]:
        """The folders (packages) or DLLs (natives) in the profile no entry loads: what Add existing offers."""
        found = profile_mods.unlisted(self._profile(profile), self._kind(kind))
        return tuple(UnlistedFolder(label, str(path)) for label, path in found)

    def add_existing(self, profile: str | Path, kind: str, paths: Sequence[str]) -> Added:
        """List folders (or DLLs) that already sit in place as entries, last in the load order. Only unlisted() ones.
        Raises not_found, busy, add_failed."""
        self._idle()
        offered = {os.path.normcase(f.path) for f in self.unlisted(profile, kind)}
        for p in paths:
            if os.path.normcase(str(Path(p))) not in offered:
                raise OperationError("not_found", "That folder is not one the profile can add.", {"path": p})
        with refusing("add_failed"):
            names = profile_mods.add_existing(profile, [Path(x) for x in paths], kind, loc=self._loc())
        return Added(tuple(names), kind == "native" and bool(profile_mods.loose_dlls_of(Path(profile))))

    # ---- Edit as text
    def read_text(self, profile: str | Path) -> ProfileText:
        """The profile's text. Raises not_found."""
        try:
            raw = self._profile(profile).read_bytes()
        except OSError:
            raw = b""
        body = raw.decode("utf-8", errors="replace")
        return ProfileText(body.replace("\r\n", "\n"), "\r\n" in body)

    @staticmethod
    def check_text(text: str) -> str:
        """The parse gate of the editor: why the text is not a profile (the parser's words), "" when it is."""
        try:
            tomllib.loads(text)
        except tomllib.TOMLDecodeError as e:
            return str(e)
        return ""

    def save_text(self, profile: str | Path, text: str, crlf: bool = False) -> None:
        """The profile as the player wrote it (a Version is kept first). Raises not_found, busy, invalid_toml (details:
        why), profile_write_failed."""
        self._idle()
        path = self._profile(profile)
        if why := self.check_text(text):
            raise OperationError("invalid_toml", "The text does not parse.", {"why": why})
        with refusing("profile_write_failed"):
            mod_service.save_profile_text(path, text.replace("\n", "\r\n") if crlf else text)

    # ---- the combined parameters
    def rebuild(self, profile: str | Path, combine: bool | None = None, allow: bool = False) -> str:
        """Rebuild (or first combine) the profile's parameters as a job; its id. Raises not_found, rebuild_game_running,
        rebuild_blocked, nothing_to_rebuild (details: detail), tool_cannot_run, busy, and needs_confirmation (details:
        reason "allow_tool", tool) before a rebuild tool that is not allowed yet runs: send it again with allow."""
        path, loc = self._profile(profile), self._loc()
        combine = True if combine else None
        refusal = profile_mods.rebuild_refusal(path, loc=loc, game_running=self._jobs.game_running, combine=combine)
        if refusal is not None:
            code, detail = refusal
            raise OperationError(_REBUILD_CODES[code], "The parameters can't be rebuilt now.", {"detail": detail})
        state = profile_mods.tool_state(path, loc=loc)
        if state.problem:
            raise OperationError(
                "tool_cannot_run", "The rebuild tool cannot run.", {"tool": state.tool.label, "why": state.problem}
            )
        if not state.ready:
            if not allow:
                raise OperationError(
                    "needs_confirmation",
                    "The rebuild tool needs your permission.",
                    {"reason": "allow_tool", "tool": vars(_tool_info(state.tool))},
                )
            profile_mods.allow_tool(state.tool)  # the player confirmed: remembered for this version of the tool
        title = "Combining parameters..." if combine else "Rebuilding combined parameters..."
        job = profile_mods.rebuild_job(path, combine)
        return self._jobs.start(lambda _ctx: run_job_value(job, loc, title), title=title, quiet=True)

    def check_allow_tool(self, profile: str | Path) -> ToolInfo:
        """The rebuild tool the profile would run (what the player is asked to allow). Raises not_found, no_tool."""
        return _tool_info(self._tool(profile))

    def _tool(self, profile: str | Path) -> Any:
        state = profile_mods.tool_state(self._profile(profile), loc=self._loc())
        if state.tool is None:
            raise OperationError("no_tool", "This profile has no rebuild tool.")
        return state.tool

    def allow_tool(self, profile: str | Path, expect: str) -> None:
        """Remember that the player allowed this version of the tool. expect: the key check_allow_tool gave. Raises
        not_found, no_tool, stale."""
        tool = self._tool(profile)
        if _tool_info(tool).key != expect:
            raise OperationError("stale", "The rebuild tool changed since you were asked. Ask again.")
        profile_mods.allow_tool(tool)

    def check_trim_backups(self, profile: str | Path) -> TrimPlan:
        """The rebuild backups beyond the ones kept. Raises not_found, nothing_to_trim (details: keep)."""
        keep = profile_mods.KEEP_TOOL_BACKUPS
        extra = profile_mods.tool_backups_to_trim(self._profile(profile))
        if not extra:
            raise OperationError("nothing_to_trim", "There is nothing to trim.", {"keep": keep})
        return TrimPlan(len(extra), sum(int(b.get("size") or 0) for b in extra), keep)

    def trim_backups(self, profile: str | Path, expect: int) -> str:
        """Move the older rebuild backups to the Recycle Bin as a job; its id. The result is {"moved"}. expect: the
        count check_trim_backups gave. Raises not_found, nothing_to_trim, stale, busy."""
        path = self._profile(profile)
        if self.check_trim_backups(path).count != expect:
            raise OperationError("stale", "The backups changed since you were asked. Ask again.")
        return self._start(
            "Trimming rebuild backups...",
            "launcher: trim rebuild backups",
            lambda _loc: {"moved": len(profile_mods.trim_tool_backups(path))},
        )

    # ---- the profile's folders
    def rename_folder(self, profile: str | Path) -> str:
        """Rename the profile's folder to the profile's name as a job (Undo in Activity); its id. The result is {}.
        Raises not_found, folder_refused, busy."""
        path, loc = self._profile(profile), self._loc()
        if why := rename_service.rename_folder_refusal(path, loc=loc):
            raise OperationError("folder_refused", why)

        def work(jloc: Locations) -> dict:
            with refusing("folder_failed"):
                rename_service.rename_folder(path, loc=jloc)
            return {}

        return self._start("Renaming the folder...", "launcher: fix the profile's folder", work)

    def check_split_folder(self, profile: str | Path) -> FolderPlan:
        """What giving every profile of a crowded folder its own folder would do (profiles, and the moves and copies it takes;
        writes nothing). Raises not_found."""
        path = self._profile(profile)
        plan = rename_service.split_preview(path, loc=self._loc())
        refusals = tuple(plan.refusals) or (() if plan.ok else ("There is nothing to split.",))
        return FolderPlan(refusals, plan.moves, plan.copies, 0, stamp(path), plan.profiles)

    def split_folder(self, profile: str | Path, expect: tuple[int, int] | None) -> str:
        """Split the folder as a job; its id. The result is {}. expect: the stamp check_split_folder gave. Raises
        not_found, cannot_split (details: refusals), stale, busy."""
        path = self._profile(profile)
        plan = self.check_split_folder(path)
        if not plan.ok:
            raise OperationError("cannot_split", " ".join(plan.refusals), {"refusals": list(plan.refusals)})
        self._fresh(path, expect)

        def work(jloc: Locations) -> dict:
            with refusing("folder_failed"):
                rename_service.split_folder(path, loc=jloc)
            return {}

        return self._start("Splitting the folder...", "launcher: fix the profile's folder", work)

    def check_dll_folders(self, profile: str | Path) -> FolderPlan:
        """What giving each loose DLL mod a folder of its own would do (moves: DLLs, files: files moved, copies: files
        copied; writes nothing). Raises not_found."""
        path = self._profile(profile)
        plan = profile_mods.dll_folders_preview(path, loc=self._loc())
        refusals = tuple(plan.refusals) or (() if plan.ok else ("Every DLL is in its own folder.",))
        return FolderPlan(refusals, len(plan.moves), plan.files_copied, plan.files_moved, stamp(path))

    def dll_folders(self, profile: str | Path, expect: tuple[int, int] | None) -> str:
        """Put the loose DLLs in folders as a job; its id. The result is {}. expect: the stamp check_dll_folders
        gave. Raises not_found, cannot_move (details: refusals), stale, busy."""
        path = self._profile(profile)
        plan = self.check_dll_folders(path)
        if not plan.ok:
            raise OperationError("cannot_move", " ".join(plan.refusals), {"refusals": list(plan.refusals)})
        self._fresh(path, expect)

        def work(jloc: Locations) -> dict:
            with refusing("folder_failed"):
                profile_mods.put_dlls_in_folders(path, loc=jloc)
            return {}

        return self._start("Moving the DLLs...", "launcher: fix the profile's folder", work)

    # ---- Seamless Co-op in the game folder
    def _seamless(self, profile: str | Path, kind: str, source: str):
        """The launch and what of Seamless Co-op sits in the game folder (writing: not while a job or the game runs)."""
        path = self._profile(profile)
        if self._jobs.busy:
            raise Busy("Wait for the current job to finish.", {"reason": "job"})
        if self._jobs.game_running:
            raise Busy("The game is running.", {"reason": "game_running"})
        launch = launch_for(self._loc(), str(path), kind, source)
        found = coop_service.game_folder_seamless(launch)
        if found is None:
            raise OperationError("nothing_to_do", "Seamless Co-op is not in the game folder.")
        return launch, found

    def check_seamless(self, profile: str | Path, kind: str = "me3", source: str = "") -> SeamlessPlan:
        """What of Seamless Co-op sits in the game folder: move it into this profile, or clean up what it left there.
        Raises not_found, busy, nothing_to_do."""
        _launch, found = self._seamless(profile, kind, source)
        launcher = found.launcher.name if found.launcher is not None else ""
        return SeamlessPlan(found.kind, str(found.folder), len(found.files), launcher)

    def seamless(self, profile: str | Path, expect: tuple[str, int], kind: str = "me3", source: str = "") -> str:
        """Do what check_seamless offered (the files go to the Recycle Bin; the profile's own copy and the settings file
        in use are never touched) as a job; its id. The result is {"kind"}. expect: its (kind, files). Raises
        not_found, busy, nothing_to_do, stale."""
        launch, found = self._seamless(profile, kind, source)
        if (found.kind, len(found.files)) != tuple(expect):
            raise OperationError("stale", "The game folder changed since you were asked. Ask again.")
        move = found.kind == "move"

        def work(_loc: Locations) -> dict:
            with refusing("seamless_failed"):
                if move:
                    coop_service.move_seamless_into_profile(launch, found, run_logging.log)
                else:
                    coop_service.clean_up_game_folder_seamless(launch, found, run_logging.log)
            return {"kind": found.kind}

        title = "Moving Seamless Co-op..." if move else "Cleaning up the game folder..."
        return self._start(title, "launcher: seamless co-op in the game folder", work)

    # ---- me3 settings
    def settings(self, profile: str | Path) -> ProfileSettings:
        """The profile's me3 options. Raises not_found."""
        vals = mod_service.read_profile_settings(self._profile(profile))

        def tri(value: Any) -> int:
            return {True: 1, False: 2}.get(value, 0)

        return ProfileSettings(
            savefile=str(vals.get("savefile") or ""),
            start_online=tri(vals.get("start_online")),
            disable_arxan=tri(vals.get("disable_arxan")),
            mem_patch=tri(vals.get("mem_patch")),
            mem_patch_heap_size=int(vals.get("mem_patch_heap_size") or 0),
            heap_applies=profile_mods.heap_size_applies(vals),
            heap_shown=bool(getattr(self._loc().game, "me3_heap_setting", True)),
        )

    def set_setting(
        self, profile: str | Path, key: str, value: int | str | None, confirmed: bool = False
    ) -> SettingChange:
        """One me3 option of the profile, comments kept (the three-way ones come as 0 default / 1 on / 2 off). Turning
        online matchmaking on raises needs_confirmation (details: reason "online") until confirmed. Raises not_found,
        busy, unknown_setting, profile_write_failed."""
        self._idle()
        path = self._profile(profile)
        if key not in SETTING_TEXT:
            raise OperationError("unknown_setting", "That is not a profile setting.", {"key": key})
        if key in _TRI:
            value = {1: True, 2: False}.get(int(value or 0))
        elif key == "mem_patch_heap_size":
            value = int(value or 0) or None
        else:
            value = str(value or "").strip() or None
        if profile_mods.setting_needs_confirmation(key, value) and not confirmed:
            raise OperationError(
                "needs_confirmation", "Online matchmaking is a ban risk with modded data.", {"reason": "online"}
            )
        with refusing("profile_write_failed"):
            changed = mod_service.write_profile_setting(path, key, value)
        return SettingChange(changed, key, value)

    # ---- the profile itself
    def profile_block(self, profile: str | Path, kind: str = "me3", source: str = "") -> str:
        """Why the profile can't be renamed, copied or moved now: "" | no-profile | managed (run by its installer) |
        busy | game-running."""
        if not profile or not Path(profile).is_file():
            return profile_mods.DELETE_NO_PROFILE
        return self._blocked(Path(profile), kind, source)

    @staticmethod
    def check_profile_name(profile: str | Path, name: str) -> NameCheck:
        """Whether name can be the profile's new name (reads the profile's folder only)."""
        if not profile or not Path(profile).is_file():
            return NameCheck("no_profile")
        if not name.strip():
            return NameCheck("empty")
        why = rename_service.name_problem(Path(profile), name)
        return NameCheck("invalid", why) if why else NameCheck("")

    def rename_profile(self, profile: str | Path, name: str, kind: str = "me3", source: str = "") -> str:
        """Rename the profile as a job (its Undo is in Activity); its id. The result is {"profile": the new path,
        "name"}. Raises not_found, profile_blocked (details: reason), invalid_name (details: code, reason), busy."""
        path = self._unblocked(profile, kind, source)
        if (got := self.check_profile_name(path, name)).code:
            raise OperationError(
                "invalid_name", got.reason or "Type a new name.", {"code": got.code, "reason": got.reason}
            )

        def work(jloc: Locations) -> dict:
            with refusing("rename_failed", name=name):
                out = rename_service.rename(path, name, loc=jloc)
            run_logging.log(f"done: {path.stem} is now {out['new']}")
            return {"profile": str(out["profile"]), "name": str(out["new"])}

        return self._start(
            f"Renaming {path.stem}...",
            f"launcher: rename profile {path.stem} to {name.strip()}",
            work,
        )

    def duplicate_profile(
        self, profile: str | Path, share: bool | None = None, kind: str = "me3", source: str = ""
    ) -> str:
        """Copy the profile as "<name> copy" as a job; its id. The result is {"profile", "name"}. share: share the
        game-file mods with the original instead of copying them; None asks (needs_confirmation, details: reason
        "share") only when its packages could be shared. Raises not_found, profile_blocked, busy."""
        path = self._unblocked(profile, kind, source)
        if share is None and library_service.separate_copies(path, loc=self._loc()):
            raise OperationError(
                "needs_confirmation", "Its packages can be shared.", {"reason": "share", "name": path.stem}
            )

        def work(jloc: Locations) -> dict:
            with refusing("duplicate_failed"):
                out = rename_service.duplicate(path, loc=jloc, share=bool(share))
            run_logging.log(f"done: {out['name']} is a copy of {path.stem}")
            return {"profile": str(out["profile"]), "name": str(out["name"])}

        return self._start(f"Copying {path.stem}...", f"launcher: duplicate profile {path.stem}", work)

    def check_move_in(self, profile: str | Path, kind: str = "me3", source: str = "") -> FolderPlan:
        """What moving a profile outside Bayle's folder into it would do (moves: mods that move, copies: mods copied
        because other profiles use them). Raises not_found, profile_blocked."""
        path = self._unblocked(profile, kind, source)
        plan = mod_service.move_in_plan(self._loc(), path)
        moved, copied = move_in.counts(plan)
        return FolderPlan(tuple(plan.refusals), moved, copied, 0, stamp(path))

    def move_in(self, profile: str | Path, expect: tuple[int, int] | None, kind: str = "me3", source: str = "") -> str:
        """Move the profile into Bayle's folder as a job (its Undo is in Activity); its id. The result is {"profile"}.
        expect: the stamp check_move_in gave. Raises not_found, profile_blocked, cannot_move_in (details: refusals),
        stale, busy."""
        path = self._unblocked(profile, kind, source)
        plan = self.check_move_in(path, kind, source)
        if not plan.ok:
            raise OperationError("cannot_move_in", " ".join(plan.refusals), {"refusals": list(plan.refusals)})
        self._fresh(path, expect)

        def work(jloc: Locations) -> dict:
            with refusing("move_in_failed"):
                return {"profile": str(mod_service.move_into_launcher_folder(jloc, path)["profile"])}

        return self._start(
            f"Moving {path.stem}...",
            f"launcher: move profile {path.stem} into Bayle's folder",
            work,
        )

    def check_delete_profile(self, profile: str | Path, kind: str = "me3", source: str = "") -> DeletePlan:
        """What deleting the profile would do (it moves to Deleted profiles; its mod folders stay). Raises no_profile,
        managed (its installer owns it), busy, not_found."""
        loc = self._loc()
        launch = launch_for(loc, str(profile), kind, source)
        if code := profile_mods.delete_refusal(launch, self._jobs.busy, loc=loc):
            raise OperationError(code.replace("-", "_"), "That profile can't be deleted now.", {"reason": code})
        path = self._profile(profile)
        return DeletePlan(path.stem, profile_mods.overhaul_to_keep(path, loc=loc), stamp(path))

    def delete_profile(
        self, profile: str | Path, expect: tuple[int, int] | None, kind: str = "me3", source: str = ""
    ) -> str:
        """Move the profile to Deleted profiles as a job; its id. The result is {"moved_to"}. expect: the stamp
        check_delete_profile gave. Raises what the check raises, stale, busy."""
        plan = self.check_delete_profile(profile, kind, source)
        path = self._profile(profile)
        self._fresh(path, expect)
        return self._start(
            f"Deleting profile {plan.name}...",
            f"launcher: delete profile {plan.name}",
            lambda _loc: {"moved_to": str(mod_service.delete_profile(path))},
        )
