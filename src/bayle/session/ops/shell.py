"""The shell's operations: the top bar's snapshot, the game and profile in use, Launch, the launcher's updates, me3,
support logs and Steam shortcuts. They act on the session's Shell service (session.shell.service)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from bayle.platform.text import tr
from bayle.services.errors import OperationError
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry
from bayle.session.shell import launch as launch_flow
from bayle.session.shell.service import Shell
from bayle.views import topbar
from bayle.views.shell import ShellState


def _missing() -> Shell:
    raise OperationError("no_shell", "This session has no shell: no game or profile is in use.")


def shell_of(session: Session) -> Shell:
    return session.service("shell", _missing)


Mode = Literal["profile", "offline", "vanilla"]


class GameParams(Params):
    key: str
    remember: bool = True


class IndexParams(Params):
    index: int


class ModeParams(Params):
    mode: Mode


class PathParams(Params):
    path: str


class FolderParams(Params):
    folder: str


class NewProfileParams(Params):
    name: str = ""
    include_seamless: bool = False


class LaunchParams(Params):
    mode: Mode | None = None  # None: the one remembered for the game
    allow_without_backup: bool = False


class CheckParams(Params):
    force: bool = True


class NoticeParams(Params):
    notice_id: str


class NoticeActionParams(NoticeParams):
    key: str


class GameSet(Result):
    game: str


class Picked(Result):
    changed: bool
    index: int


class ModeSet(Result):
    mode: str


class Started(Result):
    job_id: str  # follow it on the event stream or GET /v1/jobs/{job_id}


class Launched(Result):
    started: bool  # the flow began; its questions arrive as `prompt` events, answered on POST /v1/prompts/{id}


class SavedLogs(Result):
    path: str


class Shortcuts(Result):
    changed: list[str]


class Me3(Result):
    facts: dict[str, Any]


class Done(Result):
    ok: bool = True


@registry.page("shell", view=ShellState)
def snapshot(session: Session) -> ShellState:
    return shell_of(session).snapshot()


@operation("shell.set_game", params=GameParams, result=GameSet, kind="command", writes=True)
def set_game(call: Call, p: GameParams) -> GameSet:
    shell = shell_of(call.session)
    shell.set_game(p.key, p.remember)  # Busy while a job runs
    return GameSet(game=shell.state.game.key)


@operation("shell.pick_profile", params=IndexParams, result=Picked, kind="command", writes=True)
def pick_profile(call: Call, p: IndexParams) -> Picked:
    shell = shell_of(call.session)
    return Picked(changed=shell.pick_profile(p.index), index=shell.state.index)


@operation("shell.add_profile", params=PathParams, result=Picked, kind="command", writes=True)
def add_profile(call: Call, p: PathParams) -> Picked:
    shell = shell_of(call.session)
    if not shell.add_profile(Path(p.path)):
        raise OperationError(
            "not_a_profile", tr("That file is not a .me3 profile, and it is not a launcher installation.json.")
        )
    return Picked(changed=True, index=shell.state.index)


@operation("shell.new_profile", params=NewProfileParams, result=Started, kind="command", writes=True)
def new_profile(call: Call, p: NewProfileParams) -> Started:
    return Started(job_id=shell_of(call.session).new_profile(p.name, p.include_seamless))


@operation("shell.set_mode", params=ModeParams, result=ModeSet, kind="command", writes=True)
def set_mode(call: Call, p: ModeParams) -> ModeSet:
    shell = shell_of(call.session)
    shell.set_mode(p.mode)
    return ModeSet(mode=shell.mode())


@operation("shell.launch", params=LaunchParams, result=Launched, kind="command", writes=True)
def launch(call: Call, p: LaunchParams) -> Launched:
    """Begin the Launch flow. Raises cannot_launch (with the reason) when it cannot start now."""
    shell = shell_of(call.session)
    mode = p.mode or shell.mode()
    why = launch_flow.gate(shell.state, mode if mode in topbar.MODES else topbar.PROFILE)
    if why:
        raise OperationError("cannot_launch", why)
    return Launched(started=shell.launch(p.mode, p.allow_without_backup))


@operation("shell.clear_dead_processes", result=Started, kind="command", writes=True)
def clear_dead_processes(call: Call, p: NoParams) -> Started:
    return Started(job_id=shell_of(call.session).clear_dead_processes())


@operation("shell.me3", result=Me3, kind="command", writes=True)
def me3(call: Call, p: NoParams) -> Me3:
    """me3's version, folders and the latest release (asks me3 and, once a day, the network; caches what it learns)."""
    return Me3(facts=shell_of(call.session).me3_facts())


@operation("shell.save_logs", params=FolderParams, result=SavedLogs, kind="command", writes=True)
def save_logs(call: Call, p: FolderParams) -> SavedLogs:
    return SavedLogs(path=str(shell_of(call.session).save_logs(Path(p.folder))))


@operation("shell.steam_shortcuts", result=Shortcuts, kind="command", writes=True)
def steam_shortcuts(call: Call, p: NoParams) -> Shortcuts:
    return Shortcuts(changed=shell_of(call.session).point_steam_shortcuts())


@operation("shell.check_updates", params=CheckParams, result=Done, kind="command")
def check_updates(call: Call, p: CheckParams) -> Done:
    shell_of(call.session).updates.check(force=p.force)
    return Done()


@operation("shell.update_action", params=NoticeActionParams, result=Done, kind="command", writes=True)
def update_action(call: Call, p: NoticeActionParams) -> Done:
    shell_of(call.session).updates.notice_action(p.notice_id, p.key)
    return Done()


@operation("shell.dismiss_notice", params=NoticeParams, result=Done, kind="command")
def dismiss_notice(call: Call, p: NoticeParams) -> Done:
    shell_of(call.session).updates.dismiss(p.notice_id)
    return Done()
