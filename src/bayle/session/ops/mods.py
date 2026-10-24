"""The Mods page's operations for the HTTP layer, each handed straight to the session's ModsService
(services.mods_page): the page's snapshot, the notices the session remembers, the load-order drag table, and (in
mods_entries and mods_profile) every change to a profile or its entries. A plan is a check (what would change, with a
stamp) and a start (with the stamp the client confirmed); the long writes are jobs whose id is returned. A change
that asks only sometimes raises OperationError("needs_confirmation") with the reason and the facts in details until
it is sent again confirmed. Refusals are OperationError codes; the client words what it gets. Temporary: the Qt page
calls the service itself.

Conventions: a profile is its .me3 path, a client passes it in every call (the shell owns which one is current)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bayle.errors import Busy, OperationError
from bayle.game.locate import Locations
from bayle.services import mods as mod_service
from bayle.services import mods_page
from bayle.services.mods_page import ModsPageState, ModsService, run_logged_job, stamp
from bayle.session.operations import Call, Params, Result, Session, operation, registry

__all__ = ["run_logged_job", "stamp"]  # the ops of mods_install, mods_library and mods_overhaul still use these


def _none() -> ModsService:
    raise OperationError("no_mods_service", "This session has no Mods page.")


def svc(session: Session) -> ModsService:
    return session.service("mods", _none)


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


class Done(Result):
    note: str = ""


class ModsJob(Result):
    job_id: str


class Changed(Result):
    """A command that wrote the profile: the host's other views read it again, and Undo restores the version before."""

    name: str = ""


@registry.page("mods", scope=ModsScope, view=ModsPageState)
def snapshot(
    session: Session, profile: str = "", kind: str = "me3", source: str = "", no_profiles: bool = False
) -> ModsPageState:
    return svc(session).page(profile, kind, source, no_profiles)


class Closed(Result):
    key: str


@operation("mods.close_notice", params=NoticeRef, result=Closed, kind="command")
def close_notice(call: Call, p: NoticeRef) -> Closed:
    svc(call.session).close_notice(p.profile, p.key)
    return Closed(key=p.key)


class LibraryHint(Result):
    mods: int
    size: int
    enough: bool  # more than the Library is suggested for
    closed: bool  # the player closed the InfoBar for this profile


@operation("mods.library_hint", params=ProfileRef, result=LibraryHint)
def library_hint(call: Call, p: ProfileRef) -> LibraryHint:
    """Mods kept as the same Separate copy in several profiles (the disk scan; worked out after the page shows)."""
    return LibraryHint(**vars(svc(call.session).library_hint(p.profile)))


class DragTable(Result):
    kind: str
    reasons: dict[
        int, str
    ]  # target position (0-based among the kind as shown) -> why a drop there is refused, "" if not


@operation("mods.drag", params=EntryRef, result=DragTable)
def drag(call: Call, p: EntryRef) -> DragTable:
    """Ship the ordering so a client drags without asking again: the refusal for every drop spot of this entry."""
    return DragTable(**vars(svc(call.session).drag(p.profile, p.index)))


# ----------------------------------------------------------------------------- helpers the other Mods ops still use
def idle(session: Session) -> None:
    """A change to a profile waits for the running job (it holds the folder)."""
    if session.jobs.busy:
        raise Busy("Wait for the current job to finish.", {"reason": "job"})


def entry_of(profile: str, index: int) -> dict:
    """The profile's entry at index, or OperationError not_found (the profile changed since the page was read)."""
    entry = next((e for e in mod_service.profile_entries(profile) if e["index"] == index), None)
    if entry is None:
        raise OperationError("not_found", "The profile changed; look again.", {"index": index})
    return entry


def start_logged(
    session: Session, title: str, log_title: str, body: Callable[[Locations], Any], quiet: bool = False
) -> str:
    """For a plan's run: start body as a session job that is also an old-style logged one. Returns the job id."""
    loc = session.locations()
    return session.start(lambda _ctx: mods_page.run_logged_job(loc, title, log_title, body), title=title, quiet=quiet)
