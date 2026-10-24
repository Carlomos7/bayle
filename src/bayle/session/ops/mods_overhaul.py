"""The Mods page's operations on overhauls the launcher installs (a preview feature) for the HTTP layer, each handed
straight to the session's ModInstallService (services.mod_install): install from an unpacked download, remove (and
what its installer changed to put back), take over a setup its own installer made, and clean up what the installers
left. A change is a check (what it would do, with a stamp) and a start (with the stamp the client confirmed; a job
whose id is returned). The tick lists are rows of the choices call; a check or start names the ticked rows, and the
server derives the same rows again from the profile. No wording here; the client words what it gets. Temporary: the
Qt page calls the service itself."""

from __future__ import annotations

from bayle.services.mod_install import LeftoverFolder
from bayle.session.operations import Call, Result, operation
from bayle.session.ops.mods_install import ProfileParams, Started, svc


class OverhaulPlan(Result):
    label: str
    lines: list[str]
    notes: list[str]
    refusals: list[str]  # why it cannot go ahead (a start would be refused)
    asked: list[str]  # the shared dependencies the revert option switches back off
    update: bool
    stamp: tuple[int, int] | None


class InstallFolder(ProfileParams):
    folder: str  # the folder the download was unpacked into


class InstallStart(InstallFolder):
    expect: tuple[int, int] | None  # the stamp the check gave


@operation("mods.check_overhaul_install", params=InstallFolder, result=OverhaulPlan)
def check_overhaul_install(call: Call, p: InstallFolder) -> OverhaulPlan:
    """What installing an overhaul from the folder would do. Errors: not_found, unreadable."""
    return OverhaulPlan(**vars(svc(call.session).check_overhaul_install(p.profile, p.folder)))


@operation("mods.overhaul_install", params=InstallStart, result=Started, kind="command", writes=True)
def overhaul_install(call: Call, p: InstallStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, unreadable, stale, cannot_install (details: refusals), busy."""
    return Started(job_id=svc(call.session).install_overhaul(p.profile, p.folder, p.expect))


class OverhaulChoices(Result):
    label: str
    rows: list[str]  # the changes that can be chosen (none: nothing to offer)
    ticked: list[int] = []  # the rows to offer ticked


@operation("mods.overhaul_remove_choices", params=ProfileParams, result=OverhaulChoices)
def overhaul_remove_choices(call: Call, p: ProfileParams) -> OverhaulChoices:
    """For an overhaul its own installer set up: the changes it made that can be put back. Errors: not_found,
    no_overhaul."""
    return OverhaulChoices(**vars(svc(call.session).remove_choices(p.profile)))


class RemoveChosen(ProfileParams):
    chosen: list[int] = []  # the ticked rows of the choices call


class RemoveStart(RemoveChosen):
    revert: bool = False  # also switch the plan's asked dependencies back off
    expect: tuple[int, int] | None


@operation("mods.check_overhaul_remove", params=RemoveChosen, result=OverhaulPlan)
def check_overhaul_remove(call: Call, p: RemoveChosen) -> OverhaulPlan:
    """What removing the profile's overhaul would do. Errors: not_found, no_overhaul, cannot_remove."""
    return OverhaulPlan(**vars(svc(call.session).check_overhaul_remove(p.profile, p.chosen)))


@operation("mods.overhaul_remove", params=RemoveStart, result=Started, kind="command", writes=True)
def overhaul_remove(call: Call, p: RemoveStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, no_overhaul, stale, cannot_remove (details: refusals), busy."""
    return Started(job_id=svc(call.session).remove_overhaul(p.profile, p.chosen, p.revert, p.expect))


@operation("mods.takeover_choices", params=ProfileParams, result=OverhaulChoices)
def takeover_choices(call: Call, p: ProfileParams) -> OverhaulChoices:
    """For Take over: what the player may also choose, the entries the installer copied ticked. Errors: not_found,
    no_overhaul, no_takeover."""
    return OverhaulChoices(**vars(svc(call.session).take_over_choices(p.profile)))


@operation("mods.check_takeover", params=RemoveChosen, result=OverhaulPlan)
def check_takeover(call: Call, p: RemoveChosen) -> OverhaulPlan:
    """What taking over a setup its own installer made would do. Errors: not_found, no_overhaul, cannot_take_over."""
    return OverhaulPlan(**vars(svc(call.session).check_take_over(p.profile, p.chosen)))


@operation("mods.takeover", params=RemoveStart, result=Started, kind="command", writes=True)
def takeover(call: Call, p: RemoveStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, no_overhaul, stale, cannot_take_over (details: refusals), busy."""
    return Started(job_id=svc(call.session).take_over(p.profile, p.chosen, p.revert, p.expect))


class Leftovers(Result):
    folders: list[LeftoverFolder]
    backups: list[LeftoverFolder]  # asked one at a time and last: the installers' profile backups


@operation("mods.leftovers", params=ProfileParams, result=Leftovers)
def leftovers(call: Call, p: ProfileParams) -> Leftovers:
    """What overhauls' own installers left beside the profile that no profile uses any more."""
    return Leftovers(**vars(svc(call.session).leftovers(p.profile)))


class CleanParams(ProfileParams):
    paths: list[str]  # leftovers' own folders or backups


@operation("mods.leftovers_clean", params=CleanParams, result=Started, kind="command", writes=True)
def leftovers_clean(call: Call, p: CleanParams) -> Started:
    """A job: the chosen leftovers go to the Recycle Bin. Errors: not_found, nothing_chosen, busy."""
    return Started(job_id=svc(call.session).clean_leftovers(p.profile, p.paths))
