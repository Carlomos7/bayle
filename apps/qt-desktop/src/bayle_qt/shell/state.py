"""What the shell knows about the launcher right now, without Qt: the Engine, the game, its setups (the profiles
Launch can use), the one in use, and whether a job or the game is running. The shell's host owns one; the top bar's
presenter, the Launch flow and the menu read it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from bayle.adapters.system import logging as run_logging
from bayle.adapters.system.logging import JobStore
from bayle.modules.games import catalog as games
from bayle.modules.launch import play as core
from bayle.modules.mods.service import migrate_profile_folders
from bayle.modules.settings.service import load_settings, save_settings
from bayle.runtime.startup import StartupStep
from bayle.work.jobs import JobManager


class Context(Protocol):
    """The part of runtime.bootstrap.Engine the shell needs (the ui layer cannot import the runtime, which sits above
    it). A test's light context provides the same: its own job manager and plans, no activity log (None: the records
    are in jobs.jsonl), and the start-up steps."""

    game: games.Game
    settings: Any
    locations: Any
    data_dir: Path
    jobs: JobManager

    @property
    def activity(self) -> JobStore | None: ...

    def startup(self, profile: Callable[[], Path | None]) -> list[StartupStep]: ...

    def select_game(self, game: games.Game | str) -> Any: ...
    def note_profile_saves(self, names) -> Any: ...
    def reload_settings(self) -> Any: ...
    def start_imports(self) -> Any: ...


_MIGRATED: set[str] = set()


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
        if g.ready and g.key not in _MIGRATED:  # once per game a session: the shared library's profiles move out first
            _MIGRATED.add(g.key)
            try:
                migrate_profile_folders(self.locations)
            except Exception as e:  # nothing changed; it tries again at the next start
                run_logging.log(f"warning: profiles not moved into their own folders yet: {e}")
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
