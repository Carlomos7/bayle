"""mod_install over HTTP: the Install mod dialog and the overhauls the launcher installs, each route handed to the
engine's ModInstallService (see routers/activity.py for the shape). Which paths can be installed, open a download
(unpacked and planned, held by an install id), plan it again for another name, id or variant, preview it as an
overhaul, close it, hand its profiles to Import, and install with what the player chose (a job whose id is
returned). Overhauls: install from an unpacked download, remove (and what its installer changed to put back), take
over a setup its own installer made, and clean up what the installers left. A change is a check (what it would do,
with a stamp) and a start (with the stamp the client confirmed). The edits stay with the client: it sends its choices
again with the call that needs them. No wording here; the client words what it gets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from bayle.api.deps import service
from bayle.api.models import JobStarted as Started
from bayle.api.models import Params, Result
from bayle.api.routers.mods import ProfileRef
from bayle.modules.mods import mod_configs
from bayle.modules.mods.mod_install import InstallChoices, LeftoverFolder, ModInstallService
from bayle.modules.overhauls.config import BasicNative

router = APIRouter(prefix="/mod_install", tags=["mod_install"])
Install = Annotated[ModInstallService, Depends(service("mod_install"))]


class SetupForm(Params):
    """The overhaul setup form's values (shared with routers/mod_configs)."""

    natives: tuple[BasicNative, ...]
    files: dict[str, str]
    tables: dict[str, str]
    health: dict[str, str] | None = None  # None: the log check was not touched

    def values(self) -> mod_configs.SetupValues:
        return mod_configs.SetupValues([n.model_dump() for n in self.natives], self.files, self.tables, self.health)


class SourcesParams(Params):
    paths: list[str]


class Sources(Result):
    usable: list[str]  # folders, .zip / .7z / .rar archives and DLL mods
    skipped: list[str]  # the rest


@router.post("/install_sources", name="mod_install_sources")
def install_sources(i: Install, p: SourcesParams) -> Sources:
    """Which of the picked or dropped paths can be installed."""
    got = i.sources(p.paths)
    return Sources(usable=list(got.usable), skipped=list(got.skipped))


class OpenParams(ProfileRef):
    source: str  # a folder, an archive or a DLL


class Opened(Result):
    install_id: str
    plan: dict[str, Any]  # the plan as facts, with "option": plain | suggested | matched | refused
    overhaul_on: bool  # the Settings switch: the overhaul option is offered
    stamp: tuple[int, int] | None  # of the profile: send it back with install_finish


@router.post("/install_open", name="mod_install_open")
def install_open(i: Install, p: OpenParams) -> Opened:
    """Unpack and plan a download; it stays open until install_finish, install_close or install_import. Heavy: not for
    the UI thread. Errors: not_found, unreadable, not_installable, already_listed."""
    return Opened(**vars(i.open(p.profile, p.source)))


class InstallRef(Params):
    install_id: str


class ReplanParams(InstallRef):
    name: str
    id: str = ""
    variant: str | None = None


class InstallPlan(Result):
    plan: dict[str, Any]


@router.post("/install_replan", name="mod_install_replan")
def install_replan(i: Install, p: ReplanParams) -> InstallPlan:
    """Plan again for the typed name, id and variant. Heavy: not for the UI thread. Errors: unknown_install,
    cannot_plan (the last good plan stays)."""
    return InstallPlan(plan=i.replan(p.install_id, p.name, p.id, p.variant))


class PreviewParams(InstallRef):
    name: str
    setup: SetupForm | None = None  # the setup form's values when the player changed them


class OverhaulPreview(Result):
    mode: str  # matched | setup
    lines: list[str]
    notes: list[str]
    refusals: list[str]  # why it cannot be installed as an overhaul
    natives: list[dict[str, Any]]
    files: list[dict[str, Any]]
    texts: list[dict[str, Any]]
    editable: bool


@router.post("/install_preview", name="mod_install_preview")
def install_preview(i: Install, p: PreviewParams) -> OverhaulPreview:
    """The overhaul preview and the setup form's rows. Heavy: not for the UI thread. Errors: unknown_install,
    not_offered."""
    got = i.check_overhaul(p.install_id, p.name, p.setup.values() if p.setup is not None else None)
    return OverhaulPreview(**vars(got))


class InstallClosed(Result):
    install_id: str


@router.post("/install_close", name="mod_install_close")
def install_close(i: Install, p: InstallRef) -> InstallClosed:
    """The dialog was cancelled: the unpacked copy is dropped."""
    i.close(p.install_id)
    return InstallClosed(install_id=p.install_id)


class Handoff(Result):
    unpacked: str
    profiles: list[str]
    staging: str | None


@router.post("/install_import", name="mod_install_import")
def install_import(i: Install, p: InstallRef) -> Handoff:
    """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder (and clears the
    staging folder itself), so the install ends without dropping it. Errors: unknown_install, no_profiles."""
    got = i.hand_off(p.install_id)
    return Handoff(unpacked=got.unpacked, profiles=list(got.profiles), staging=got.staging)


class Choices(Params):
    """What the player set in the dialog (services.mod_install.InstallChoices)."""

    name: str
    id: str = ""
    variant: str | None = None
    exclude: list[str] = []  # the names of the plan's contents left unticked
    place_last: bool = False
    rebuild: bool = True
    after_last: bool = False
    library_choice: str = ""
    overhaul: bool = False
    setup: SetupForm | None = None

    def values(self) -> InstallChoices:
        d = self.model_dump(exclude={"setup", "exclude"})
        return InstallChoices(
            **d, exclude=tuple(self.exclude), setup=self.setup.values() if self.setup is not None else None
        )


class FinishParams(InstallRef):
    choices: Choices
    expect: tuple[int, int] | None  # the profile's stamp install_open gave


@router.post("/install_finish", name="mod_install_finish")
def install_finish(i: Install, p: FinishParams) -> Started:
    """A job with one Undo in Activity; its result is {"name", "overhaul", "update"}. The install ends with it.
    Errors: unknown_install, stale, cannot_plan, not_ready (details: reason, refusals), busy."""
    return Started(job_id=i.install(p.install_id, p.choices.values(), p.expect))


# ----------------------------------------------------------------------------- overhauls the launcher installs
class OverhaulPlan(Result):
    label: str
    lines: list[str]
    notes: list[str]
    refusals: list[str]  # why it cannot go ahead (a start would be refused)
    asked: list[str]  # the shared dependencies the revert option switches back off
    update: bool
    stamp: tuple[int, int] | None


class InstallFolder(ProfileRef):
    folder: str  # the folder the download was unpacked into


class InstallStart(InstallFolder):
    expect: tuple[int, int] | None  # the stamp the check gave


@router.post("/check_overhaul_install", name="mod_install_check_overhaul_install")
def check_overhaul_install(i: Install, p: InstallFolder) -> OverhaulPlan:
    """What installing an overhaul from the folder would do. Errors: not_found, unreadable."""
    return OverhaulPlan(**vars(i.check_overhaul_install(p.profile, p.folder)))


@router.post("/overhaul_install", name="mod_install_overhaul_install")
def overhaul_install(i: Install, p: InstallStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, unreadable, stale, cannot_install (details: refusals), busy."""
    return Started(job_id=i.install_overhaul(p.profile, p.folder, p.expect))


class OverhaulChoices(Result):
    label: str
    rows: list[str]  # the changes that can be chosen (none: nothing to offer)
    ticked: list[int] = []  # the rows to offer ticked


@router.post("/overhaul_remove_choices", name="mod_install_overhaul_remove_choices")
def overhaul_remove_choices(i: Install, p: ProfileRef) -> OverhaulChoices:
    """For an overhaul its own installer set up: the changes it made that can be put back. Errors: not_found,
    no_overhaul."""
    return OverhaulChoices(**vars(i.remove_choices(p.profile)))


class RemoveChosen(ProfileRef):
    chosen: list[int] = []  # the ticked rows of the choices call


class RemoveStart(RemoveChosen):
    revert: bool = False  # also switch the plan's asked dependencies back off
    expect: tuple[int, int] | None


@router.post("/check_overhaul_remove", name="mod_install_check_overhaul_remove")
def check_overhaul_remove(i: Install, p: RemoveChosen) -> OverhaulPlan:
    """What removing the profile's overhaul would do. Errors: not_found, no_overhaul, cannot_remove."""
    return OverhaulPlan(**vars(i.check_overhaul_remove(p.profile, p.chosen)))


@router.post("/overhaul_remove", name="mod_install_overhaul_remove")
def overhaul_remove(i: Install, p: RemoveStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, no_overhaul, stale, cannot_remove (details: refusals), busy."""
    return Started(job_id=i.remove_overhaul(p.profile, p.chosen, p.revert, p.expect))


@router.post("/takeover_choices", name="mod_install_takeover_choices")
def takeover_choices(i: Install, p: ProfileRef) -> OverhaulChoices:
    """For Take over: what the player may also choose, the entries the installer copied ticked. Errors: not_found,
    no_overhaul, no_takeover."""
    return OverhaulChoices(**vars(i.take_over_choices(p.profile)))


@router.post("/check_takeover", name="mod_install_check_takeover")
def check_takeover(i: Install, p: RemoveChosen) -> OverhaulPlan:
    """What taking over a setup its own installer made would do. Errors: not_found, no_overhaul, cannot_take_over."""
    return OverhaulPlan(**vars(i.check_take_over(p.profile, p.chosen)))


@router.post("/takeover", name="mod_install_takeover")
def takeover(i: Install, p: RemoveStart) -> Started:
    """A job with one Undo in Activity. Errors: not_found, no_overhaul, stale, cannot_take_over (details: refusals), busy."""
    return Started(job_id=i.take_over(p.profile, p.chosen, p.revert, p.expect))


class Leftovers(Result):
    folders: list[LeftoverFolder]
    backups: list[LeftoverFolder]  # asked one at a time and last: the installers' profile backups


@router.post("/leftovers", name="mod_install_leftovers")
def leftovers(i: Install, p: ProfileRef) -> Leftovers:
    """What overhauls' own installers left beside the profile that no profile uses any more."""
    return Leftovers(**vars(i.leftovers(p.profile)))


class CleanParams(ProfileRef):
    paths: list[str]  # leftovers' own folders or backups


@router.post("/leftovers_clean", name="mod_install_leftovers_clean")
def leftovers_clean(i: Install, p: CleanParams) -> Started:
    """A job: the chosen leftovers go to the Recycle Bin. Errors: not_found, nothing_chosen, busy."""
    return Started(job_id=i.clean_leftovers(p.profile, p.paths))
