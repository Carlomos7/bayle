"""The Launch flow (technical specification §8.10, "Launch flow"), without Qt: what happens between pressing Launch
and the game running, in one place, for the pill, Ctrl+L, the menu and a `play <game>` from a second start.

    gate > pending co-op edits > back up saves > stale-merge check > online check > launch

The launch itself is a logged job (services/play) that clears leftover processes, waits for Steam, starts the game,
watches it and, for me3 launches, repairs the saves after it closes. Each step that has to ask the player does so
through `Ports.ask` with a few named choices, and carries on (or stops) from the answer; nothing here blocks, so
the same flow runs under a window or under a test. A step that fails to be sure stops: the game never starts
without its backup, with unrefreshed merged mods, or online with changed game data unless the player said so.

`--play` from a Steam shortcut keeps services.play.play_headless: nothing can ask there."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from bayle.mods import rebuild as mod_merge
from bayle.platform import logging as run_logging
from bayle.platform.text import tr  # job titles only: they are job records (Activity shows them)
from bayle.services import game_checks, profile_mods
from bayle.services import play as core
from bayle.work import jobs
from bayle.work.prompts import Option, Question

from bayle_qt.shell import facts as topbar
from bayle_qt.shell.state import LauncherState

UPDATE_LABEL = "Updating merged mods..."  # the job that rebuilds before Launch (the status text shows it)

# Answers
RETRY, WITHOUT_BACKUP, REBUILD, PLAY_ANYWAY, OFFLINE_INSTEAD, ONLINE_ANYWAY, DETAILS, GO, CANCEL = (
    "retry",
    "without_backup",
    "rebuild",
    "play_anyway",
    "offline_instead",
    "online_anyway",
    "details",
    "go",
    "cancel",
)


Ask = Question  # the flow's name for a fork; it carries a code and facts, the window words it

# The steps before the launch job runs (Ports.progress); the window words them
CHECKING, STARTING, BACKING_UP, CHECKING_MODS, CHECKING_ONLINE = (
    "checking",
    "starting",
    "backing_up",
    "checking_mods",
    "checking_online",
)


class Ports(Protocol):
    """What the flow needs from the shell; the host implements them, tests fake them."""

    def ask(self, ask: Ask, on_answer: Callable[[str], None]) -> None: ...
    def toast(self, code: str, facts: dict | None = None, error: bool = False) -> None:
        """Say something: a code the window words (blocked, launch_cancelled, text: facts["text"] as it is)."""

    def progress(self, step: str) -> None:
        """A step before the launch job is running (BACKING_UP...); "" when the flow is over."""

    def background(self, work: Callable[[], Any], on_result: Callable[[Any], None]) -> None: ...
    def run_job(self, job, label: str, kind: str, on_done: Callable[[bool], None] | None = None) -> None: ...
    def save_pending(self) -> str | None:
        """Save the Seamless settings edited and not written yet; the reason it could not, or None."""

    def show_activity(self) -> None: ...


@dataclass
class Services:
    """The functions the flow calls into; tests replace them."""

    play_options: Callable[..., dict] = core.play_options
    backup: Callable[..., Any] = core.backup_saves_before_play
    play_check: Callable[..., dict | None] = mod_merge.play_check
    update_before_play: Callable[..., Any] = mod_merge.update_before_play
    last_run: Callable[..., dict | None] = mod_merge.last_run
    tool_state: Callable[..., Any] = profile_mods.tool_state
    online_risk: Callable[..., Any] = game_checks.online_risk
    job_play: Callable[..., None] = core.job_play
    job_play_offline: Callable[..., None] = core.job_play_offline
    job_play_vanilla: Callable[..., None] = core.job_play_vanilla


def gate(state: LauncherState, mode: str, problems: tuple[core.Problem, ...] | None = None) -> topbar.Block | None:
    """Why Launch cannot start now, or None when it can: a job or the game running, an unsupported or missing game,
    no profile, a profile with problems (an incomplete managed setup, me3 missing). The pill shows the same reasons."""
    if state.busy:
        return topbar.Block("busy")
    if state.game_running:
        return topbar.Block("running", state.game.name)
    launch_profile = state.launch_profile
    facts = topbar.Facts(
        game=state.game,
        installed=bool(state.locations.game_dir()),
        profile_count=1 if launch_profile else 0,
        problems=tuple(launch_profile.problems()) if launch_profile and problems is None else (problems or ()),
    )
    return topbar.blocked(facts, mode)


@dataclass
class _Run:
    mode: str
    backup: str = core.BACKUP_SKIP  # how the job treats a backup (the flow does it first)
    allow_without_backup: bool = False  # --allow-without-backup: a failed backup does not stop it
    rebuild_chosen: bool = False  # "Rebuild now" was picked
    skip_update: bool = False  # "Launch anyway this once"
    cancelled: bool = False  # "Stop after the rebuild"
    profile: Path | None = None
    confirmed: bool = False  # "Launch Offline" was confirmed
    refused: bool = False  # the fresh check found a reason not to start


class LaunchFlow:
    def __init__(self, state: LauncherState, ports: Ports, services: Services | None = None):
        self.state = state
        self.ports = ports
        self.services = services or Services()
        self.active = False  # a flow is between its first step and the launch job starting
        self._run: _Run | None = None
        self._rebuild_failed: dict[str, tuple] = {}  # profile -> the reasons of the rebuild that failed

    # ---------------------------------------------------------------- start
    def start(self, mode: str, allow_without_backup: bool = False) -> bool:
        """Begin a launch. False (and a toast saying why) when it cannot start now."""
        if self.active:
            return False
        mode = mode if mode in topbar.MODES else topbar.PROFILE
        why = gate(self.state, mode, ())  # the quick reasons first, with no disk reads
        if why:
            self.ports.toast("blocked", asdict(why), error=True)
            return False
        self.active = True
        launch_profile = self.state.launch_profile
        run = self._run = _Run(mode, allow_without_backup=allow_without_backup)
        self.ports.progress(CHECKING)

        def check():  # the profile's disk checks, read fresh now (never a cached answer), off the UI thread
            return tuple(launch_profile.problems()) if launch_profile and mode != topbar.VANILLA else ()

        self.ports.background(check, lambda problems: self._gated(run, mode, problems))
        return not run.refused

    def _gated(self, run: _Run, mode: str, problems: tuple[core.Problem, ...]) -> None:
        """The fresh check is back: the full gate on it, then the flow."""
        why = gate(self.state, mode, problems)
        if why:
            run.refused = True
            self.ports.toast("blocked", asdict(why), error=True)
            self._end()
            return
        launch_profile = self.state.launch_profile
        run.profile = Path(launch_profile.profile) if launch_profile and mode != topbar.VANILLA else None
        self.ports.progress(STARTING)
        self._pending_edits(run)

    def stop_after_rebuild(self) -> None:
        """ "Stop after the rebuild" (spec 1174, owner D6 A): the rebuild finishes (a tool stopped midway could leave
        its files half written), then the game does not start."""
        run = self._run
        if run is None or run.cancelled:
            return
        run.cancelled = True
        self.ports.toast("launch_cancelled_rebuild")

    def _end(self) -> None:
        self.active = False
        self._run = None
        self.ports.progress("")

    def _cancel(self, why: str) -> None:
        run_logging.log(why)
        self._end()

    # ---------------------------------------------------------------- 1. pending co-op edits
    def _pending_edits(self, run: _Run) -> None:
        """Seamless settings edited on Mod Configs and not written apply on launch: they are saved first, and a save
        that fails stops the launch with the reason (an empty password, say). Offline and Vanilla play without
        Seamless, so they save nothing."""
        if run.mode == topbar.PROFILE:
            error = self.ports.save_pending()
            if error:
                self.ports.toast("text", {"text": error}, error=True)
                self._end()
                return
        self._backup(run)

    # ---------------------------------------------------------------- 2. back up saves
    def _backup(self, run: _Run) -> None:
        opts = self.services.play_options(self.state.settings)
        if not opts["play_backup_before"]:
            self._stale(run)
            return
        if run.allow_without_backup:  # a Steam shortcut said so: the job backs up and goes on if that fails
            run.backup = core.BACKUP_ALLOW_FAILURE
            self._stale(run)
            return
        loc = self._locations()
        self.ports.progress(BACKING_UP)

        def work():
            try:
                self.services.backup(loc, required=True)
            except core.BackupBeforePlayFailed as e:
                return e
            except Exception as e:  # anything else is a failed backup too
                return core.BackupBeforePlayFailed([(Path(loc.game.save_dir), str(e))])
            return None

        self.ports.background(work, lambda failed: self._backed_up(run, failed))

    def _backed_up(self, run: _Run, failed) -> None:
        if failed is None:
            self._stale(run)
            return
        ask = Ask(
            "backup_failed",
            {"failed": [f"{p.name}: {why}" for p, why in failed.failed]},
            (Option(RETRY, "primary"), Option(WITHOUT_BACKUP), Option(CANCEL)),
        )

        def answered(key: str) -> None:
            if key == RETRY:
                self._backup(run)
            elif key == WITHOUT_BACKUP:
                run_logging.log(f"warning: starting without a backup of every save, as chosen ({failed})")
                self._stale(run)
            else:
                self._cancel(f"Launch cancelled: a backup before Play failed ({failed})")

        self.ports.ask(ask, answered)

    # ---------------------------------------------------------------- 3. stale merged mods
    def _stale(self, run: _Run) -> None:
        prof = run.profile
        if prof is None or run.skip_update:  # Vanilla uses no mods; "Launch anyway this once" was picked
            self._online(run)
            return
        loc = self._locations()
        self.ports.progress(CHECKING_MODS)

        def work():
            try:
                return self.services.play_check(prof, loc=loc)
            except Exception as e:  # not sure: ask, never start with mods we could not check
                return {"error": str(e)}

        self.ports.background(work, lambda h: self._checked(run, h))

    def _checked(self, run: _Run, h) -> None:
        prof = run.profile
        if h is None:
            self._online(run)
            return
        if prof is None:  # cannot happen: _stale only runs with a profile
            self._online(run)
            return
        if "error" in h:
            self._ask_stale(run, "check_error", "", h["error"])
            return
        reason = (h.get("reasons") or [h.get("text") or ""])[0]  # "": the window's generic "out of date"
        if h.get("blocked"):
            self._ask_stale(run, "blocked", reason, h["blocked"])
            return
        key = tuple(h.get("reasons") or ())
        if self._rebuild_failed.get(str(prof)) == key:
            self._ask_stale(run, "last_failed", reason)
            return
        state = self.services.tool_state(prof, loc=self._locations())
        if state.tool is not None and (state.problem or not state.allowed):
            if state.problem:
                self._ask_stale(run, "tool_problem", reason, state.problem)
            else:
                self._ask_stale(run, "tool_not_allowed", reason, tool=state.tool.label)
            return
        if not self.services.play_options(self.state.settings)["play_update_merge"] and not run.rebuild_chosen:
            self._ask_rebuild(run, reason)
            return
        self._rebuild(run, prof, key, reason)

    def _ask_rebuild(self, run: _Run, reason: str) -> None:
        """Automatic rebuilds are off: Rebuild now / Launch anyway this once / Cancel."""
        ask = Ask(
            "stale_rebuild", {"reason": reason}, (Option(REBUILD, "primary"), Option(PLAY_ANYWAY), Option(CANCEL))
        )

        def answered(key: str) -> None:
            if key == REBUILD:
                run.rebuild_chosen = True
                self._stale(run)
            elif key == PLAY_ANYWAY:
                run.skip_update = True
                self._online(run)
            else:
                self._cancel("Launch cancelled: the merged mods are out of date")

        self.ports.ask(ask, answered)

    def _ask_stale(self, run: _Run, cause: str, reason: str, detail: str = "", tool: str = "") -> None:
        """The merged mods are out of date and cannot be rebuilt now: say so before the game starts. There is no
        setting that skips this. cause: check_error | blocked | last_failed | tool_problem | tool_not_allowed."""
        facts = {"cause": cause, "reason": reason, "detail": detail, "tool": tool}
        ask = Ask("stale_blocked", facts, (Option(PLAY_ANYWAY, "primary"), Option(DETAILS), Option(CANCEL)))

        def answered(key: str) -> None:
            if key == PLAY_ANYWAY:
                run.skip_update = True
                self._online(run)
                return
            if key == DETAILS:
                self.ports.show_activity()
            self._cancel("Launch cancelled: the merged mods are out of date")

        self.ports.ask(ask, answered)

    def _rebuild(self, run: _Run, prof: Path, key: tuple, reason: str) -> None:
        services = self.services

        def job(_launch_profile, job_loc):
            run_logging.start_log("launcher: update merged mods before Play", job_loc.game.key)
            try:
                out = services.update_before_play(prof, run_logging.log, loc=job_loc)
                if out is not None:
                    run_logging.set_undo(out.get("undo"))
                    run_logging.log(f"done: merged mods updated by {out['backend']}; {out['profile_note']}")
                else:
                    run_logging.log("done: the merged mods were already up to date")
            except mod_merge.MergeError as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.ports.progress("")
        self.ports.run_job(job, UPDATE_LABEL, "update", lambda ok: self._rebuilt(run, prof, key, ok))

    def _rebuilt(self, run: _Run, prof: Path, key: tuple, ok: bool) -> None:
        if run.cancelled:
            self._cancel("Launch cancelled while the merged mods were rebuilt")
            return
        if ok:
            self._rebuild_failed.pop(str(prof), None)
            self._stale(run)  # checked again: it must now be current
            return
        self._rebuild_failed[str(prof)] = key
        failed = self.services.last_run(prof) or {}
        ask = Ask(
            "rebuild_failed",
            {"message": failed.get("message") or ""},
            (Option(PLAY_ANYWAY, "primary"), Option(DETAILS), Option(CANCEL)),
        )

        def answered(choice: str) -> None:
            if choice == PLAY_ANYWAY:
                run.skip_update = True
                self._online(run)
                return
            if choice == DETAILS:
                self.ports.show_activity()
            self._cancel("Launch cancelled: the merged mods could not be updated")

        self.ports.ask(ask, answered)

    # ---------------------------------------------------------------- 4. online check
    def _online(self, run: _Run) -> None:
        """A profile that starts the game online with changed game data is asked about first; Offline and Vanilla
        never reach the network with changed data, so they skip the check."""
        prof = run.profile
        if run.mode != topbar.PROFILE or prof is None:
            self._launch(run)
            return
        loc = self._locations()
        self.ports.progress(CHECKING_ONLINE)

        def work():
            try:
                return self.services.online_risk(prof, loc)
            except Exception as e:  # not sure: treat it as a risk and ask
                return e

        self.ports.background(work, lambda risk: self._online_checked(run, risk))

    def _online_checked(self, run: _Run, risk) -> None:
        if risk is None:
            self._launch(run)
            return
        ask = Ask(
            "online_risk", {}, (Option(OFFLINE_INSTEAD, "primary"), Option(ONLINE_ANYWAY, "danger"), Option(CANCEL))
        )

        def answered(key: str) -> None:
            if key == OFFLINE_INSTEAD:
                run.mode = topbar.OFFLINE
                self._launch(run)
            elif key == ONLINE_ANYWAY:
                self._launch(run)
            else:
                self._cancel("Launch cancelled: the profile would have gone online with changed game data")

        self.ports.ask(ask, answered)

    # ---------------------------------------------------------------- 5. launch
    def _launch(self, run: _Run) -> None:
        settings = self.state.settings
        if run.mode == topbar.OFFLINE and not settings.offline_skip_confirm and not run.confirmed:
            facts = {
                "strip_overhaul": bool(settings.offline_strip_overhaul),
                "start_steam": bool(settings.offline_start_steam),
            }
            ask = Ask("offline_confirm", facts, (Option(GO, "primary"), Option(CANCEL)))

            def answered(key: str) -> None:
                if key != GO:
                    self._cancel("Launch cancelled")
                    return
                run.confirmed = True
                self._launch(run)

            self.ports.ask(ask, answered)
            return
        backup = run.backup
        services = self.services
        if run.mode == topbar.VANILLA:

            def job(launch_profile, job_loc):
                services.job_play_vanilla(launch_profile, job_loc, backup=backup, notice=jobs.notice)

            label = tr("Starting {game}...").format(game=self.state.game.name)
        elif run.mode == topbar.OFFLINE:

            def job(launch_profile, job_loc):
                services.job_play_offline(
                    launch_profile,
                    job_loc,
                    strip_overhaul=settings.offline_strip_overhaul,
                    start_steam=settings.offline_start_steam,
                    backup=backup,
                    notice=jobs.notice,
                )

            label = tr("Starting offline...")
        else:

            def job(launch_profile, job_loc):
                services.job_play(launch_profile, job_loc, backup=backup, notice=jobs.notice)

            label = tr("Starting...")
        self._end()
        self.ports.run_job(job, label, "launch")

    # ---------------------------------------------------------------- helpers
    def _locations(self):
        """The game's locations with the save files the profile in use names."""
        launch_profile = self.state.launch_profile
        return launch_profile.locations() if launch_profile is not None else self.state.locations
