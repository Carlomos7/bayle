"""The Settings page's operations: its snapshot, one change of a setting, the folder buttons, the folder-name check,
and the three layout changes (rename the folders, move the profiles folder, move every profile in), which move user
folders and so are plans (confirm first) that run as jobs with a cancel token and an Undo in Activity."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from bayle.game import catalog as games
from bayle.platform.text import tr
from bayle.services import layout as layout_service
from bayle.services import play as play_service
from bayle.services import settings as store
from bayle.services.errors import Busy, OperationError
from bayle.services.jobs import run_job_value
from bayle.session.jobs import JobContext
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry
from bayle.session.plans import Proposal
from bayle.views import settings as sp
from bayle.views import settings_state as state
from bayle.views.common import Refusal
from bayle.views.settings_state import SettingsState


class SetParams(Params):
    key: str  # a key of the snapshot's specs
    value: bool | int | str


class Changed(Result):
    key: str
    value: bool | int | str  # as saved (a number is brought into its range, a location is trimmed)
    stored_as: str  # the key in the settings file (the repair switch has one per game)
    follow: str  # none | settings | appearance | updates: what the window does next
    said: str = ""


class FolderParams(Params):
    kind: str  # me3 | game | profiles | saves | backups | settings


class FolderPath(Result):
    path: str | None  # None when the folder is not on this PC


class Names(Params):
    """The four folder names; None leaves one as it is."""

    pattern: str | None = None
    packages: str | None = None
    natives: str | None = None
    shared: str | None = None


class LayoutCheck(Result):
    errors: dict[str, str]  # field -> the sentence under each unusable name
    preview: str  # the folder the game would get, "" when the pattern is unusable


class RelocateParams(Params):
    folder: str


class Moved(Result):
    count: int = 0


class Cleared(Result):
    pass


def _where(session: Session) -> tuple[Any, Any]:
    """(game, locations or None) for the current game; Elden Ring with no locations when none is selected."""
    try:
        loc = session.locations()
    except OperationError:
        return games.ELDEN_RING, None
    return loc.game, loc


@registry.page("settings", view=SettingsState)
def snapshot(session: Session) -> SettingsState:
    game, loc = _where(session)
    return state.build(store.facts(game, loc), game)


@operation("settings.set", params=SetParams, result=Changed, kind="command", writes=True)
def set_setting(call: Call, p: SetParams) -> Changed:
    """Change one setting. Errors: unknown_setting, invalid_value, invalid_choice, path_problem."""
    spec = store.schema(state.switch_keys()).get(p.key)
    if spec is None:
        msg = tr("There is no setting called {key}.").format(key=p.key)
        raise OperationError("unknown_setting", msg, {"key": p.key})
    game, _loc = _where(call.session)
    value = store.normalise(spec, p.value, game)
    stored = store.store(spec, value, game)
    said = ""
    if spec.kind == "location":
        said = state.location_said(str(value))
    elif p.key == "log_level":
        said = tr(state.LOG_LEVEL_SAID)
    return Changed(key=p.key, value=value, stored_as=stored, follow=spec.follow, said=said)


@operation("settings.folder", params=FolderParams, result=FolderPath, kind="command", writes=True)
def folder(call: Call, p: FolderParams) -> FolderPath:
    """The folder behind an "Open ... folder" button; asking for the backups folder creates it. Errors: unknown_folder."""
    _game, loc = _where(call.session)
    found = store.folder(p.kind, loc, make=True)
    return FolderPath(path=None if found is None else str(found))


@operation("settings.layout_check", params=Names, result=LayoutCheck)
def layout_check(call: Call, p: Names) -> LayoutCheck:
    """Which of the folder names cannot be used, and the preview of the game folder."""
    game, _loc = _where(call.session)
    draft = {k: v for k, v in p.model_dump().items() if v is not None}
    return LayoutCheck(errors=sp.name_errors(draft), preview=sp.game_preview(draft.get("pattern", ""), game.key))


def _refusal_if_busy(session: Session) -> Refusal | None:
    if session.jobs.busy:
        return Refusal(tr("Wait for the current job."), tr("Another job is running."))
    if session.jobs.game_running:
        return Refusal(tr("The game is running."), tr("Close it first."))
    return None


def _layout_plan(
    session: Session,
    words,
    title: str,
    work: Callable[[JobContext, Any], int],
    stale: Callable[[], object] | None = None,
) -> Proposal:
    """A plan whose answer starts work(ctx, loc) as a job (the old logged-job record: its log and Undo are kept)."""
    loc = session.locations()

    def run(_answer) -> str:
        return session.start(lambda ctx: Moved(count=work(ctx, loc)), title=title)

    return Proposal(words, run, stale)


def _layout_stale() -> object:
    return state.layout_saved(store.load_settings())


@operation("settings.rename_layout", params=Names, result=Moved, kind="plan", writes=True)
def rename_layout(call: Call, p: Names) -> Proposal | Refusal:
    """Offer to rename the game folder pattern and the packages / DLL / shared folders.
    Errors: invalid_names (details.errors), nothing_to_change."""
    session = call.session
    saved = state.layout_saved(store.load_settings())
    given = {k: v for k, v in p.model_dump().items() if v is not None}
    if errors := sp.name_errors({**saved, **given}):
        raise OperationError("invalid_names", next(iter(errors.values())), {"errors": errors})
    names = {k: v for k, v in given.items() if v != saved[k]}
    if not names:
        raise OperationError("nothing_to_change", tr("The names are the ones in use already."))
    if refused := _refusal_if_busy(session):
        return refused
    title = tr("Renaming folders...")
    changes = {tr(state.LAYOUT_LABELS[k]): (saved[k], v) for k, v in names.items()}

    def work(_ctx: JobContext, loc) -> int:
        run_job_value(lambda _l, loc: layout_service.rename_layout(loc, **names), loc, title)
        return 0

    return _layout_plan(session, sp.rename_confirm(changes), title, work, _layout_stale)


@operation("settings.relocate", params=RelocateParams, result=Moved, kind="plan", writes=True)
def relocate(call: Call, p: RelocateParams) -> Proposal | Refusal:
    """Offer to move every profile and mod to a new profiles folder; cancelling its job stops the move with nothing
    changed. Errors: invalid_params."""
    session = call.session
    if not p.folder.strip():
        raise OperationError("invalid_params", tr("Pick a folder."))
    if refused := _refusal_if_busy(session):
        return refused
    new = Path(p.folder)
    count, size = layout_service.profiles_facts(session.locations())
    title = tr("Moving profiles and mods...")

    def work(ctx: JobContext, loc) -> int:
        run_job_value(lambda _l, loc: layout_service.relocate(loc, new, cancel=ctx.cancelled), loc, title)
        return 0

    words = sp.relocate_confirm(str(new), count, size, layout_service.free_bytes(new))
    return _layout_plan(session, words, title, work, lambda: store.load_settings().profiles_root)


@operation("settings.move_all", result=Moved, kind="plan", writes=True)
def move_all(call: Call, p: NoParams) -> Proposal | Refusal:
    """Offer to move every me3 profile of this game that lies outside Bayle's folder into it."""
    session = call.session
    if refused := _refusal_if_busy(session):
        return refused
    found = layout_service.plain_profiles(session.locations())
    if not found:
        return Refusal(tr("Nothing to move"), tr("No profiles are outside Bayle's folder."))
    title = tr("Moving profiles...")

    def work(_ctx: JobContext, loc) -> int:
        return run_job_value(lambda _l, loc: layout_service.move_all(loc, found), loc, title)

    return _layout_plan(session, sp.move_all_confirm([f.stem for f in found]), title, work)


@operation("settings.clear_leftovers", result=Cleared, kind="job")
def clear_leftovers(call: Call, p: NoParams) -> Cleared:
    """Close the hidden copies of the game left running. Allowed while the game runs (that is when it is needed), but
    not beside another writing job."""
    if call.session.jobs.busy:
        raise Busy(tr("Wait for the current job."))
    run_job_value(play_service.job_clear, call.session.locations(), tr("Clearing leftover processes..."))
    return Cleared()
