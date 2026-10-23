"""The Mod Configs page's operations for the HTTP layer, each handed straight to the session's ModConfigsService
(services.mod_configs): the page's tree, opening and saving a listed settings file by kind (text, form values,
Seamless Co-op), the Overhaul setup (its form, save, apply to the profiles using it, install a new one, turn it off),
sharing Seamless Co-op settings (the clipboard stays with the client: these take and give text) and the file stamp
that tells a file changed under the page. A plan is a check (what would change, with a stamp) and a start (with the
stamp the client confirmed); the long ones are jobs whose id is returned. No wording here; the client words what it
gets. Temporary: the Qt page calls the service itself."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from bayle.errors import OperationError
from bayle.overhauls.config import BasicNative
from bayle.services import game_checks
from bayle.services import mod_configs as svc
from bayle.services.mod_configs import ModConfigsService, ModConfigsState
from bayle.session.operations import Call, Params, Result, Session, operation, registry


class ModConfigsScope(Params):
    profile: str = ""


class ProfileParams(Params):
    profile: str


class FileParams(ProfileParams):
    path: str  # a file the profile's tree lists (anything else is not_found)


class OpenParams(FileParams):
    seamless: bool = False  # also read the Seamless Co-op panel and the regulation fingerprint


class FileRead(Result):
    """A file as read: the text exactly (line breaks as \\n) and what writing it back needs. The client builds the
    form from the text (services.mod_configs.parse_doc)."""

    path: str
    text: str
    encoding: str
    crlf: bool
    sha: str
    stamp: tuple[int, int] | None  # taken before reading: a later change shows
    seamless: svc.Seamless | None = None
    fingerprint: game_checks.Fingerprint | None = None  # Seamless only: the parameters the game will use
    regulation: str = ""  # the file the fingerprint is of


class Stamp(Result):
    stamp: tuple[int, int] | None  # modification time (ns) and size; None when the file is gone


class Edit(Params):
    section: str = ""
    key: str
    value: str


class SaveParams(FileParams):
    expect: str  # the sha the file had when it was read
    kind: Literal["text", "values", "seamless"]
    text: str = ""
    edits: tuple[Edit, ...] = ()


class Saved(Result):
    name: str
    saved: int  # settings written (text: 1)
    missing: tuple[str, ...] = ()  # Seamless keys the file does not have (nothing is appended)


class TieParams(ProfileParams):
    target: str  # the DLL, or the package's folder, of a mod of the profile
    file: str


class Done(Result):
    ok: bool = True


class Candidate(BaseModel):
    name: str
    id: str
    folder: str


class Candidates(Result):
    mods: list[Candidate]


class FormParams(ProfileParams):
    folder: str = ""  # set one of the profile's mods up as a new overhaul: its folder and name (and id); else its own
    name: str = ""
    overhaul_id: str = ""


class OverhaulForm(Result):
    setup: dict[str, Any]  # config, verified, level, folder, path, sha (services.mods.overhaul_setup_of)
    choices: dict[str, Any]
    values: dict[str, Any]  # the working values; services.mod_configs.patch_values edits them
    new: bool


class SetupForm(Params):
    natives: tuple[BasicNative, ...]
    files: dict[str, str]
    tables: dict[str, str]
    health: dict[str, str] | None = None  # None: the log check was not touched

    def values(self) -> svc.SetupValues:
        return svc.SetupValues([n.model_dump() for n in self.natives], self.files, self.tables, self.health)


class SaveSetupParams(ProfileParams):
    path: str
    expect: str
    form: SetupForm | None = None
    text: str | None = None  # the setup's TOML as text (instead of the form)


class SetupSaved(Result):
    name: str
    overhaul_id: str


class ModConfigsJob(Result):
    job_id: str


class ApplyParams(ProfileParams):
    overhaul_id: str


class InstallSetupParams(ProfileParams):
    folder: str
    name: str
    overhaul_id: str = ""
    form: SetupForm


class StartInstallParams(InstallSetupParams):
    expect: tuple[int, int] | None  # the stamp check_install_setup gave and the client confirmed


class StartTurnOffParams(ProfileParams):
    expect: tuple[int, int] | None  # the stamp check_turn_off gave and the client confirmed


class SetupPlan(Result):
    label: str
    lines: tuple[str, ...]
    notes: tuple[str, ...]
    refusals: tuple[str, ...]  # why it cannot go ahead (a start would be refused)
    stamp: tuple[int, int] | None


class IniParams(ProfileParams):
    ini: str  # the Seamless Co-op settings file the tree lists


class ShareText(Result):
    text: str


class ExportParams(IniParams):
    to: str


class PasteParams(IniParams):
    text: str


class PasteStartParams(PasteParams):
    expect: tuple[int, int] | None  # the stamp check_paste gave and the client confirmed


class PastePlan(Result):
    changes: dict[str, tuple[str, str]]  # key -> (yours, theirs)
    unknown: tuple[str, ...]  # keys the file does not have
    stamp: tuple[int, int] | None


class Pasted(Result):
    saved: int


def _none() -> ModConfigsService:
    raise OperationError("no_mod_configs_service", "This session has no Mod Configs page.")


def _svc(session: Session) -> ModConfigsService:
    return session.service("mod_configs", _none)


@registry.page("mod_configs", scope=ModConfigsScope, view=ModConfigsState)
def snapshot(session: Session, profile: str = "") -> ModConfigsState:
    return _svc(session).page(profile)


# ----------------------------------------------------------------------------- one file
@operation("mod_configs.open", params=OpenParams, result=FileRead)
def open_file(call: Call, p: OpenParams) -> FileRead:
    got = _svc(call.session).open(p.profile, p.path, seamless=p.seamless)
    o = got.opened
    return FileRead(
        path=str(o.path),
        text=o.text,
        encoding=o.encoding,
        crlf=o.crlf,
        sha=o.sha,
        stamp=got.stamp,
        seamless=got.seamless,
        fingerprint=got.fingerprint,
        regulation=got.regulation,
    )


@operation("mod_configs.stamp", params=FileParams, result=Stamp)
def stamp(call: Call, p: FileParams) -> Stamp:
    return Stamp(stamp=_svc(call.session).stamp(p.profile, p.path))


@operation("mod_configs.save", params=SaveParams, result=Saved, kind="command", writes=True)
def save(call: Call, p: SaveParams) -> Saved:
    """Write a file by its kind. Errors: not_found, stale (it changed since it was read), password_empty, unreadable,
    not_saved."""
    edits = [(e.section, e.key, e.value) for e in p.edits]
    got = _svc(call.session).save(p.profile, p.path, p.expect, p.kind, text=p.text, edits=edits)
    return Saved(name=got.name, saved=got.saved, missing=got.missing)


@operation("mod_configs.attach", params=TieParams, result=Done, kind="command", writes=True)
def attach(call: Call, p: TieParams) -> Done:
    _svc(call.session).attach(p.profile, p.target, p.file)
    return Done()


@operation("mod_configs.detach", params=TieParams, result=Done, kind="command", writes=True)
def detach(call: Call, p: TieParams) -> Done:
    _svc(call.session).detach(p.profile, p.target, p.file)
    return Done()


# ----------------------------------------------------------------------------- the Overhaul setup
@operation("mod_configs.setup_candidates", params=ProfileParams, result=Candidates)
def setup_candidates(call: Call, p: ProfileParams) -> Candidates:
    return Candidates(
        mods=[
            Candidate(name=m.name, id=m.id, folder=str(m.folder))
            for m in _svc(call.session).setup_candidates(p.profile)
        ]
    )


@operation("mod_configs.overhaul_form", params=FormParams, result=OverhaulForm)
def overhaul_form(call: Call, p: FormParams) -> OverhaulForm:
    """The Overhaul setup form's starting state: the choices the mod's files give and the values as the config has them."""
    f = _svc(call.session).overhaul_form(p.profile, p.folder, p.name, p.overhaul_id)
    return OverhaulForm(setup=f.setup, choices=f.choices, values=f.values, new=f.new)


@operation("mod_configs.save_setup", params=SaveSetupParams, result=SetupSaved, kind="command", writes=True)
def save_setup(call: Call, p: SaveSetupParams) -> SetupSaved:
    """Save the profile's overhaul setup, from the form or as text. Apply it with mod_configs.apply_setup. Errors:
    not_found, stale, invalid_setup, invalid_params, not_saved."""
    form = p.form.values() if p.form is not None else None
    got = _svc(call.session).save_setup(p.profile, p.path, p.expect, form=form, text=p.text)
    return SetupSaved(name=got.name, overhaul_id=got.overhaul_id)


@operation("mod_configs.apply_setup", params=ApplyParams, result=ModConfigsJob, kind="command", writes=True)
def apply_setup(call: Call, p: ApplyParams) -> ModConfigsJob:
    """A job (one Undo in Activity takes back every profile); its result is {"profiles": [names]}."""
    return ModConfigsJob(job_id=_svc(call.session).apply_setup(p.profile, p.overhaul_id))


@operation("mod_configs.check_install_setup", params=InstallSetupParams, result=SetupPlan)
def check_install_setup(call: Call, p: InstallSetupParams) -> SetupPlan:
    """What setting the mod up as the profile's overhaul would do; nothing is written."""
    plan = _svc(call.session).check_install_setup(p.profile, p.folder, p.name, p.form.values(), p.overhaul_id)
    return SetupPlan(**vars(plan))


@operation("mod_configs.install_setup", params=StartInstallParams, result=ModConfigsJob, kind="command", writes=True)
def install_setup(call: Call, p: StartInstallParams) -> ModConfigsJob:
    """A job; its result is {"name"}. Errors: stale, cannot_set_up (details: refusals), busy."""
    job = _svc(call.session).install_setup(p.profile, p.folder, p.name, p.form.values(), p.expect, p.overhaul_id)
    return ModConfigsJob(job_id=job)


@operation("mod_configs.check_turn_off", params=ProfileParams, result=SetupPlan)
def check_turn_off(call: Call, p: ProfileParams) -> SetupPlan:
    """What turning the profile's overhaul back into an ordinary mod would do; nothing is written."""
    return SetupPlan(**vars(_svc(call.session).check_turn_off(p.profile)))


@operation("mod_configs.turn_off", params=StartTurnOffParams, result=ModConfigsJob, kind="command", writes=True)
def turn_off(call: Call, p: StartTurnOffParams) -> ModConfigsJob:
    """A job (one Undo); its result is {"name"}. Errors: stale, cannot_turn_off, busy."""
    return ModConfigsJob(job_id=_svc(call.session).turn_off(p.profile, p.expect))


# ----------------------------------------------------------------------------- sharing Seamless Co-op settings
@operation("mod_configs.share", params=IniParams, result=ShareText)
def share(call: Call, p: IniParams) -> ShareText:
    return ShareText(text=_svc(call.session).share(p.profile, p.ini))


@operation("mod_configs.export_share", params=ExportParams, result=ModConfigsJob, kind="command", writes=True)
def export_share(call: Call, p: ExportParams) -> ModConfigsJob:
    """A job; its result is {"path"}. The file is written whole or not at all."""
    return ModConfigsJob(job_id=_svc(call.session).export_share(p.profile, p.ini, p.to))


@operation("mod_configs.check_paste", params=PasteParams, result=PastePlan)
def check_paste(call: Call, p: PasteParams) -> PastePlan:
    """What a friend's shared settings (text) would change; nothing is written. Errors: not_settings,
    nothing_to_change (details: unknown)."""
    return PastePlan(**vars(_svc(call.session).check_paste(p.profile, p.ini, p.text)))


@operation("mod_configs.paste", params=PasteStartParams, result=Pasted, kind="command", writes=True)
def paste(call: Call, p: PasteStartParams) -> Pasted:
    """Apply the shared settings. Errors: stale, password_empty, not_settings, nothing_to_change, not_saved."""
    return Pasted(saved=_svc(call.session).paste(p.profile, p.ini, p.text, p.expect))
