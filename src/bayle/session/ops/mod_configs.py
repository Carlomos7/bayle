"""The Mod Configs page's operations: its tree, opening and saving a settings file by kind (text, form values, Seamless
Co-op), the Overhaul setup (its form, save, apply to the profiles using it, install a new one, turn it off), sharing
Seamless Co-op settings (the clipboard stays with the client: these take and give text) and the file stamp that tells
a file changed under the page."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from bayle.errors import OperationError
from bayle.overhauls.config import BasicNative
from bayle.platform.text import tr
from bayle.services import mod_configs
from bayle.services import mods as mod_service
from bayle.services.settings import load_settings
from bayle.session.operations import Call, Params, Result, Session, operation, registry
from bayle.views.common import Refusal
from bayle.views.mod_configs import ModConfigsPresenter, ModConfigsState
from bayle.work.prompts import Proposal


class ModConfigsScope(Params):
    profile: str = ""


class PathParams(Params):
    path: str


class OpenParams(PathParams):
    seamless: bool = False  # also read the Seamless Co-op panel (and the regulation fingerprint line for profile)
    profile: str = ""


class FileRead(Result):
    """A file as read: the text exactly (line breaks as \\n) and what writing it back needs. The client builds the
    form from the text (services.mod_configs.parse_doc)."""

    path: str
    text: str
    encoding: str
    crlf: bool
    sha: str
    stamp: tuple[int, int] | None  # taken before reading: a later change shows
    seamless: mod_configs.Seamless | None = None
    fingerprint: str = ""
    fingerprint_note: str = ""


class Stamp(Result):
    stamp: tuple[int, int] | None  # modification time (ns) and size; None when the file is gone


class Edit(Params):
    section: str = ""
    key: str
    value: str


class SaveParams(PathParams):
    expect: str  # the sha the file had when it was read
    kind: Literal["text", "values", "seamless"]
    text: str = ""
    edits: tuple[Edit, ...] = ()


class Saved(Result):
    name: str
    saved: int  # settings written (text: 1)
    missing: tuple[str, ...] = ()  # Seamless keys the file does not have (nothing is appended)


class TieParams(Params):
    target: str  # the DLL, or the package's folder, the file is attached to
    file: str


class Done(Result):
    ok: bool = True


class ProfileParams(Params):
    profile: str


class Candidate(BaseModel):
    name: str
    id: str
    folder: str


class Candidates(Result):
    mods: list[Candidate]


class FormParams(ProfileParams):
    folder: str = (
        ""  # set a mod up as a new overhaul: its folder and name (and id when installed); else the profile's own
    )
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


class Applied(Result):
    profiles: list[str]


class InstallSetupParams(ProfileParams):
    folder: str
    name: str
    overhaul_id: str = ""
    form: SetupForm


class Installed(Result):
    name: str


class TurnedOff(Result):
    name: str


class IniParams(Params):
    ini: str


class ShareText(Result):
    text: str


class ExportParams(IniParams):
    to: str


class PasteParams(IniParams):
    text: str


def _presenter() -> ModConfigsPresenter:
    return ModConfigsPresenter()


def _unreadable(path: Path, e: Exception) -> OperationError:
    return OperationError("unreadable", str(e), {"name": path.name})


def _not_saved(e: Exception) -> OperationError:
    return OperationError("not_saved", str(e))


@registry.page("mod_configs", scope=ModConfigsScope, view=ModConfigsState)
def snapshot(session: Session, profile: str = "") -> ModConfigsState:
    try:
        loc = session.locations()
    except OperationError as e:
        if e.code != "no_game":
            raise
        return ModConfigsState("", ())
    if not profile or not Path(profile).is_file():
        return ModConfigsState("", ())
    return ModConfigsState(profile, tuple(mod_configs.tree(profile, loc=loc, settings=load_settings())))


# ----------------------------------------------------------------------------- one file
@operation("mod_configs.open", params=OpenParams, result=FileRead)
def open_file(call: Call, p: OpenParams) -> FileRead:
    path = Path(p.path)
    stamp = mod_configs.stamp(path)
    try:
        opened = mod_configs.open_file(path, form=False)
        seamless = mod_configs.seamless(path) if p.seamless else None
    except Exception as e:  # too big, not text, gone
        raise _unreadable(path, e) from e
    line, note = "", ""
    if seamless is not None and p.profile:
        from bayle.services import game_checks
        from bayle.views.mods import ModsPresenter

        loc = call.session.locations()
        fp = game_checks.regulation_fingerprint(Path(p.profile), loc)
        words = ModsPresenter()
        line = words.fingerprint(fp, loc.game.regulation)
        note = words.parameters({}, False, fp).fingerprint_note if fp else ""
    return FileRead(
        path=str(path),
        text=opened.text,
        encoding=opened.encoding,
        crlf=opened.crlf,
        sha=opened.sha,
        stamp=stamp,
        seamless=seamless,
        fingerprint=line,
        fingerprint_note=note,
    )


@operation("mod_configs.stamp", params=PathParams, result=Stamp)
def stamp(call: Call, p: PathParams) -> Stamp:
    return Stamp(stamp=mod_configs.stamp(Path(p.path)))


@operation("mod_configs.save", params=SaveParams, result=Saved, kind="command", writes=True)
def save(call: Call, p: SaveParams) -> Saved:
    """Write a file by its kind: text (all of it), values (only the edited settings' characters change) or Seamless
    Co-op keys. Errors: file_changed (it changed since it was read), password_empty, unreadable, not_saved."""
    path = Path(p.path)
    if p.kind == "seamless":
        values = {e.key: e.value for e in p.edits}
        try:
            missing = mod_configs.save_seamless(path, values)
        except OperationError:
            raise
        except Exception as e:
            raise _not_saved(e) from e
        return Saved(name=path.name, saved=len(values) - len(missing), missing=tuple(missing))
    try:
        opened = mod_configs.open_file(path, form=False)
    except Exception as e:
        raise _unreadable(path, e) from e
    if opened.sha != p.expect:
        raise OperationError("file_changed", f"{path.name} changed on disk since it was read; reload it and try again.")
    try:
        if p.kind == "text":
            mod_configs.save_text(opened, p.text)
            return Saved(name=path.name, saved=1)
        mod_configs.save_values(opened, {(e.section or None, e.key): e.value for e in p.edits})
    except Exception as e:  # a setting only text can change, a character the encoding cannot hold
        raise _not_saved(e) from e
    return Saved(name=path.name, saved=len(p.edits))


@operation("mod_configs.attach", params=TieParams, result=Done, kind="command", writes=True)
def attach(call: Call, p: TieParams) -> Done:
    mod_configs.attach(load_settings(), Path(p.target), Path(p.file))
    return Done()


@operation("mod_configs.detach", params=TieParams, result=Done, kind="command", writes=True)
def detach(call: Call, p: TieParams) -> Done:
    mod_configs.detach(load_settings(), Path(p.target), Path(p.file))
    return Done()


# ----------------------------------------------------------------------------- the Overhaul setup
def _setup_of(session: Session, p: FormParams) -> dict[str, Any]:
    """The setup the form is for: the profile's own, or a proposal for the mod in p.folder (nothing is written)."""
    loc = session.locations()
    if not p.folder:
        setup = mod_service.overhaul_setup_of(Path(p.profile), loc=loc)
        if setup is None:
            raise OperationError("not_found", tr("This profile has no overhaul setup."))
        return setup
    try:
        config = mod_service.propose_overhaul_setup(Path(p.folder), p.name, loc=loc, overhaul_id=p.overhaul_id or None)
    except (ValueError, OSError) as e:  # the folder has nothing to set up, or is gone
        raise OperationError("cannot_set_up", str(e)) from e
    return {"config": config, "verified": False, "level": "basic", "folder": Path(p.folder), "path": None, "sha": None}


@operation("mod_configs.setup_candidates", params=ProfileParams, result=Candidates)
def setup_candidates(call: Call, p: ProfileParams) -> Candidates:
    return Candidates(
        mods=[
            Candidate(name=m["name"], id=m["id"], folder=str(m["folder"]))
            for m in mod_configs.mods_to_set_up(p.profile)
        ]
    )


@operation("mod_configs.overhaul_form", params=FormParams, result=OverhaulForm)
def overhaul_form(call: Call, p: FormParams) -> OverhaulForm:
    """The Overhaul setup form's starting state: the choices the mod's files give and the values as the config has them."""
    loc = call.session.locations()
    setup = _setup_of(call.session, p)
    choices = mod_configs.overhaul_choices(setup, loc.game_dir())
    values = mod_configs.initial_values(choices, setup["config"])
    return OverhaulForm(setup=setup, choices=choices, values=values, new=bool(p.folder))


def _config_with(setup: dict[str, Any], form: SetupForm, call: Call):
    """The setup's config with the form's values. Raises OperationError invalid_setup (a texts entry with no table
    chosen, a "re:" text that is not a regular expression)."""
    loc = call.session.locations()
    choices = mod_configs.overhaul_choices(setup, loc.game_dir())
    try:
        return mod_configs.with_basic(
            setup["config"],
            natives=[n.model_dump() for n in form.natives],
            files=mod_configs.files_to_store(choices["files"], form.files),
            health=mod_configs.health_of_form(form.health) if form.health is not None else None,
            tables=form.tables,
        )
    except ValueError as e:
        raise OperationError("invalid_setup", str(e)) from e


@operation("mod_configs.save_setup", params=SaveSetupParams, result=SetupSaved, kind="command", writes=True)
def save_setup(call: Call, p: SaveSetupParams) -> SetupSaved:
    """Save the profile's overhaul setup, from the form or as text. Apply it to the profiles using it with
    mod_configs.apply_setup. Errors: file_changed, invalid_setup, not_found, not_saved."""
    try:
        if p.text is not None:
            config = mod_configs.parse_overhaul_text(p.text)
            out = mod_service.save_overhaul_setup(config, expect=p.expect, path=Path(p.path))
        else:
            if p.form is None:
                raise OperationError("invalid_params", "Give the form or the text.")
            setup = _setup_of(call.session, FormParams(profile=p.profile))
            if setup["sha"] != p.expect:
                raise OperationError("file_changed", tr("The setup changed on disk since it was read; reload it."))
            config = _config_with(setup, p.form, call)
            out = mod_service.save_overhaul_setup(config, expect=p.expect, path=setup["path"], folder=setup["folder"])
    except OperationError:
        raise
    except ValueError as e:  # the text is not a setup
        raise OperationError("invalid_setup", str(e)) from e
    except Exception as e:  # a verified one, changed on disk since, a config that would not read back
        raise _not_saved(e) from e
    return SetupSaved(name=Path(out).name, overhaul_id=config.id)


@operation(
    "mod_configs.apply_setup",
    params=ApplyParams,
    result=Applied,
    kind="job",
    writes=True,
    title="Applying the overhaul setup to the profiles using it...",
)
def apply_setup(call: Call, p: ApplyParams) -> Applied:
    """Install the saved setup again in every profile using it; one Undo in Activity takes back them all."""
    loc = call.session.locations()
    done = mod_configs.logged(
        "launcher: apply the saved overhaul setup",
        loc,
        lambda: mod_service.reapply_overhaul_setup(p.profile, p.overhaul_id, loc=loc),
    )
    return Applied(profiles=done)


@operation("mod_configs.install_setup", params=InstallSetupParams, result=Installed, kind="plan", writes=True)
def install_setup(call: Call, p: InstallSetupParams) -> Proposal | Refusal:
    """Offer to set a mod up as the profile's overhaul with the form's values; answering starts the install as a job."""
    session = call.session
    loc = session.locations()
    setup = _setup_of(session, FormParams(profile=p.profile, folder=p.folder, name=p.name, overhaul_id=p.overhaul_id))
    config = _config_with(setup, p.form, call)
    try:
        preview = mod_service.preview_overhaul_setup(p.profile, p.folder, config, loc=loc)
    except Exception as e:
        raise OperationError("cannot_set_up", str(e)) from e
    words = _presenter().install_setup(preview)
    if isinstance(words, Refusal):
        return words

    def run(_answer) -> str:
        where = session.locations()
        return session.start(
            lambda _ctx: Installed(
                name=mod_configs.logged(
                    f"launcher: set up {preview.label} as an overhaul",
                    where,
                    lambda: mod_service.install_overhaul_setup(preview, loc=where)["name"],
                )
            ),
            title=tr("Installing {label} as an overhaul...").format(label=preview.label),
        )

    return Proposal(words, run, stale=lambda: mod_configs.stamp(Path(p.profile)))


@operation("mod_configs.turn_off", params=ProfileParams, result=TurnedOff, kind="plan", writes=True)
def turn_off(call: Call, p: ProfileParams) -> Proposal | Refusal:
    """Offer to make the profile's overhaul an ordinary mod again; answering starts it as a job (one Undo)."""
    session = call.session
    try:
        preview = mod_service.preview_turn_off_overhaul(p.profile, loc=session.locations())
    except Exception as e:  # the profile has no overhaul
        raise OperationError("cannot_turn_off", str(e)) from e
    words = _presenter().turn_off(preview)
    if isinstance(words, Refusal):
        return words
    label = preview.remove.config.label

    def run(_answer) -> str:
        return session.start(
            lambda _ctx: TurnedOff(
                name=mod_configs.logged(
                    f"launcher: turn off overhaul {label}",
                    session.locations(),
                    lambda: mod_service.turn_off_overhaul(preview)["name"],
                )
            ),
            title=tr("Removing the overhaul setup of {label}...").format(label=label),
        )

    return Proposal(words, run, stale=lambda: mod_configs.stamp(Path(p.profile)))


# ----------------------------------------------------------------------------- sharing Seamless Co-op settings
@operation("mod_configs.share", params=IniParams, result=ShareText)
def share(call: Call, p: IniParams) -> ShareText:
    return ShareText(text=mod_configs.share_text(Path(p.ini)))


@operation("mod_configs.export_share", params=ExportParams, result=Done, kind="command", writes=True)
def export_share(call: Call, p: ExportParams) -> Done:
    try:
        Path(p.to).write_text(mod_configs.share_text(Path(p.ini)), encoding="utf-8")
    except OSError as e:
        raise _not_saved(e) from e
    return Done()


@operation("mod_configs.paste", params=PasteParams, result=Done, kind="plan", writes=True)
def paste(call: Call, p: PasteParams) -> Proposal:
    """Offer to apply a friend's shared settings (text) to the Seamless Co-op file; answering writes them (run
    returns None). Errors: not_settings (the text holds none), nothing_to_change (it matches), password_empty,
    file_changed."""
    ini = Path(p.ini)
    try:
        changes, unknown, opened = mod_configs.plan_paste(ini, p.text)
    except Exception as e:
        raise OperationError("not_settings", str(e)) from e
    words = _presenter()
    if not changes:
        raise OperationError("nothing_to_change", words.nothing_to_change(unknown), {"unknown": unknown})

    def run(_answer) -> None:
        try:
            mod_configs.apply_paste(opened, changes)
        except OperationError:
            raise
        except Exception as e:
            raise _not_saved(e) from e

    return Proposal(words.paste(changes, unknown), run, stale=lambda: mod_configs.stamp(ini))
