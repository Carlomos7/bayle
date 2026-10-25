"""Mod Configs over HTTP, each route handed straight to the engine's ModConfigsService (modules.mods.mod_configs): the
page's tree, opening and saving a listed settings file by kind (text, form values, Seamless Co-op), the Overhaul setup
(its form, save, apply to the profiles using it, install a new one, turn it off), sharing Seamless Co-op settings (the
clipboard stays with the client: these take and give text) and the file stamp that tells a file changed under the
page. A plan is a check (what would change, with a stamp) and a start (with the stamp the client confirmed); the long
ones are jobs whose id is returned. No wording here; the client words what it gets."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from bayle.api.deps import service
from bayle.api.models import JobStarted, Params, Result
from bayle.api.routers.mod_install import SetupForm
from bayle.modules.launch import game_checks
from bayle.modules.mods import mod_configs as svc
from bayle.modules.mods.mod_configs import ModConfigsService, ModConfigsState

router = APIRouter(prefix="/mod_configs", tags=["mod_configs"])
Configs = Annotated[ModConfigsService, Depends(service("mod_configs"))]


class ModConfigsScope(Params):
    profile: str = ""


class ProfileParams(Params):
    profile: str


class FileParams(ProfileParams):
    path: str  # a file the profile's tree lists (anything else is not_found)


class OpenFileParams(FileParams):
    seamless: bool = False  # also read the Seamless Co-op panel and the regulation fingerprint


class ConfigFileRead(Result):
    """A file as read: the text exactly (line breaks as \\n) and what writing it back needs. The client builds the
    form from the text (modules.mods.mod_configs.parse_doc)."""

    path: str
    text: str
    encoding: str
    crlf: bool
    sha: str
    stamp: tuple[int, int] | None  # taken before reading: a later change shows
    seamless: svc.Seamless | None = None
    fingerprint: game_checks.Fingerprint | None = None  # Seamless only: the parameters the game will use
    regulation: str = ""  # the file the fingerprint is of


class ConfigStamp(Result):
    stamp: tuple[int, int] | None  # modification time (ns) and size; None when the file is gone


class ConfigEdit(Params):
    section: str = ""
    key: str
    value: str


class SaveParams(FileParams):
    expect: str  # the sha the file had when it was read
    kind: Literal["text", "values", "seamless"]
    text: str = ""
    edits: tuple[ConfigEdit, ...] = ()


class ConfigSaved(Result):
    name: str
    saved: int  # settings written (text: 1)
    missing: tuple[str, ...] = ()  # Seamless keys the file does not have (nothing is appended)


class TieParams(ProfileParams):
    target: str  # the DLL, or the package's folder, of a mod of the profile
    file: str


class ConfigDone(Result):
    ok: bool = True


class ConfigCandidate(BaseModel):
    name: str
    id: str
    folder: str


class ConfigCandidates(Result):
    mods: list[ConfigCandidate]


class FormParams(ProfileParams):
    folder: str = ""  # set one of the profile's mods up as a new overhaul: its folder and name (and id); else its own
    name: str = ""
    overhaul_id: str = ""


class OverhaulForm(Result):
    setup: dict[str, Any]  # config, verified, level, folder, path, sha (modules.mods.service.overhaul_setup_of)
    choices: dict[str, Any]
    values: dict[str, Any]  # the working values; modules.mods.mod_configs.patch_values edits them
    new: bool


class SaveSetupParams(ProfileParams):
    path: str
    expect: str
    form: SetupForm | None = None
    text: str | None = None  # the setup's TOML as text (instead of the form)


class SetupSaved(Result):
    name: str
    overhaul_id: str


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


class ExportShareParams(IniParams):
    to: str


class PasteParams(IniParams):
    text: str


class PasteStartParams(PasteParams):
    expect: tuple[int, int] | None  # the stamp check_paste gave and the client confirmed


class PastePlan(Result):
    changes: dict[str, tuple[str, str]]  # key -> (yours, theirs)
    unknown: tuple[str, ...]  # keys the file does not have
    stamp: tuple[int, int] | None


class ConfigPasted(Result):
    saved: int


@router.get("", name="mod_configs")
def page(s: Configs, q: Annotated[ModConfigsScope, Query()]) -> ModConfigsState:
    return s.page(q.profile)


# ----------------------------------------------------------------------------- one file
@router.post("/open", name="mod_configs_open")
def open_file(s: Configs, p: OpenFileParams) -> ConfigFileRead:
    got = s.open(p.profile, p.path, seamless=p.seamless)
    o = got.opened
    return ConfigFileRead(
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


@router.post("/stamp", name="mod_configs_stamp")
def stamp(s: Configs, p: FileParams) -> ConfigStamp:
    return ConfigStamp(stamp=s.stamp(p.profile, p.path))


@router.post("/save", name="mod_configs_save")
def save(s: Configs, p: SaveParams) -> ConfigSaved:
    """Write a file by its kind. Errors: not_found, stale (it changed since it was read), password_empty, unreadable,
    not_saved."""
    edits = [(e.section, e.key, e.value) for e in p.edits]
    got = s.save(p.profile, p.path, p.expect, p.kind, text=p.text, edits=edits)
    return ConfigSaved(name=got.name, saved=got.saved, missing=got.missing)


@router.post("/attach", name="mod_configs_attach")
def attach(s: Configs, p: TieParams) -> ConfigDone:
    s.attach(p.profile, p.target, p.file)
    return ConfigDone()


@router.post("/detach", name="mod_configs_detach")
def detach(s: Configs, p: TieParams) -> ConfigDone:
    s.detach(p.profile, p.target, p.file)
    return ConfigDone()


# ----------------------------------------------------------------------------- the Overhaul setup
@router.post("/setup_candidates", name="mod_configs_setup_candidates")
def setup_candidates(s: Configs, p: ProfileParams) -> ConfigCandidates:
    return ConfigCandidates(
        mods=[ConfigCandidate(name=m.name, id=m.id, folder=str(m.folder)) for m in s.setup_candidates(p.profile)]
    )


@router.post("/overhaul_form", name="mod_configs_overhaul_form")
def overhaul_form(s: Configs, p: FormParams) -> OverhaulForm:
    """The Overhaul setup form's starting state: the choices the mod's files give and the values as the config has them."""
    f = s.overhaul_form(p.profile, p.folder, p.name, p.overhaul_id)
    return OverhaulForm(setup=f.setup, choices=f.choices, values=f.values, new=f.new)


@router.post("/save_setup", name="mod_configs_save_setup")
def save_setup(s: Configs, p: SaveSetupParams) -> SetupSaved:
    """Save the profile's overhaul setup, from the form or as text. Apply it with mod_configs.apply_setup. Errors:
    not_found, stale, invalid_setup, invalid_params, not_saved."""
    form = p.form.values() if p.form is not None else None
    got = s.save_setup(p.profile, p.path, p.expect, form=form, text=p.text)
    return SetupSaved(name=got.name, overhaul_id=got.overhaul_id)


@router.post("/apply_setup", name="mod_configs_apply_setup")
def apply_setup(s: Configs, p: ApplyParams) -> JobStarted:
    """A job (one Undo in Activity takes back every profile); its result is {"profiles": [names]}."""
    return JobStarted(job_id=s.apply_setup(p.profile, p.overhaul_id))


@router.post("/check_install_setup", name="mod_configs_check_install_setup")
def check_install_setup(s: Configs, p: InstallSetupParams) -> SetupPlan:
    """What setting the mod up as the profile's overhaul would do; nothing is written."""
    plan = s.check_install_setup(p.profile, p.folder, p.name, p.form.values(), p.overhaul_id)
    return SetupPlan(**vars(plan))


@router.post("/install_setup", name="mod_configs_install_setup")
def install_setup(s: Configs, p: StartInstallParams) -> JobStarted:
    """A job; its result is {"name"}. Errors: stale, cannot_set_up (details: refusals), busy."""
    job = s.install_setup(p.profile, p.folder, p.name, p.form.values(), p.expect, p.overhaul_id)
    return JobStarted(job_id=job)


@router.post("/check_turn_off", name="mod_configs_check_turn_off")
def check_turn_off(s: Configs, p: ProfileParams) -> SetupPlan:
    """What turning the profile's overhaul back into an ordinary mod would do; nothing is written."""
    return SetupPlan(**vars(s.check_turn_off(p.profile)))


@router.post("/turn_off", name="mod_configs_turn_off")
def turn_off(s: Configs, p: StartTurnOffParams) -> JobStarted:
    """A job (one Undo); its result is {"name"}. Errors: stale, cannot_turn_off, busy."""
    return JobStarted(job_id=s.turn_off(p.profile, p.expect))


# ----------------------------------------------------------------------------- sharing Seamless Co-op settings
@router.post("/share", name="mod_configs_share")
def share(s: Configs, p: IniParams) -> ShareText:
    return ShareText(text=s.share(p.profile, p.ini))


@router.post("/export_share", name="mod_configs_export_share")
def export_share(s: Configs, p: ExportShareParams) -> JobStarted:
    """A job; its result is {"path"}. The file is written whole or not at all."""
    return JobStarted(job_id=s.export_share(p.profile, p.ini, p.to))


@router.post("/check_paste", name="mod_configs_check_paste")
def check_paste(s: Configs, p: PasteParams) -> PastePlan:
    """What a friend's shared settings (text) would change; nothing is written. Errors: not_settings,
    nothing_to_change (details: unknown)."""
    return PastePlan(**vars(s.check_paste(p.profile, p.ini, p.text)))


@router.post("/paste", name="mod_configs_paste")
def paste(s: Configs, p: PasteStartParams) -> ConfigPasted:
    """Apply the shared settings. Errors: stale, password_empty, not_settings, nothing_to_change, not_saved."""
    return ConfigPasted(saved=s.paste(p.profile, p.ini, p.text, p.expect))
