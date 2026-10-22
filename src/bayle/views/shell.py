"""The shell's page (top bar): what the Launch pill, the status text and the drop-downs show, as one snapshot. The
words come from views.topbar; this only gathers them with the update notices, so a client reads one thing."""

from __future__ import annotations

from dataclasses import dataclass, field

from bayle.views import topbar
from bayle.views.settings import UpdateNotice


@dataclass(frozen=True)
class UpdatesState:
    line: str = ""
    tone: str = "muted"
    checking: bool = False
    notices: tuple[UpdateNotice, ...] = ()


@dataclass(frozen=True)
class ShellState:
    game: str
    game_name: str
    game_ready: bool
    games: tuple[topbar.GameEntry, ...]
    profiles: tuple[str, ...]
    profile_index: int
    mode: str
    modes: tuple[dict, ...]
    pill: topbar.Pill
    status: topbar.Status
    game_running: bool
    unseen: int = 0
    updates: UpdatesState = field(default_factory=UpdatesState)


def shell_state(
    facts: topbar.Facts,
    *,
    labels: list[str],
    index: int,
    installed: dict[str, bool],
    unseen: int,
    updates: dict,
) -> ShellState:
    """updates: UpdateFlow.state() (line, tone, checking, notices)."""
    return ShellState(
        game=facts.game.key,
        game_name=facts.game.name,
        game_ready=facts.game.ready,
        games=tuple(topbar.game_menu(facts.game, installed)),
        profiles=tuple(labels),
        profile_index=index,
        mode=facts.mode,
        modes=tuple(topbar.mode_menu(facts.mode)),
        pill=topbar.pill(facts),
        status=topbar.status(facts),
        game_running=facts.game_running,
        unseen=unseen,
        updates=UpdatesState(updates["line"], updates["tone"], bool(updates["checking"]), tuple(updates["notices"])),
    )
