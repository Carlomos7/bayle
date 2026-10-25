"""The shell behind the Session (technical specification §8.10; backend plan WP19): the game and its profiles
(LauncherState), the job bookkeeping the top bar shows, the Launch flow, the game watch, the launcher's update flow,
me3 facts and the start-up sequence. No Qt: the window and the HTTP layer both drive this and follow it on the event
bus (`game.state`, `invalidated`, `notice`, `navigate`, `prompt` and the job events).

Shell builds the program's one Session on the Engine's job manager, bus and plans (runtime.bootstrap), and sets the
writes gate (a running game refuses writing jobs) and its bookkeeping on that manager. Activity (services.activity) runs
on the same manager and the Engine's activity log. A test's light context provides the same parts. Who owns start-up: whoever hosts the Shell calls `startup()` once, which runs
the Engine's start-up steps; nothing else recovers on its own."""

from __future__ import annotations

import datetime
import shutil
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bayle.config.app_paths import data_dir
from bayle.errors import Busy, OperationError
from bayle.game import catalog as games
from bayle.game.discovery import installed_dir
from bayle.platform import desktop
from bayle.platform import logging as run_logging
from bayle.services import features
from bayle.services import play as core
from bayle.services.mods import me3_facts
from bayle.services.settings import load_settings, save_game_settings
from bayle.session.startup import StepReport, recover_profile, run_steps
from bayle.work.jobs import JobManager

from bayle_qt.shell import facts as topbar
from bayle_qt.shell import launch
from bayle_qt.shell.background import Background, ThreadBackground
from bayle_qt.shell.ports import EventPorts
from bayle_qt.shell.state import Context, LauncherState
from bayle_qt.shell.updates import Say, UpdateFlow
from bayle_qt.shell.watch import GameWatch
from bayle_qt.text import tr
from bayle_qt.updater import inno as migration

# A job's log lines that say how a launch is going: the status text shows the newest one while the job runs.
PROGRESS_LINES = (
    "steam:",
    "launching",
    "game ",
    "regulation",
    "done:",
    "password",
    "no dead",
    "dead ",
    "scaling",
    "applied",
)
KEEP_KINDS = 100


class Shell:
    def __init__(
        self,
        ctx: Context,
        *,
        background: Background | None = None,
        restart: Callable[[Any], None] | None = None,
        open_url: Callable[[str], None] = desktop.open_path,
    ):
        """background: where the watch, the update flow and the flow's steps run (the window passes one whose results
        arrive on its UI thread). restart(prepared): apply a downloaded update by restarting (the window's close
        rules decide)."""
        self.state = LauncherState(ctx)
        self.background: Background = background or ThreadBackground()
        self.step = ""  # the Launch flow's step code before its job runs (launch.BACKING_UP...)
        self.job_detail = ""  # the newest line of the running job that says how it is going
        self.steam_bad = False
        self.dead_shells = 0
        self.failed_job = ""  # a job that failed and was not looked at yet
        self.unseen = 0  # failed jobs since Activity was last looked at (the rail badge)
        self.me3_note = ""
        self._me3_said = False
        self.checks_late = False  # the window: the disk checks are taking a while
        self.coop_unsaved: Callable[[], bool] = lambda: False  # the window: Seamless settings edited, not saved
        self.save_pending: Callable[[], str | None] = lambda: None  # the window: save them, or why it could not
        self.kinds: dict[str, str] = {}  # job id -> "launch" | "update" | "other" | "page"
        self._titles: dict[str, str] = {}
        self._done_calls: dict[str, Callable[[bool], None]] = {}
        self._next = threading.local()
        self._slow: tuple[tuple, tuple, tuple, dict[str, bool]] | None = None
        self.jobs: JobManager = ctx.jobs
        # the manager is made before the shell, whose state its gates and observer read
        self.jobs.attach(
            game_running=lambda: self.state.game_running, external_busy=lambda: self.flow.active, observer=self._observe
        )
        self.bus = self.jobs.bus
        self.features = features.build(self.jobs, ctx.activity, lambda: self.state.locations)
        self.activity, self.settings, self.saves = self.features.activity, self.features.settings, self.features.saves
        self._startup_steps = ctx.startup(self.state.profile_path)
        self.flow = launch.LaunchFlow(self.state, EventPorts(self))
        self.updates = UpdateFlow(
            self.background,
            lambda: self.state.settings,
            lambda said, kind: self.say(said.code, said.facts, error=kind == "error"),
            self.cannot_update,
            restart or (lambda _prepared: None),
            open_url,
        )
        self.updates.watch(lambda: self.invalidate("updates"))
        self.watch = GameWatch(
            self.background, lambda: self.state.locations, self._on_running, self._on_steam, self._on_shells
        )

    # ---------------------------------------------------------------- events out
    def invalidate(self, *what: str) -> None:
        """Something a client shows changed: it reads that again (what: shell, pages, updates, game...)."""
        self.bus.publish("invalidated", {"what": list(what)})

    def notice(self, text: str, error: bool = False, details: bool = False) -> None:
        """Say something to the player. details: the job log has more (the window offers a Details button)."""
        self.bus.publish("notice", {"text": text, "error": error, "details": details})

    def say(self, code: str, facts: dict | None = None, error: bool = False) -> None:
        """Say something as a code and facts: the window words it (the event carries no text)."""
        self.bus.publish("notice", {"text": "", "code": code, "facts": facts or {}, "error": error, "details": False})

    def navigate(self, page: str) -> None:
        self.bus.publish("navigate", {"page": page})

    def _game_state(self) -> None:
        self.bus.publish(
            "game.state",
            {
                "game": self.state.game.key,
                "running": self.state.game_running,
                "steam_problem": self.steam_bad,
                "dead_shells": self.dead_shells,
            },
        )

    # ---------------------------------------------------------------- state
    @property
    def busy(self) -> bool:
        return self.state.busy or self.flow.active or self.jobs.busy

    # ---------------------------------------------------------------- jobs
    def start(
        self,
        job,
        title: str,
        kind: str = "other",
        *,
        external: bool = False,
        on_done: Callable[[bool], None] | None = None,
    ) -> str:
        """Run job(launch_profile, loc) as a logged job of the shell. Raises Busy: a job runs, the Launch flow is between
        steps (unless external: it is the flow), or the game runs (nothing but clearing leftover processes then).
        on_done(ok) comes through the background after the shell has caught up with the job's end."""
        st = self.state
        lp = st.launch_profile
        loc = lp.locations() if lp is not None else st.locations
        self._next.v = (kind, on_done)
        try:
            return self.jobs.start_logged(job, lp, loc, title, external=external, while_game_runs=job is core.job_clear)
        finally:
            self._next.v = None

    def _observe(self, type: str, data: dict, job_id: str | None) -> None:
        """Every job event, before clients see it: the top bar's bookkeeping lives here, so a client that reads the
        shell after an event finds it current."""
        if job_id is None:
            return
        st = self.state
        if type == "started":
            kind, on_done = getattr(self._next, "v", None) or ("other", None)
            self.kinds[job_id] = kind
            while len(self.kinds) > KEEP_KINDS:
                del self.kinds[next(iter(self.kinds))]
            if on_done is not None:
                self._done_calls[job_id] = on_done
            self._titles[job_id] = title = str(data.get("title") or "")
            st.busy, st.job_label, st.job_kind, self.job_detail, self.step = True, title, kind, "", ""
        elif type == "log":
            shown = str(data.get("text") or "").strip()
            if st.busy and shown.lower().startswith(PROGRESS_LINES):
                self.job_detail = shown.splitlines()[0][:120]
        elif type == "progress":
            self.job_detail = str(data.get("label") or "")[:120]
        elif type in ("finished", "failed", "cancelled"):
            self._job_over(job_id, type == "finished")

    def _job_over(self, job_id: str, ok: bool) -> None:
        st = self.state
        title = self._titles.pop(job_id, "")
        kind = self.kinds.get(job_id, "other")
        on_done = self._done_calls.pop(job_id, None)
        st.busy, st.job_kind, self.job_detail = bool(self._titles), "", ""
        if not ok:
            self.failed_job = title
        try:
            st.ctx.reload_settings()  # a job, or another window, may have changed it
            if kind != "launch" or not ok:
                st.reload_profiles()  # an install may have changed the profiles
            self.update_badge()
        except Exception as e:  # the job is over either way; the next read tries again
            run_logging.log(f"warning: the shell could not catch up with {title or job_id}: {e}")
        self.invalidate("pages", "shell")
        if on_done is not None:
            self.background.start(lambda _progress: ok, on_result=on_done, name="job-done")

    def update_badge(self) -> None:
        self.unseen = self.activity.unseen()

    # ---------------------------------------------------------------- game and profile
    def set_game(self, key: str, remember: bool = True) -> bool:
        """Point everything at another game. Raises Busy while a job runs."""
        g = games.get(key)
        if g is self.state.game:
            return True
        if self.busy:
            raise Busy(tr("Wait for the current job. Switch games once it finishes."))
        self.state.select_game(g, remember)
        self.step = ""
        self.watch.look_now()
        self._game_state()
        self.recover_current_profile()
        self.invalidate("game", "pages", "shell")
        return True

    def pick_profile(self, index: int) -> bool:
        """Make the index'th profile the current one. False when nothing changed (busy, out of range, the same)."""
        st = self.state
        if self.busy or not 0 <= index < len(st.launch_profiles) or index == st.index:
            return False
        st.choose(index)
        self.recover_current_profile()
        self.invalidate("pages", "shell")
        return True

    def add_profile(self, path: Path) -> bool:
        """A .me3 profile or an installation.json becomes a profile of this game. False: it is neither."""
        st = self.state
        lp = core.launch_profile_from_path(path, st.locations)
        if lp is None:
            return False
        st.reload_profiles(select=lp.source)
        if not any(core.same_source(s.source, lp.source) for s in st.launch_profiles):
            st.launch_profiles.append(lp)
            st.choose(len(st.launch_profiles) - 1)
        self.invalidate("pages", "shell")
        return True

    def new_profile(self, name: str, include_seamless: bool) -> str:
        """A profile for this game (and Seamless Co-op moved into it when asked), as a logged job; its id."""
        from bayle.services import mods as mods_service
        from bayle.work import runner as jobs_service

        st = self.state
        g = st.game
        name = name.strip() or tr("{game} mods").format(game=g.name)

        def job(_launch_profile, loc):
            with jobs_service.run_logged("launcher: create profile", loc.game.key):
                made = str(mods_service.create_first_profile(name, include_seamless, loc=loc, log=run_logging.log))
            core.remember_profile(made, g)
            st.ctx.reload_settings()
            st.reload_profiles(select=made)

        return self.start(job, tr("Creating profile..."), "other")

    def set_mode(self, mode: str) -> None:
        if mode in topbar.MODES:
            save_game_settings(self.state.game.key, launch_mode=mode)
            self.state.ctx.reload_settings()
            self.invalidate("shell")

    def mode(self) -> str:
        return topbar.mode_of(self.state.settings, self.state.game)

    def launch(self, mode: str | None = None, allow_without_backup: bool = False) -> bool:
        """Launch in `mode` (default: the one remembered for the game)."""
        mode = mode or self.mode()
        if mode != self.mode():
            self.set_mode(mode)
        return self.flow.start(mode, allow_without_backup)

    def clear_dead_processes(self) -> str:
        return self.start(core.job_clear, tr("Clearing leftover processes..."), "other")

    # ---------------------------------------------------------------- the game watch
    def _on_running(self, running: bool) -> None:
        if running != self.state.game_running:
            self.state.game_running = running  # the writes gate reads this
            self._game_state()
            self.invalidate("pages", "shell")  # what a page may write depends on it

    def _on_steam(self, bad: bool) -> None:
        bad = bad and not self.busy
        if bad != self.steam_bad:
            self.steam_bad = bad
            self._game_state()

    def _on_shells(self, n: int) -> None:
        if n != self.dead_shells:
            self.dead_shells = n
            self._game_state()

    # ---------------------------------------------------------------- what the top bar shows
    def facts(self) -> topbar.Facts:
        st = self.state
        s = st.launch_profile
        busy = self.busy
        if self._slow is None:  # the very first read: nothing to show a wait on yet
            self._slow = (self.checks_key(), *self.read_checks(s))
        key, problems, warnings, _installed = self._slow
        if key != self.checks_key():
            problems, warnings = (), ()  # another profile than the one checked: say nothing until its check is back
        return topbar.Facts(
            game=st.game,
            installed=bool(st.locations.game_dir()),
            profile_count=len(st.launch_profiles),
            problems=problems,
            warnings=warnings,
            checking=self.checks_late and not busy,
            busy=busy,
            job_label=(self.job_detail or st.job_label) if st.busy else "",
            step=self.step,
            job_kind=st.job_kind if st.busy else ("launch" if self.flow.active else ""),
            game_running=st.game_running,
            steam_bad=self.steam_bad,
            dead_shells=self.dead_shells,
            warn_dead_shells=bool(st.settings.warn_dead_shells),
            coop_unsaved=self.coop_unsaved(),
            me3_update=self.me3_note,
            failed_job=self.failed_job,
            mode=self.mode(),
        )

    def checks_key(self) -> tuple:
        s = self.state.launch_profile
        return (id(s), str(s.profile) if s else "")

    @staticmethod
    def read_checks(s) -> tuple[tuple[core.Problem, ...], tuple[core.Problem, ...], dict[str, bool]]:
        """The disk reads behind the pill: the setup's problems and warnings, which games are installed."""
        return (
            tuple(s.problems()) if s else (),
            tuple(s.warnings()) if s else (),
            {g.key: bool(installed_dir(g)) for g in games.GAMES},
        )

    def store_checks(self, key: tuple, result) -> bool:
        """Keep a check read for `key`; True when it differs from the one before."""
        old = self._slow
        self._slow = (key, *result)
        return old != self._slow

    def installed_games(self) -> dict[str, bool]:
        return self._slow[3] if self._slow else {}

    # ---------------------------------------------------------------- me3
    def me3_facts(self) -> dict:
        """me3 asked now (runs me3 info and may ask the network: call it off the UI thread)."""
        return me3_facts(self.state.launch_profile, self.state.locations)

    def refresh_me3(self) -> None:
        launch_profile, loc = self.state.launch_profile, self.state.locations

        def work(_progress):
            try:
                return me3_facts(launch_profile, loc)
            except Exception as e:
                return {"error": str(e)}

        self.background.start(work, on_result=self._on_me3, name="me3-facts")

    def _on_me3(self, f: dict) -> None:
        if f.get("reload"):  # me3 reported its folders: its profile folder may be the one to use now
            self.state.ctx.reload_settings()
        latest = (f.get("latest") or {}).get("version")
        if f.get("update") and latest and not self._me3_said:
            self._me3_said = True  # one me3-update line per session
            self.me3_note = str(latest)
        self.invalidate("shell")

    def me3_clicked(self) -> None:
        """The me3 update line was followed: it is not said again this session."""
        self.me3_note = ""
        self.invalidate("shell")

    # ---------------------------------------------------------------- updates
    def cannot_update(self) -> Say | None:
        return self.updates.cannot_update(self.state.game_running, self.state.game.name, self.busy)

    # ---------------------------------------------------------------- start-up
    def startup(self) -> None:
        """The start-up sequence, once: the Engine's start-up steps (session.startup.run_steps), the game watch, me3 and update
        checks. The steps run off the calling thread; what they put right is told as notices."""

        def work(_progress) -> list[StepReport]:
            return run_steps(self._startup_steps)

        def done(reports: list[StepReport]) -> None:
            for r in reports:
                if r.ok and r.name in ("run_health", "interrupted_installs"):
                    for line in r.done or []:
                        self.notice(str(line), details=True)
            self.invalidate("pages", "shell")

        self.background.start(work, on_result=done, name="startup")
        self.update_badge()
        self.watch.start()
        self.refresh_me3()
        self.updates.check()

    def recover_current_profile(self) -> None:
        """Another profile is in use: finish its interrupted change, if any (the start did only the first one's)."""
        profile = self.state.profile_path()
        if profile is None:
            return

        def done(lines: list[str]) -> None:
            for line in lines:
                self.notice(line, details=True)
            if lines:
                self.invalidate("pages")

        self.background.start(lambda _progress: recover_profile(profile), on_result=done, name="recover-profile")

    def stop(self) -> None:
        self.watch.stop()

    # ---------------------------------------------------------------- support
    def save_logs(self, folder: Path) -> Path:
        """The launcher's logs, user names and Steam IDs masked, zipped into folder."""
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_logging.copy_logs(Path(tmp) / "logs")
                return Path(shutil.make_archive(str(Path(folder) / f"roundtable-souls-logs-{stamp}"), "zip", tmp))
        except OSError as e:
            raise OperationError("logs_not_saved", f"{tr('Could not save the logs')}: {e}") from e

    def logs_folder(self) -> Path:
        logs = data_dir() / "logs"
        try:
            logs.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise OperationError("logs_not_found", f"{tr('Could not open the logs folder')}: {e}") from e
        return logs

    def point_steam_shortcuts(self) -> list[str]:
        """Steam shortcuts with --play that start another copy of this program now start this one; the names changed."""
        try:
            record = load_settings().inno_migration or {}
            if record.get("steam_pending") or (record.get("old_exe") and not record.get("steam_done")):
                changed = migration.finish_steam_step()
            else:
                changed = migration.point_play_shortcuts_here()
        except Exception as e:
            raise OperationError("steam_shortcuts_failed", f"{tr('Steam shortcuts not changed')}: {e}") from e
        return [s.name for s in changed]
