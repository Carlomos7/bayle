"""The Mods page's operations on the Library (opt-in sharing of game-file mods between profiles): share a package,
use a separate copy, link other profiles to a version, list what is shared and remove the versions nobody uses.
See ops/mods.py for the conventions."""

from __future__ import annotations

import dataclasses
from typing import Any

from bayle.platform import logging as run_logging
from bayle.platform.text import tr
from bayle.services import shared_mods as library_service
from bayle.services.errors import OperationError
from bayle.session.operations import Call, Result, operation
from bayle.session.ops.mods import Done, EntryRef, ProfileRef, entry_of, run_logged_job, stamp, start_logged
from bayle.session.ops.mods_overhaul import PickOffer
from bayle.session.plans import Answer, Proposal
from bayle.views.common import Refusal, prompt_dict
from bayle.views.mods import ModsPresenter


def _done(what: str, work: Any) -> Any:
    """The Library job's body: the Library refuses with its reason and changes nothing; a success is logged."""

    def body(loc: Any) -> dict:
        work(loc)
        run_logging.log(f"done: {what}")
        return Done(note=what).model_dump()

    return body


@operation("mods.share", params=EntryRef, result=Done, kind="plan", writes=True)
def share(call: Call, p: EntryRef) -> Proposal:
    """Share a Separate package: its files become shared mods and this profile uses them from there."""
    name = entry_of(p.profile, p.index)["name"]

    def run(_answer: Answer) -> str:
        what = f"share {name}"
        title = tr("Sharing {name}...").format(name=name)
        body = _done(what, lambda loc: library_service.share(p.profile, [p.index], loc=loc))
        return start_logged(call.session, title, f"launcher: {what}", body)

    return Proposal(ModsPresenter.share_confirm([name]), run, stale=lambda: stamp(p.profile))


def _ref(call: Call, p: EntryRef) -> tuple[tuple[str, str], str]:
    """The Shared mod (id, version) the entry uses and its name; OperationError not_shared when it is a Separate one."""
    loc = call.session.locations()
    ref = library_service.shared_ref(p.profile, entry_of(p.profile, p.index), loc=loc)
    if ref is None:
        raise OperationError("not_shared", tr("This mod is not shared."))
    return ref, library_service.display_name(ref[0], loc=loc)


@operation("mods.separate", params=EntryRef, result=Done, kind="plan", writes=True)
def separate(call: Call, p: EntryRef) -> Proposal | Refusal:
    """Give this profile its own editable copy of a Shared mod; the other profiles keep the shared files."""
    try:
        ref, name = _ref(call, p)
    except OperationError as e:
        return Refusal(tr("Not shared"), e.message)
    size = library_service.version_size(*ref, loc=call.session.locations())

    def run(_answer: Answer) -> str:
        what = f"separate copy of {name}"
        title = tr("Copying {name}...").format(name=name)
        body = _done(what, lambda loc: library_service.separate(p.profile, [p.index], loc=loc))
        return start_logged(call.session, title, f"launcher: {what}", body)

    return Proposal(ModsPresenter.separate_confirm(name, size), run, stale=lambda: stamp(p.profile))


@operation("mods.library_use_choices", params=EntryRef, result=PickOffer)
def library_use_choices(call: Call, p: EntryRef) -> PickOffer:
    """The other profiles a Shared mod could be linked into, as a tick list (a profile with its own copy: ticking
    replaces it)."""
    ref, name = _ref(call, p)
    found = library_service.candidates(p.profile, ref[0], loc=call.session.locations())
    if not found:
        raise OperationError("no_other_profiles", tr("There are no other profiles."))
    pres = ModsPresenter()
    rows = tuple(pres.use_row(c.profile.stem, c.has_copy, c.uses) for c in found)
    return PickOffer(label=name, prompt=prompt_dict(dataclasses.replace(pres.use_pick(name), rows=rows)))


class UseParams(EntryRef):
    targets: list[int]  # the ticked rows of library_use_choices


def _check_use(call: Call, p: UseParams) -> None:
    if not p.targets:
        raise OperationError("nothing_chosen", tr("Nothing was chosen."))


@operation(
    "mods.library_use",
    params=UseParams,
    result=Done,
    kind="job",
    writes=True,
    title=lambda c, p: tr("Linking {name}...").format(name=_ref(c, p)[1]),
    check=_check_use,
)
def library_use(call: Call, p: UseParams) -> Done:
    """Link the ticked profiles to the version this profile uses."""
    ref, name = _ref(call, p)
    loc = call.session.locations()
    found = library_service.candidates(p.profile, ref[0], loc=loc)
    targets = {found[i].profile: True for i in p.targets if 0 <= i < len(found)}
    what = f"use {name} in other profiles"
    body = _done(what, lambda jloc: library_service.use_in(ref[0], ref[1], targets, loc=jloc))
    run_logged_job(loc, tr("Linking {name}...").format(name=name), f"launcher: {what}", body)
    return Done(note=what)


class LibraryRows(Result):
    rows: list[dict[str, Any]]  # each mod with its versions, "Installed <date>", size and who uses it


@operation("mods.library", params=ProfileRef, result=LibraryRows)
def library(call: Call, p: ProfileRef) -> LibraryRows:
    try:
        return LibraryRows(rows=ModsPresenter().library(library_service.listing(call.session.locations())))
    except Exception:
        return LibraryRows(rows=[])


@operation("mods.remove_unused", params=ProfileRef, result=Done, kind="plan", writes=True)
def remove_unused(call: Call, p: ProfileRef) -> Proposal | Refusal:
    """Remove the shared versions no profile uses (to the Recycle Bin; Undo in Activity brings them back)."""
    found, why = library_service.unused(call.session.locations())
    if why:
        return Refusal(tr("Can't tell what is unused"), why)
    if not found:
        return Refusal(tr("Nothing to remove"), tr("Every shared version is in use."), info=True)

    def run(_answer: Answer) -> str:
        what = "remove unused library versions"
        body = _done(what, lambda loc: library_service.remove_unused(loc=loc))
        return start_logged(call.session, tr("Removing unused versions..."), f"launcher: {what}", body)

    size = sum(v.size for _m, v in found)
    return Proposal(ModsPresenter.clean_confirm(len(found), size), run)
