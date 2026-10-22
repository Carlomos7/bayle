"""The Mods page's operations (reads and the profile operations), on the default registry: its snapshot, the notices
the session remembers, the load-order drag table, and every change to a profile or its entries. Words the player is
asked about come from the presenter (views.mods); decisions and writes are services.profile_mods / services.mods.

Conventions: a profile is its .me3 path, a client passes it in every call (the shell owns which one is current).
A change that always asks is a plan (answering it starts a logged job). A change that asks only sometimes is a
command or job that raises OperationError("needs_confirmation") with the Confirm in details["prompt"] when the
player has not confirmed (confirmed=True on the second call). Refusals are OperationError codes; no one matches text."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.game.locate import Locations
from bayle.mods import undo as mod_undo
from bayle.platform.text import tr
from bayle.services import mods as mod_service
from bayle.services import mods_page
from bayle.services.errors import Cancelled, ErrorInfo, OperationError
from bayle.services.jobs import run_job_result, run_logged
from bayle.session.operations import Call, Params, Result, Session, operation, registry
from bayle.views import load_order
from bayle.views.common import Confirm, prompt_dict
from bayle.views.load_order import LoadOrderPanel
from bayle.views.mods import ModsPresenter, ModsState, Notice, OverhaulMenu


# ----------------------------------------------------------------------------- what the session remembers
class NoticeBook:
    """The InfoBars the player closed (per profile, for this session) and the interrupted changes put right as the
    page opened (the last profile read: another profile has its own lines)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._closed: set[tuple[str, str]] = set()
        self._recovered_for = ""
        self._recovered: list[str] = []

    def close(self, profile: str, key: str) -> None:
        with self._lock:
            self._closed.add((profile, key))

    def closed(self) -> frozenset[tuple[str, str]]:
        with self._lock:
            return frozenset(self._closed)

    def recover(self, profile: str, lines: list[str]) -> None:
        with self._lock:
            if profile != self._recovered_for:
                self._recovered_for, self._recovered = profile, []
            self._recovered += lines

    def recovered(self, profile: str) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._recovered) if profile == self._recovered_for else ()


def book(session: Session) -> NoticeBook:
    return session.service("mods_notices", NoticeBook)


# ----------------------------------------------------------------------------- params
class ProfileRef(Params):
    profile: str  # the .me3 path


class LaunchRef(ProfileRef):
    """The profile as the setup the shell launches: kind "me3" or "manifest" (an overhaul installer's), and its source."""

    kind: str = "me3"
    source: str = ""


class ModsScope(Params):
    profile: str = ""  # "" = none picked
    kind: str = "me3"
    source: str = ""
    no_profiles: bool = False  # this game has no profile at all (the page says how to start)


class EntryRef(ProfileRef):
    index: int  # the entry's block index in the profile


class NoticeRef(ProfileRef):
    key: str


# ----------------------------------------------------------------------------- the page
@dataclass(frozen=True)
class RebuildUndo:
    id: str  # the job whose undo this is (Undo rebuild goes through activity.undo)
    label: str


@dataclass(frozen=True)
class OverhaulInfo:
    label: str
    short_label: str
    legacy: bool  # its own installer set it up
    takeover: bool
    removable: bool


@dataclass(frozen=True)
class ModsView:
    """The Mods page for one profile: what the presenter shows, the Load order panel (every clash; a client cuts the
    list), the entries (for the options and rename dialogs) and what the header menu needs."""

    profile: str  # the profile read ("" when none)
    has_profile: bool
    state: ModsState
    load_order: LoadOrderPanel
    entries: tuple[dict[str, Any], ...]
    configs: dict[int, tuple[str, ...]]
    rebuild_undo: RebuildUndo | None
    overhaul: OverhaulMenu
    overhaul_info: OverhaulInfo | None
    outside: bool  # not in Bayle's folder: it can be moved in
    folders: dict[int, str]  # entry -> its folder's name (the Rename dialog starts from it)
    rename_code: str = ""  # profile_mods.DELETE_* : why it can't be renamed, copied or moved whatever is running
    tool_label: str = ""  # the rebuild tool waiting for the player's permission ("" when none)
    # the profile's folder: "misnamed" or "crowded" when it can be fixed (mods.rename_folder, mods.split_folder)
    folder_kind: str = ""


def _overhaul_info(has: dict | None) -> OverhaulInfo | None:
    if not has:
        return None
    return OverhaulInfo(
        label=str(has["label"]),
        short_label=str(has.get("short_label") or has["label"]),
        legacy=bool(has.get("legacy")),
        takeover=bool(has.get("takeover")),
        removable=bool(has.get("removable", True)),
    )


@registry.page("mods", scope=ModsScope, view=ModsView)
def snapshot(
    session: Session, profile: str = "", kind: str = "me3", source: str = "", no_profiles: bool = False
) -> ModsView:
    """Reads only. Finishing an interrupted change is mods.recover, which the client runs first."""
    pres = ModsPresenter()
    running = session.jobs.game_running
    if not profile or not Path(profile).is_file():
        state = pres.page(None, game_running=running, no_profiles=no_profiles)
        return ModsView(
            profile="",
            has_profile=False,
            state=state,
            load_order=load_order.panel(None, True),
            entries=(),
            configs={},
            rebuild_undo=None,
            overhaul=pres.overhaul_menu(False, None, False),
            overhaul_info=None,
            outside=False,
            folders={},
        )
    loc = session.locations()
    notes = book(session)
    got = mods_page.read(profile, loc=loc, launch=mods_page.launch_for(loc, profile, kind, source))
    state = pres.page(
        got.facts,
        got.scan,
        game_running=running,
        tool_to_allow=got.tool,
        recovered=notes.recovered(profile),
        seamless=got.seamless,
        no_profiles=no_profiles,
        closed=notes.closed(),
    )
    rec = got.rebuild_undo
    undo = RebuildUndo(str(rec.get("id") or ""), tr(mod_undo.label(rec.get("undo")))) if rec else None
    scan = got.scan if load_order.same_profile(got.scan, got.facts.profile) else None
    return ModsView(
        profile=str(got.facts.profile),
        has_profile=not got.facts.error,
        state=state,
        load_order=load_order.panel(scan, True),
        entries=got.facts.entries,
        configs=got.facts.configs,
        rebuild_undo=undo,
        overhaul=pres.overhaul_menu(got.overhaul_on, got.overhaul, got.leftovers),
        overhaul_info=_overhaul_info(got.overhaul),
        outside=got.facts.outside,
        folders={e["index"]: mods_page.folder_name(got.facts.profile, e) for e in got.facts.entries},
        rename_code=got.rename_code,
        tool_label=got.tool.label if got.tool is not None else "",
        folder_kind=got.facts.folder.kind,
    )


class Recovered(Result):
    lines: list[str]


@operation("mods.recover", params=ProfileRef, result=Recovered, kind="command", writes=True)
def recover(call: Call, p: ProfileRef) -> Recovered:
    """Finish or undo an install, update or removal in the profile's folder that was interrupted, and remember the
    lines for the page's notice. Nothing is looked at while a job holds the folder."""
    if call.session.jobs.busy:
        return Recovered(lines=[])
    lines = mod_service.recover_interrupted(p.profile, timeout=0.5)
    book(call.session).recover(p.profile, list(lines))
    return Recovered(lines=list(lines))


class Closed(Result):
    key: str


@operation("mods.close_notice", params=NoticeRef, result=Closed, kind="command")
def close_notice(call: Call, p: NoticeRef) -> Closed:
    """A closed InfoBar stays closed for this profile, for the session (nothing on disk)."""
    book(call.session).close(p.profile, p.key)
    return Closed(key=p.key)


class LibraryHint(Result):
    mods: int
    size: int
    notice: Notice | None  # the InfoBar, None when there is nothing to say or the player closed it


@operation("mods.library_hint", params=ProfileRef, result=LibraryHint)
def library_hint(call: Call, p: ProfileRef) -> LibraryHint:
    """Mods kept as the same Separate copy in several profiles (the disk scan; worked out after the page shows)."""
    from bayle.services import shared_mods as library_service

    mods, size = library_service.duplicates(call.session.locations())
    notice = ModsPresenter().library_hint((mods, size), p.profile, book(call.session).closed())
    return LibraryHint(mods=mods, size=size, notice=notice)


# ----------------------------------------------------------------------------- the drag
class DragTable(Result):
    kind: str
    reasons: dict[
        int, str
    ]  # target position (0-based among the kind as shown) -> why a drop there is refused, "" if not


def entry_of(profile: str, index: int) -> dict:
    """The profile's entry at index, or OperationError not_found (the profile changed since the page was read)."""
    entry = next((e for e in mod_service.profile_entries(profile) if e["index"] == index), None)
    if entry is None:
        raise OperationError("not_found", tr("The profile changed; look again."), {"index": index})
    return entry


@operation("mods.drag", params=EntryRef, result=DragTable)
def drag(call: Call, p: EntryRef) -> DragTable:
    """Ship the ordering so a client drags without asking again: the refusal for every drop spot of this entry."""
    entry = entry_of(p.profile, p.index)
    reasons = mods_page.drop_reasons(p.profile, entry["kind"], p.index, loc=call.session.locations())
    return DragTable(kind=entry["kind"], reasons=reasons)


# ----------------------------------------------------------------------------- helpers shared by the writes
def idle(session: Session) -> None:
    """A change to a profile waits for the running job (it holds the folder); Busy carries the reason."""
    if session.jobs.busy:
        raise OperationError("busy", tr("Wait for the current job to finish."))


def needs_confirmation(words: Confirm) -> OperationError:
    """The second call (confirmed=True) goes ahead; the first says what to ask."""
    return OperationError("needs_confirmation", words.title, {"prompt": prompt_dict(words)})


@contextlib.contextmanager
def refusing(code: str) -> Iterator[None]:
    """Whatever the service raises is the player's to be told: an OperationError with this code and its words."""
    try:
        yield
    except OperationError:
        raise
    except Exception as e:
        raise OperationError(code, str(e)) from e


def run_logged_job(loc: Locations, title: str, log_title: str, body: Callable[[Locations], Any]) -> Any:
    """body(loc) as an old-style logged job: its own log file, jobs-index record and undo record (what Activity
    lists). Call it inside a session job; a failure is an OperationError, a stop is Cancelled."""

    def job(_launch: Any, jloc: Locations) -> Any:
        with run_logged(log_title, jloc.game.key):
            return body(jloc)

    done = run_job_result(job, None, loc, title)
    if done.state == "done":
        return done.result
    if done.state == "cancelled":
        raise Cancelled()
    err = done.error or ErrorInfo("failed", "Failed.")
    raise OperationError(err.code, err.message, err.details)


def start_logged(
    session: Session, title: str, log_title: str, body: Callable[[Locations], Any], quiet: bool = False
) -> str:
    """For a plan's run: start body as a session job that is also an old-style logged one. Returns the job id. The
    job's result is body's return value (a Result model or JSON-clean data)."""
    loc = session.locations()
    return session.start(lambda _ctx: run_logged_job(loc, title, log_title, body), title=title, quiet=quiet)


def stamp(profile: str) -> object:
    """A cheap read of the profile a plan was made from: the plan is stale once the file changed."""
    try:
        st = Path(profile).stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class Changed(Result):
    """A command that wrote the profile: the host's other views read it again, and Undo restores the version before."""

    note: str  # the line for the host's log
    name: str = ""


class Done(Result):
    note: str = ""
