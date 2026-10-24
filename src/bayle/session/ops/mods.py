"""The Mods page's operations for the HTTP layer, each handed straight to the session's ModsService
(services.mods_page): the page's snapshot, the notices the session remembers, the load-order drag table, and (in
mods_entries and mods_profile) every change to a profile or its entries. A plan is a check (what would change, with a
stamp) and a start (with the stamp the client confirmed); the long writes are jobs whose id is returned. A change
that asks only sometimes raises OperationError("needs_confirmation") with the reason and the facts in details until
it is sent again confirmed. Refusals are OperationError codes; the client words what it gets. Temporary: the Qt page
calls the service itself.

Conventions: a profile is its .me3 path, a client passes it in every call (the shell owns which one is current)."""

from __future__ import annotations

from bayle.errors import OperationError
from bayle.services.mods_page import ModsPageState, ModsService
from bayle.session.operations import Call, Params, Result, Session, operation, registry


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
