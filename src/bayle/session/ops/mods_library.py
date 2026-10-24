"""The Mods page's operations on the Library (opt-in sharing of game-file mods between profiles) for the HTTP layer,
each handed straight to the session's ModLibraryService (services.shared_mods): share a package, use a separate
copy, link other profiles to a version, list what is shared and remove the versions nobody uses. A change is a check
(what it would do, with a stamp) and a start (with the stamp the client confirmed; a job whose id is returned). No
wording here; the client words what it gets. Temporary: the Qt page calls the service itself."""

from __future__ import annotations

from bayle.errors import OperationError
from bayle.services import shared_mods as svc_module
from bayle.services.shared_mods import ModLibraryService
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation
from bayle.session.ops.mods_install import ProfileParams, Started


def _none() -> ModLibraryService:
    raise OperationError("no_mod_library_service", "This session has no Library service.")


def svc(session: Session) -> ModLibraryService:
    return session.service("mod_library", _none)


class EntryParams(ProfileParams):
    index: int  # the entry's block index in the profile


class StartParams(EntryParams):
    expect: tuple[int, int] | None  # the stamp the check gave and the client confirmed


class SharePlan(Result):
    name: str
    size: int  # of the shared version (separate only)
    stamp: tuple[int, int] | None


@operation("mods.check_share", params=EntryParams, result=SharePlan)
def check_share(call: Call, p: EntryParams) -> SharePlan:
    """What sharing a Separate package would do; nothing is written. Errors: not_found."""
    return SharePlan(**vars(svc(call.session).check_share(p.profile, p.index)))


@operation("mods.share", params=StartParams, result=Started, kind="command", writes=True)
def share(call: Call, p: StartParams) -> Started:
    """A job with one Undo in Activity. Errors: not_found, stale, busy; the job fails with library_refused."""
    return Started(job_id=svc(call.session).share(p.profile, p.index, p.expect))


@operation("mods.check_separate", params=EntryParams, result=SharePlan)
def check_separate(call: Call, p: EntryParams) -> SharePlan:
    """What giving the profile its own copy of a Shared mod would do. Errors: not_found, not_shared."""
    return SharePlan(**vars(svc(call.session).check_separate(p.profile, p.index)))


@operation("mods.separate", params=StartParams, result=Started, kind="command", writes=True)
def separate(call: Call, p: StartParams) -> Started:
    """A job with one Undo in Activity. Errors: not_found, not_shared, stale, busy; the job fails with
    library_refused."""
    return Started(job_id=svc(call.session).separate(p.profile, p.index, p.expect))


class UseChoices(Result):
    name: str
    mod_id: str
    version: str
    profiles: list[svc_module.UseProfile]


@operation("mods.library_use_choices", params=EntryParams, result=UseChoices)
def library_use_choices(call: Call, p: EntryParams) -> UseChoices:
    """The other profiles a Shared mod could be linked into. Errors: not_found, not_shared, no_other_profiles."""
    return UseChoices(**vars(svc(call.session).use_choices(p.profile, p.index)))


class UseParams(EntryParams):
    targets: list[str]  # the .me3 paths of library_use_choices' profiles to link


@operation("mods.library_use", params=UseParams, result=Started, kind="command", writes=True)
def library_use(call: Call, p: UseParams) -> Started:
    """A job with one Undo in Activity. Errors: not_found, not_shared, nothing_chosen, busy."""
    return Started(job_id=svc(call.session).use_in(p.profile, p.index, p.targets))


class LibraryRows(Result):
    mods: list[svc_module.LibraryMod]


@operation("mods.library", params=ProfileParams, result=LibraryRows)
def library(call: Call, p: ProfileParams) -> LibraryRows:
    return LibraryRows(mods=svc(call.session).mods())


class UnusedPlan(Result):
    versions: list[svc_module.UnusedVersion]
    size: int
    token: list[str]  # send it back with remove_unused


@operation("mods.check_remove_unused", params=NoParams, result=UnusedPlan)
def check_remove_unused(call: Call, p: NoParams) -> UnusedPlan:
    """The shared versions no profile uses. Errors: cannot_tell (message: why), nothing_unused."""
    got = svc(call.session).check_remove_unused()
    return UnusedPlan(versions=list(got.versions), size=got.size, token=list(got.token))


class RemoveUnusedParams(Params):
    expect: list[str]  # check_remove_unused' token


@operation("mods.remove_unused", params=RemoveUnusedParams, result=Started, kind="command", writes=True)
def remove_unused(call: Call, p: RemoveUnusedParams) -> Started:
    """A job (to the Recycle Bin; Undo in Activity brings them back). Errors: cannot_tell, nothing_unused, stale, busy."""
    return Started(job_id=svc(call.session).remove_unused(tuple(p.expect)))
