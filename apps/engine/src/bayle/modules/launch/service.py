"""Games, profiles and Play for one engine: the games the launcher knows and which one is current, the profiles of the
current game and the one Play remembers, and Play itself (online, offline, vanilla) as a job that asks the client
mid-way (work.prompts.Question) and goes on with the key it answers with. Returns data and OperationError codes,
never wording: the client words them.

The questions Play asks, with the keys that answer them (cancel always ends the job as cancelled): backup_failed
(retry | without_backup), stale_blocked / rebuild_failed (play_anyway), stale_rebuild (rebuild | play_anyway),
online_risk (offline_instead | online_anyway), offline_confirm (go)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.adapters.system import logging as run_logging
from bayle.errors import Busy, Cancelled, OperationError
from bayle.modules import ports
from bayle.modules.games import catalog
from bayle.modules.games import ports as game_ports
from bayle.modules.games.locate import Locations
from bayle.modules.launch import game_checks
from bayle.modules.launch import play as play_service
from bayle.modules.mods import profile_edit
from bayle.modules.mods import rebuild as mod_merge
from bayle.work.jobs import JobContext, JobManager, notice
from bayle.work.prompts import Option, Question
from bayle.work.runner import run_job_value

MODES = ("profile", "offline", "vanilla")


@dataclass(frozen=True)
class GameFacts:
    key: str
    name: str
    ready: bool  # the launcher fully supports it (the others show a placeholder)
    installed: str | None  # the game's folder, None when it is not on this PC
    current: bool
    profile: str | None  # the setup Play last used for it
    last_run_build: str | None  # the exe's build stamp the last Play saw


@dataclass(frozen=True)
class ProfileFacts:
    profile: str  # the .me3 path
    kind: str  # me3 | manifest (an overhaul installer's setup)
    source: str  # what is remembered and sent back to launch: the .me3 path, or the installer's manifest
    name: str
    active: bool
    problems: tuple[play_service.Problem, ...]


@dataclass(frozen=True)
class LaunchCheck:
    problems: tuple[play_service.Problem, ...]
    warnings: tuple[play_service.Problem, ...]
    game_running: bool
    busy: bool
    installed: bool


class LaunchService:
    """jobs: the engine's JobManager (Play is a writing job). locations: the current game's Locations (None: no game
    selected). select_game(game): makes a game the current one (runtime.bootstrap.Engine.select_game); a server built
    without it refuses to switch (not_available)."""

    def __init__(
        self,
        jobs: JobManager,
        locations: Callable[[], Locations | None],
        select_game: Callable[[catalog.Game], Locations] | None = None,
    ) -> None:
        self._jobs, self._locations, self._select = jobs, locations, select_game

    def _loc(self) -> Locations:
        try:
            loc = self._locations()
        except OperationError:
            loc = None
        if loc is None:
            raise OperationError("no_game", "No game is selected.")
        return loc

    # ---- games
    def games(self) -> list[GameFacts]:
        loc, settings = self._loc(), ports.load_settings()
        return [
            GameFacts(
                g.key,
                g.name,
                g.ready,
                _text(game_ports.installed_dir(g)),
                g is loc.game,
                play_service.remembered_profile(settings, g),
                settings.run_state.get(g.key, {}).get("exe_build"),
            )
            for g in catalog.GAMES
        ]

    def select_game(self, key: str) -> list[GameFacts]:
        """Make the game current and remember it for the next start. Raises unknown_game, not_available, busy."""
        game = catalog.resolve(key)
        if game is None:
            raise OperationError("unknown_game", f"There is no game called {key}.", {"key": key})
        if self._select is None:
            raise OperationError("not_available", "This server cannot switch games.")
        if self._jobs.busy:
            raise Busy("Wait for the current job to finish.", {"reason": "job"})
        ports.save_settings(game=game.key)
        self._select(game)
        return self.games()

    # ---- profiles
    def _launch_profile(self, source: str) -> play_service.LaunchProfile:
        found = play_service.launch_profile_from_path(source, self._loc()) if source else None
        if found is None:
            raise OperationError("not_found", "That profile is not there.", {"source": source})
        return found

    def profiles(self) -> list[ProfileFacts]:
        """The current game's profiles (+ the remembered one, + installer setups), as Play offers them."""
        loc = self._loc()
        remembered = play_service.remembered_profile(None, loc.game)
        found = play_service.discover(remembered, loc) if loc.game.ready else []
        return [
            ProfileFacts(
                p.profile,
                p.kind,
                p.source,
                p.label,
                play_service.same_source(p.source, remembered),
                tuple(p.problems()),
            )
            for p in found
        ]

    def set_active(self, source: str) -> None:
        """Remember the setup Play uses next ("" forgets it). Raises not_found."""
        game = self._loc().game
        if source:
            play_service.remember_profile(self._launch_profile(source).source, game)
        else:
            play_service.forget_profile(game)

    def create_profile(self, name: str) -> Path:
        """A new empty profile in me3's folder for the current game. Raises invalid_value, create_failed, busy."""
        if not name.strip():
            raise OperationError("invalid_value", "A profile needs a name.")
        if self._jobs.busy:
            raise Busy("Wait for the current job to finish.", {"reason": "job"})
        loc = self._loc()
        try:
            folder = loc.me3_profiles_dir()
            if not folder:
                raise RuntimeError("me3's profile folder is unknown on this PC.")
            return profile_edit.create_profile(folder, name, game=loc.game.key)
        except Exception as e:
            raise OperationError("create_failed", str(e)) from e

    # ---- Play
    def check(self, mode: str, source: str = "") -> LaunchCheck:
        """Why Play cannot start now, read fresh from the disk. Raises invalid_params (mode), not_found."""
        _mode(mode)
        loc = self._loc()
        launch = None if mode == "vanilla" else self._launch_profile(source)
        return LaunchCheck(
            tuple(launch.problems()) if launch else (),
            tuple(launch.warnings()) if launch else (),
            loc.game_running(),
            self._jobs.busy,
            bool(loc.game_dir()),
        )

    def play(self, mode: str, source: str = "", allow_without_backup: bool = False) -> str:
        """Start Play as a job; its id. The job asks (prompt events) before it launches; its result is {"mode"}.
        Raises invalid_params (mode), not_found, cannot_launch (details: reason game_unsupported | not_installed |
        game_running | problems), busy."""
        got = self.check(mode, source)
        loc = self._loc()
        reason = (
            "game_unsupported"
            if not loc.game.ready
            else "not_installed"
            if not got.installed
            else "game_running"
            if got.game_running
            else "problems"
            if got.problems
            else ""
        )
        if reason:
            details = {"reason": reason, "problems": [p.code for p in got.problems]}
            raise OperationError("cannot_launch", "Play cannot start now.", details)
        launch = None if mode == "vanilla" else self._launch_profile(source)
        game_loc = launch.locations() if launch else loc
        return self._jobs.start(
            lambda ctx: run_job_value(
                lambda _launch, job_loc: self._flow(ctx, mode, launch, job_loc, allow_without_backup),
                game_loc,
                f"Play ({mode})",
            ),
            title=f"Starting {loc.game.name}...",
            quiet=True,
        )

    # ---- the job
    @staticmethod
    def _ask(ctx: JobContext, code: str, facts: dict[str, Any], *options: tuple[str, str]) -> str:
        """Ask and wait; a cancel answer (or Stop) ends the job as cancelled."""
        key = ctx.ask(Question(code, facts, (*(Option(k, r) for k, r in options), Option("cancel"))))  # type: ignore[arg-type]
        if key == "cancel" or ctx.cancelled():
            raise Cancelled("Play was cancelled.")
        return key

    def _flow(
        self,
        ctx: JobContext,
        mode: str,
        launch: play_service.LaunchProfile | None,
        loc: Locations,
        allow_without_backup: bool,
    ) -> dict[str, str]:
        opts, settings = play_service.play_options(), ports.load_settings()
        backup = play_service.BACKUP_SKIP
        if opts["play_backup_before"]:
            if allow_without_backup:
                backup = play_service.BACKUP_ALLOW_FAILURE
            else:
                while True:
                    try:
                        play_service.backup_saves_before_play(loc, required=True)
                        break
                    except play_service.BackupBeforePlayFailed as e:
                        failed = [f"{p.name}: {why}" for p, why in e.failed]
                        if (
                            self._ask(
                                ctx,
                                "backup_failed",
                                {"failed": failed},
                                ("retry", "primary"),
                                ("without_backup", "normal"),
                            )
                            == "without_backup"
                        ):
                            break
        if launch is not None:
            self._merged(ctx, Path(launch.profile), loc, opts)
            if mode == "profile" and game_checks.online_risk(Path(launch.profile), loc) is not None:
                asked = self._ask(ctx, "online_risk", {}, ("offline_instead", "primary"), ("online_anyway", "danger"))
                mode = "offline" if asked == "offline_instead" else mode
        if mode == "offline" and not settings.offline_skip_confirm:
            self._ask(
                ctx,
                "offline_confirm",
                {"strip_overhaul": settings.offline_strip_overhaul, "start_steam": settings.offline_start_steam},
                ("go", "primary"),
            )
        ctx.raise_if_cancelled()
        if mode == "vanilla":
            play_service.job_play_vanilla(None, loc, backup=backup, notice=notice)
        elif mode == "offline":
            play_service.job_play_offline(
                launch,
                loc,
                strip_overhaul=settings.offline_strip_overhaul,
                start_steam=settings.offline_start_steam,
                backup=backup,
                notice=notice,
            )
        else:
            assert launch is not None
            play_service.job_play(launch, loc, backup=backup, notice=notice)
        return {"mode": mode}

    def _merged(self, ctx: JobContext, profile: Path, loc: Locations, opts: dict) -> None:
        """Out-of-date merged mods: rebuild them first (or ask), as Play does."""
        found = mod_merge.play_check(profile, loc=loc)
        if found is None:
            return
        reason = (found.get("reasons") or [found.get("text") or ""])[0]
        if found.get("blocked"):
            self._ask(ctx, "stale_blocked", {"reason": reason, "detail": found["blocked"]}, ("play_anyway", "primary"))
            return
        if not opts["play_update_merge"]:
            asked = self._ask(
                ctx, "stale_rebuild", {"reason": reason}, ("rebuild", "primary"), ("play_anyway", "normal")
            )
            if asked == "play_anyway":
                return
        try:
            mod_merge.update_before_play(profile, run_logging.log, loc=loc)
        except mod_merge.MergeError as e:
            self._ask(ctx, "rebuild_failed", {"message": str(e)}, ("play_anyway", "primary"))


def _mode(mode: str) -> None:
    if mode not in MODES:
        raise OperationError("invalid_params", f"{mode} is not a way to play.", {"modes": list(MODES)})


def _text(path: Path | None) -> str | None:
    return None if path is None else str(path)
