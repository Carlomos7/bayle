"""What the shell knows about the launcher right now, without Qt: the app context, the game, its setups (the profiles
Launch can use), the one in use, and whether a job or the game is running. The shell's host owns one; the top bar's
presenter, the Launch flow and the menu read it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from roundtable_souls.game import catalog as games
from roundtable_souls.services import play as core
from roundtable_souls.services.settings import load_settings, save_settings


class Context(Protocol):
    """The part of app.AppContext the shell uses (the ui layer cannot import app, which sits above it)."""

    game: games.Game
    settings: Any
    locations: Any
    data_dir: Path

    def select_game(self, game: games.Game | str) -> Any: ...
    def note_setup_saves(self, names) -> Any: ...
    def reload_settings(self) -> Any: ...
    def start_imports(self) -> Any: ...


class LauncherState:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.setups: list[core.Setup] = []
        self.setup: core.Setup | None = None
        self.busy = False
        self.job_label = ""  # what the running logged job does ("Installing X...")
        self.job_kind = ""  # "" | "launch" | "update" | "other"
        self.game_running = False
        self.reload_setups()

    # ---- what the context holds
    @property
    def game(self) -> games.Game:
        return self.ctx.game

    @property
    def settings(self):
        return self.ctx.settings

    @property
    def locations(self):
        return self.ctx.locations

    # ---- the setups
    def reload_setups(self, select: str | None = None) -> None:
        """Find the game's setups again and pick `select`, else the one Launch used last, else the first."""
        g = self.game
        remembered = core.remembered_setup(self.settings, g)
        self.setups = core.discover(select or remembered, self.locations) if g.ready else []
        pick = select or remembered
        index = next((i for i, s in enumerate(self.setups) if core.same_source(s.source, pick)), 0)
        self.choose(index if self.setups else -1)

    def choose(self, index: int) -> None:
        """Make the index'th setup the current one (-1: none). The choice is remembered per game, and the save files
        the setup names are told to the locations (a different setup can mean different files)."""
        s = self.setups[index] if 0 <= index < len(self.setups) else None
        self.setup = s
        names = core.setup_saves(s, self.game)
        self.ctx.note_setup_saves({k: names[k] for k in ("standard", "coop")})
        if s is not None and not core.same_source(core.remembered_setup(self.settings, self.game), s.source):
            core.remember_setup(s.source, s.game)
            self.ctx.settings = load_settings()

    @property
    def index(self) -> int:
        s = self.setup
        return next((i for i, x in enumerate(self.setups) if x is s), -1)

    def select_game(self, game: games.Game, remember: bool = False) -> None:
        """Point everything at another game: its location overrides, its setups."""
        if remember:
            save_settings(game=game.key)  # the tab the window opens on next time
        self.ctx.select_game(game)
        self.game_running = False
        self.reload_setups()

    def profile_path(self) -> Path | None:
        s = self.setup
        return Path(s.profile) if s and Path(s.profile).is_file() else None
