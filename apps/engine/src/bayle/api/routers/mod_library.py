"""mod_library over HTTP: the Library (opt-in sharing of game-file mods between profiles), each route handed to the
engine's ModLibraryService (see routers/activity.py for the shape): share a package, use a separate copy, link other
profiles to a version, list what is shared and remove the versions nobody uses. A change is a check (what it would do,
with a stamp) and a start (with the stamp the client confirmed; a job whose id is returned). No wording here; the
client words what it gets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from bayle.api.deps import service
from bayle.api.models import JobStarted as Started
from bayle.api.models import Params, Result
from bayle.api.routers.mods import EntryRef, ProfileRef
from bayle.modules.mods import shared_mods_page as shared_mods
from bayle.modules.mods.shared_mods_page import ModLibraryService

router = APIRouter(prefix="/mod_library", tags=["mod_library"])
Library = Annotated[ModLibraryService, Depends(service("mod_library"))]


class ShareStart(EntryRef):
    expect: tuple[int, int] | None  # the stamp the check gave and the client confirmed


class SharePlan(Result):
    name: str
    size: int  # of the shared version (separate only)
    stamp: tuple[int, int] | None


@router.post("/check_share", name="mod_library_check_share")
def check_share(lib: Library, p: EntryRef) -> SharePlan:
    """What sharing a Separate package would do; nothing is written. Errors: not_found."""
    return SharePlan(**vars(lib.check_share(p.profile, p.index)))


@router.post("/share", name="mod_library_share")
def share(lib: Library, p: ShareStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, stale, busy; the job fails with library_refused."""
    return Started(job_id=lib.share(p.profile, p.index, p.expect))


@router.post("/check_separate", name="mod_library_check_separate")
def check_separate(lib: Library, p: EntryRef) -> SharePlan:
    """What giving the profile its own copy of a Shared mod would do. Errors: not_found, not_shared."""
    return SharePlan(**vars(lib.check_separate(p.profile, p.index)))


@router.post("/separate", name="mod_library_separate")
def separate(lib: Library, p: ShareStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, not_shared, stale, busy; the job fails with
    library_refused."""
    return Started(job_id=lib.separate(p.profile, p.index, p.expect))


class UseChoices(Result):
    name: str
    mod_id: str
    version: str
    profiles: list[shared_mods.UseProfile]


@router.post("/library_use_choices", name="mod_library_use_choices")
def library_use_choices(lib: Library, p: EntryRef) -> UseChoices:
    """The other profiles a Shared mod could be linked into. Errors: not_found, not_shared, no_other_profiles."""
    return UseChoices(**vars(lib.use_choices(p.profile, p.index)))


class UseParams(EntryRef):
    targets: list[str]  # the .me3 paths of library_use_choices' profiles to link


@router.post("/library_use", name="mod_library_use")
def library_use(lib: Library, p: UseParams) -> Started:
    """A job with one Undo in Activity. Errors: not_found, not_shared, nothing_chosen, busy."""
    return Started(job_id=lib.use_in(p.profile, p.index, p.targets))


class LibraryRows(Result):
    mods: list[shared_mods.LibraryMod]


@router.post("/library", name="mod_library_rows")
def library(lib: Library, p: ProfileRef) -> LibraryRows:
    return LibraryRows(mods=lib.mods())


class UnusedPlan(Result):
    versions: list[shared_mods.UnusedVersion]
    size: int
    token: list[str]  # send it back with remove_unused


@router.post("/check_remove_unused", name="mod_library_check_remove_unused")
def check_remove_unused(lib: Library) -> UnusedPlan:
    """The shared versions no profile uses. Errors: cannot_tell (message: why), nothing_unused."""
    got = lib.check_remove_unused()
    return UnusedPlan(versions=list(got.versions), size=got.size, token=list(got.token))


class RemoveUnusedParams(Params):
    expect: list[str]  # check_remove_unused' token


@router.post("/remove_unused", name="mod_library_remove_unused")
def remove_unused(lib: Library, p: RemoveUnusedParams) -> Started:
    """A job (to the Recycle Bin; Undo in Activity brings them back). Errors: cannot_tell, nothing_unused, stale, busy."""
    return Started(job_id=lib.remove_unused(tuple(p.expect)))
