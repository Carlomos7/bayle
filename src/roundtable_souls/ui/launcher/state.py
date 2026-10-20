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
    def note_profile_saves(self, names) -> Any: ...
    def reload_settings(self) -> Any: ...
    def start_imports(self) -> Any: ...


class LauncherState:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.launch_profiles: list[core.LaunchProfile] = []
        self.launch_profile: core.LaunchProfile | None = None
        self.busy = False
        self.job_label = ""  # what the running logged job does ("Installing X...")
        self.job_kind = ""  # "" | "launch" | "update" | "other"
        self.game_running = False
        self.reload_profiles()

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
    def reload_profiles(self, select: str | None = None) -> None:
        """Find the game's setups again and pick `select`, else the one Launch used last, else the first."""
        g = self.game
        remembered = core.remembered_profile(self.settings, g)
        self.launch_profiles = core.discover(select or remembered, self.locations) if g.ready else []
        pick = select or remembered
        index = next((i for i, s in enumerate(self.launch_profiles) if core.same_source(s.source, pick)), 0)
        self.choose(index if self.launch_profiles else -1)

    def choose(self, index: int) -> None:
        """Make the index'th setup the current one (-1: none). The choice is remembered per game, and the save files
        the setup names are told to the locations (a different setup can mean different files)."""
        s = self.launch_profiles[index] if 0 <= index < len(self.launch_profiles) else None
        self.launch_profile = s
        names = core.profile_saves(s, self.game)
        self.ctx.note_profile_saves({k: names[k] for k in ("standard", "coop")})
        if s is not None and not core.same_source(core.remembered_profile(self.settings, self.game), s.source):
            core.remember_profile(s.source, s.game)
            self.ctx.settings = load_settings()

    @property
    def index(self) -> int:
        s = self.launch_profile
        return next((i for i, x in enumerate(self.launch_profiles) if x is s), -1)

    def select_game(self, game: games.Game, remember: bool = False) -> None:
        """Point everything at another game: its location overrides, its setups."""
        if remember:
            save_settings(game=game.key)  # the tab the window opens on next time
        self.ctx.select_game(game)
        self.game_running = False
        self.reload_profiles()

    def profile_path(self) -> Path | None:
        s = self.launch_profile
        return Path(s.profile) if s and Path(s.profile).is_file() else None
