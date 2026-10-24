"""The Install mod dialog's operations for the HTTP layer, each handed straight to the session's ModInstallService
(services.mod_install): which paths can be installed, open a download (unpacked and planned, held by an install id),
plan it again for another name, id or variant, preview it as an overhaul, close it, hand its profiles to Import, and
install with what the player chose (a job whose id is returned). The edits stay with the client: it sends its choices
again with the call that needs them. No wording here; the client words what it gets. Temporary: the Qt page calls the
service itself."""

from __future__ import annotations

from typing import Any

from bayle.api.routers.mod_configs import SetupForm
from bayle.errors import OperationError
from bayle.services.mod_install import InstallChoices, ModInstallService
from bayle.session.operations import Call, Params, Result, Session, operation


def _none() -> ModInstallService:
    raise OperationError("no_mod_install_service", "This session has no install service.")


def svc(session: Session) -> ModInstallService:
    return session.service("mod_install", _none)


class ProfileParams(Params):
    profile: str  # the .me3 path


class Started(Result):
    job_id: str


class SourcesParams(Params):
    paths: list[str]


class Sources(Result):
    usable: list[str]  # folders, .zip / .7z / .rar archives and DLL mods
    skipped: list[str]  # the rest


@operation("mods.install_sources", params=SourcesParams, result=Sources)
def install_sources(call: Call, p: SourcesParams) -> Sources:
    """Which of the picked or dropped paths can be installed."""
    got = svc(call.session).sources(p.paths)
    return Sources(usable=list(got.usable), skipped=list(got.skipped))


class OpenParams(ProfileParams):
    source: str  # a folder, an archive or a DLL


class Opened(Result):
    install_id: str
    plan: dict[str, Any]  # the plan as facts, with "option": plain | suggested | matched | refused
    overhaul_on: bool  # the Settings switch: the overhaul option is offered
    stamp: tuple[int, int] | None  # of the profile: send it back with install_finish


@operation("mods.install_open", params=OpenParams, result=Opened, kind="command", writes=True)
def install_open(call: Call, p: OpenParams) -> Opened:
    """Unpack and plan a download; it stays open until install_finish, install_close or install_import. Heavy: not for
    the UI thread. Errors: not_found, unreadable, not_installable, already_listed."""
    return Opened(**vars(svc(call.session).open(p.profile, p.source)))


class InstallRef(Params):
    install_id: str


class ReplanParams(InstallRef):
    name: str
    id: str = ""
    variant: str | None = None


class Plan(Result):
    plan: dict[str, Any]


@operation("mods.install_replan", params=ReplanParams, result=Plan, kind="command", writes=True)
def install_replan(call: Call, p: ReplanParams) -> Plan:
    """Plan again for the typed name, id and variant. Heavy: not for the UI thread. Errors: unknown_install,
    cannot_plan (the last good plan stays)."""
    return Plan(plan=svc(call.session).replan(p.install_id, p.name, p.id, p.variant))


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


@operation("mods.install_preview", params=PreviewParams, result=OverhaulPreview, kind="command", writes=True)
def install_preview(call: Call, p: PreviewParams) -> OverhaulPreview:
    """The overhaul preview and the setup form's rows. Heavy: not for the UI thread. Errors: unknown_install,
    not_offered."""
    got = svc(call.session).check_overhaul(p.install_id, p.name, p.setup.values() if p.setup is not None else None)
    return OverhaulPreview(**vars(got))


class Closed(Result):
    install_id: str


@operation("mods.install_close", params=InstallRef, result=Closed, kind="command", writes=True)
def install_close(call: Call, p: InstallRef) -> Closed:
    """The dialog was cancelled: the unpacked copy is dropped."""
    svc(call.session).close(p.install_id)
    return Closed(install_id=p.install_id)


class Handoff(Result):
    unpacked: str
    profiles: list[str]
    staging: str | None


@operation("mods.install_import", params=InstallRef, result=Handoff, kind="command", writes=True)
def install_import(call: Call, p: InstallRef) -> Handoff:
    """The download ships .me3 profiles: the Export / Import page takes over its unpacked folder (and clears the
    staging folder itself), so the install ends without dropping it. Errors: unknown_install, no_profiles."""
    got = svc(call.session).hand_off(p.install_id)
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


@operation("mods.install_finish", params=FinishParams, result=Started, kind="command", writes=True)
def install_finish(call: Call, p: FinishParams) -> Started:
    """A job with one Undo in Activity; its result is {"name", "overhaul", "update"}. The install ends with it.
    Errors: unknown_install, stale, cannot_plan, not_ready (details: reason, refusals), busy."""
    return Started(job_id=svc(call.session).install(p.install_id, p.choices.values(), p.expect))
