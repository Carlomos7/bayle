"""The shell's host (technical specification §8.10): the one object every page adapter talks to, the QML-shell twin
of the Widgets window's `LauncherHost`. It implements the host contract (ui/host.py: busy, game_running, locations,
the current profile, run_job, run_in_background, the pickers, the Settings hand-offs) and owns what the shell shows
and does around the pages: the game and its profiles (LauncherState), logged jobs and their bookkeeping, the Launch
flow, the game watch, the launcher's update flow, the single-instance server and the close rules.

It holds no QML. The shell's adapter (ui/launcher/adapter.py) connects to its signals and reads `facts()`; pages are
registered with `register_page` so the host can tell them to read again and ask them what is unsaved."""

from __future__ import annotations

import datetime
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import QObject, Signal

from roundtable_souls.config.settings import data_dir
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import installed_dir
from roundtable_souls.platform import desktop
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import play as core
from roundtable_souls.services.mods import me3_facts
from roundtable_souls.services.settings import load_settings, save_game_settings, save_settings
from roundtable_souls.ui.host import Host
from roundtable_souls.ui.jobs import Jobs
from roundtable_souls.ui.launcher import launch, topbar
from roundtable_souls.ui.launcher.instance import InstanceServer
from roundtable_souls.ui.launcher.state import Context, LauncherState
from roundtable_souls.ui.launcher.updates import UpdateFlow
from roundtable_souls.ui.launcher.watch import GameWatch
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.text import tr
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import inno as migration

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


class Pickers(Protocol):
    """The file and folder dialogs. The shell's window supplies QML ones; a test or the self-test supplies none."""

    def file(self, title: str, filters: str) -> Path | None: ...
    def folder(self, title: str) -> Path | None: ...
    def save(self, title: str, name: str) -> Path | None: ...


class NoPickers:
    def file(self, title: str, filters: str) -> Path | None:
        return None

    def folder(self, title: str) -> Path | None:
        return None

    def save(self, title: str, name: str) -> Path | None:
        return None


class _FlowPorts:
    """The Launch flow's ports, on the shell."""

    def __init__(self, host: ShellHost):
        self.h = host

    def ask(self, ask: launch.Ask, on_answer: Callable[[str], None]) -> None:
        self.h.notifier.choose(
            ask.title,
            ask.lines,
            [(c.key, c.label, c.role) for c in ask.choices],
            on_answer,
            warning=ask.warning,
            safety=ask.safety,
        )

    def toast(self, text: str, error: bool = False) -> None:
        self.h.notifier.toast(text, error)

    def progress(self, label: str) -> None:
        self.h.step = label
        self.h.changed.emit()

    def background(self, work: Callable[[], Any], on_result: Callable[[Any], None]) -> None:
        self.h.run_in_background(work, on_result)

    def run_job(self, job, label: str, kind: str, on_done: Callable[[bool], None] | None = None) -> None:
        self.h.start(job, label, kind, on_done)

    def save_pending(self) -> str | None:
        save: Any = getattr(self.h.pages.get("modConfigs"), "save_pending_seamless", None)
        return None if save is None else save()

    def show_activity(self) -> None:
        self.h.show_page("activity")


class ShellHost(QObject):
    changed = Signal()  # anything the top bar shows (pill, status text, drop-downs, rail badge)
    gameChanged = Signal()  # another game is the current one
    appearanceChanged = Signal()  # theme, effects or grain were saved
    pageRequested = Signal(str)  # show this page (a registered page's name)
    quitRequested = Signal()
    forwardRequested = Signal()  # a second start asked this window to come forward
    _line = Signal(str, str)  # a job's log line (from a worker thread) and its level

    def __init__(self, ctx: Context, parent: QObject | None = None):
        super().__init__(parent)
        self.state = LauncherState(ctx)
        self.jobs = Jobs(self)
        self.notifier = Notifier(self)  # the shell's own toasts and forks (a page's Notifier is its own)
        self.pickers: Pickers = NoPickers()
        self.pages: dict[str, Any] = {}  # registered page adapters, by registry name
        self.page_opener: Callable[[str], Any] | None = None  # opens a page (creating it) and gives its adapter
        self.close_guard: Callable[[Callable[[], None]], None] = lambda proceed: proceed()
        # asks Save / Discard / Cancel about unsaved edits (words, what is about to happen, how to go on)
        self.guard_prompt: Callable[[list[str], str, Callable[[], None]], None] | None = None
        self.step = ""  # the Launch flow's step before its job runs ("Backing up saves...")
        self.job_detail = ""  # the newest line of the running job that says how it is going
        self.steam_bad = False
        self.dead_shells = 0
        self.failed_job = ""  # a job that failed and was not looked at yet
        self.unseen = 0  # failed jobs since Activity was last looked at (the rail badge)
        self.me3_note = ""
        self._me3_said = False
        self.updates = UpdateFlow(
            self.jobs,
            lambda: self.state.settings,
            self._update_toast,
            self._cannot_update,
            self.restart_for_update,
            desktop.open_path,
        )
        self.flow = launch.LaunchFlow(self.state, _FlowPorts(self))
        self.watch = GameWatch(
            self.jobs, lambda: self.state.locations, self._on_running, self._on_steam, self._on_shells
        )
        self.instance = InstanceServer(self)
        self.instance.showRequested.connect(self.forwardRequested)
        self.instance.playRequested.connect(self._play_requested)
        self._line.connect(self._on_line)
        core.NOTIFY = lambda title, msg: self.notifier.toast(f"{title}: {msg}", True)

    # ---------------------------------------------------------------- the host contract: state
    @property
    def busy(self) -> bool:
        return self.state.busy or self.flow.active

    @property
    def game_running(self) -> bool:
        return self.state.game_running

    @property
    def locations(self):
        return self.state.locations

    @property
    def setup(self):
        return self.state.setup

    @property
    def profile(self) -> Path | None:
        return self.state.profile_path()

    @property
    def settings(self):
        return self.state.settings

    @property
    def game(self) -> games.Game:
        return self.state.game

    # ---------------------------------------------------------------- the host contract: work
    def run_job(self, job, status: str) -> None:
        self.start(job, status, "other")

    def run_in_background(self, work, on_result) -> None:
        self.jobs.start(lambda _progress: work(), on_result=on_result)

    def start(self, job, status: str, kind: str = "other", on_done: Callable[[bool], None] | None = None) -> bool:
        """Run job as a logged job of the shell. One job at a time; nothing but clearing leftover processes runs
        while the game does."""
        st = self.state
        if st.busy:
            return False
        if st.game_running and job is not core.job_clear:
            self.notifier.toast(tr("{game} is already running. Close it first.").format(game=st.game.name), error=True)
            return False
        st.busy, st.job_label, st.job_kind, self.job_detail, self.step = True, status, kind, "", ""
        run_logging.attach_sink(lambda msg, level="": self._line.emit(str(msg), level or ""))
        setup = st.setup
        loc = setup.locations() if setup is not None else st.locations
        self.changed.emit()
        self.jobs.start_job(job, setup, loc, status, lambda outcome: self._done(outcome, status, kind, on_done))
        return True

    def _on_line(self, msg: str, level: str) -> None:
        shown = str(msg).strip()
        if self.state.busy and shown.lower().startswith(PROGRESS_LINES):
            self.job_detail = shown.splitlines()[0][:120]
            self.changed.emit()

    def _done(self, outcome, label: str, kind: str, on_done: Callable[[bool], None] | None) -> None:
        st = self.state
        st.busy, st.job_kind, self.job_detail = False, "", ""
        ok = bool(outcome.ok)
        if not ok:
            self.failed_job = label
        self.ctx_settings_again()
        if kind != "launch" or not ok:
            st.reload_setups()  # an adoption or an install may have changed the profiles
        self._update_badge()
        if not ok:
            self.notifier.toast_action(
                f"{label.rstrip('. ')}: {outcome.status}", tr("Details"), lambda: self.show_page("activity"), error=True
            )
        elif kind == "other":
            self.notifier.toast(tr("{job}: done").format(job=label.rstrip(". ")))
        self.refresh_pages()
        self.changed.emit()
        if on_done is not None:
            on_done(ok)

    def ctx_settings_again(self) -> None:
        """Read the settings file again (a job, or another window, may have changed it)."""
        self.state.ctx.reload_settings()

    # ---------------------------------------------------------------- pages
    def register_page(self, name: str, adapter: Any) -> None:
        self.pages[name] = adapter

    def show_page(self, name: str) -> Any:
        """Show a page (creating it the first time); its adapter."""
        if self.page_opener is not None:
            return self.page_opener(name)
        self.pageRequested.emit(name)
        return self.pages.get(name)

    def refresh_pages(self) -> None:
        """Every page reads again. A game without support shows only Activity, Settings and its placeholder, which read nothing of it."""
        names = None if self.state.game.ready else ("activity", "settings", "placeholder")
        for name, adapter in list(self.pages.items()):
            if names is None or name in names:
                try:
                    adapter.refresh()
                except RuntimeError:  # the page is gone
                    self.pages.pop(name, None)

    def unsaved(self) -> list[str]:
        """What has edits that are not written yet, in words for a prompt (each page that can say offers
        `unsaved_words()`)."""
        out: list[str] = []
        for adapter in self.pages.values():
            words: Any = getattr(adapter, "unsaved_words", None)
            if words is not None:
                out.extend(words())
        return out

    def coop_unsaved(self) -> bool:
        page = self.pages.get("modConfigs")
        pending: Any = getattr(page, "seamless_pending", None)
        return pending is not None and bool(pending())

    # ---------------------------------------------------------------- the host contract: hand-offs
    def profile_changed(self, note: str) -> None:
        run_logging.log_shown(note)
        self.refresh_pages()
        self.changed.emit()

    def profile_deleted(self, profile: Path, moved_to: Path) -> None:
        run_logging.log_shown(f"profile: moved {profile.name} to {moved_to}")
        core.forget_setup(self.state.game)
        self.ctx_settings_again()
        self.state.reload_setups()
        self.refresh_pages()
        self.changed.emit()

    def install(self, from_folder: bool) -> None:
        adapter = self.show_page("mods")
        if adapter is not None:
            adapter.install(from_folder)

    def install_paths(self, paths: list[Path]) -> None:
        from PySide6.QtCore import QUrl

        adapter = self.show_page("mods")
        if adapter is not None:
            adapter.installDropped([QUrl.fromLocalFile(str(p)).toString() for p in paths])

    def open_mod_configs(self, select: str = "") -> None:
        adapter = self.show_page("modConfigs")
        if adapter is not None and select:
            adapter.select_mod(select)

    def open_profile_transfer(self, mode: str) -> None:
        adapter = self.show_page("profileTransfer")
        if adapter is not None:
            adapter.open_transfer(mode)

    def open_profile_import(self, unpacked: Path, profiles: list[str], staging: Path | None = None) -> None:
        """The bundled-profile view for a mod download that also ships .me3 profiles (S3g); the page clears staging
        when it is done."""
        adapter = self.show_page("profileTransfer")
        if adapter is not None:
            adapter.open_profile_import(unpacked, profiles, staging)

    def saves_in_use(self) -> dict:
        """The save files the setup in use plays on; the locations learn them too, so the Saves page finds a setup's
        custom save names."""
        names = core.setup_saves(self.state.setup, self.state.game)
        self.state.ctx.note_setup_saves({k: names[k] for k in ("standard", "coop")})
        return names

    def open_path(self, path: Path) -> None:
        desktop.open_path(str(path))

    # ---------------------------------------------------------------- the profile list
    def profiles(self) -> list[str]:
        return topbar.profile_labels(self.state.setups)

    def profile_index(self) -> int:
        return self.state.index

    def pick_profile(self, index: int) -> None:
        """Make the index'th profile the current one, as the profile drop-down does."""
        if self.busy or not 0 <= index < len(self.state.setups) or index == self.state.index:
            return
        self.state.choose(index)
        self.refresh_pages()
        self.changed.emit()

    def add_profile(self, path: Path) -> bool:
        """File > Add existing profile: a .me3 profile or an installation.json becomes a profile of this game."""
        setup = core.setup_from_path(path, self.state.locations)
        if setup is None:
            self.notifier.toast(
                tr("That file is not a .me3 profile, and it is not a launcher installation.json."), error=True
            )
            return False
        self.state.reload_setups(select=setup.source)
        if not any(core.same_source(s.source, setup.source) for s in self.state.setups):
            self.state.setups.append(setup)
            self.state.choose(len(self.state.setups) - 1)
        self.refresh_pages()
        self.changed.emit()
        return True

    # ---------------------------------------------------------------- pickers (the window supplies the dialogs)
    def pick_file(self, title: str, filters: str) -> Path | None:
        return self.pickers.file(title, filters)

    def pick_folder(self, title: str) -> Path | None:
        return self.pickers.folder(title)

    def save_file(self, title: str, name: str) -> Path | None:
        return self.pickers.save(title, name)

    # ---------------------------------------------------------------- the game
    def set_game(self, key: str, remember: bool = True) -> bool:
        """Point every page at another game. Refused while a job runs."""
        g = games.get(key)
        if g is self.state.game:
            return True
        if self.busy:
            self.notifier.toast(tr("Wait for the current job. Switch games once it finishes."))
            return False
        self.state.select_game(g, remember)
        self.step = ""
        self.watch.look_now()
        self.refresh_pages()
        self.gameChanged.emit()
        self.changed.emit()
        return True

    def cycle_game(self, step: int) -> None:
        order = [g.key for g in games.GAMES]
        self.request_game(order[(order.index(self.state.game.key) + step) % len(order)])

    def _switch(self, key: str) -> None:
        self.set_game(key)

    def request_game(self, key: str) -> None:
        """Switch games, after the unsaved-changes question when something is unsaved."""
        if key == self.state.game.key:
            return
        if self.busy:
            self.notifier.toast(tr("Wait for the current job. Switch games once it finishes."))
            return
        self.guard(self.unsaved(), tr("switching games"), lambda: self._switch(key))

    def guard(self, words: list[str], action: str, proceed: Callable[[], None]) -> None:
        """Run proceed(), after asking Save / Discard / Cancel when words says something is unsaved (the shell's
        adapter supplies the prompt)."""
        if not words or self.guard_prompt is None:
            proceed()
        else:
            self.guard_prompt(words, action, proceed)

    # ---------------------------------------------------------------- Launch
    def launch(self, mode: str | None = None, allow_without_backup: bool = False) -> bool:
        """Launch in `mode` (default: the one remembered for the game)."""
        mode = mode or self.mode()
        if mode != self.mode():
            self.set_mode(mode)
        return self.flow.start(mode, allow_without_backup)

    def mode(self) -> str:
        return topbar.mode_of(self.state.settings, self.state.game)

    def set_mode(self, mode: str) -> None:
        if mode in topbar.MODES:
            save_game_settings(self.state.game.key, launch_mode=mode)
            self.ctx_settings_again()
            self.changed.emit()

    def _play_requested(self, arg: str) -> None:
        """A Steam shortcut (--play) started while this window is open: Launch here, for that game. "<key>
        allow-without-backup" (--allow-without-backup): a failed backup before it doesn't stop it."""
        key, _, flag = arg.partition(" ")
        g = games.resolve(key)
        if g is None:
            return
        if self.busy or self.game_running:
            self.notifier.toast(
                tr("Play from Steam ignored: {game} or a job is already running here.").format(
                    game=self.state.game.name
                ),
                error=True,
            )
            return
        if g.key != self.state.game.key:
            words = self.unsaved()
            self.guard(words, tr("switching to {game}").format(game=g.name), lambda: self._play_game(g, flag))
            return
        self._play_game(g, flag)

    def _play_game(self, g: games.Game, flag: str) -> None:
        if g.key != self.state.game.key and not self.set_game(g.key):
            return
        self.flow.start(topbar.PROFILE, allow_without_backup=flag == "allow-without-backup")

    # ---------------------------------------------------------------- the game watch
    def _on_running(self, running: bool) -> None:
        changed = running != self.state.game_running
        self.state.game_running = running
        if changed:
            self.refresh_pages()  # what a page may write depends on it
            self.changed.emit()

    def _on_steam(self, bad: bool) -> None:
        bad = bad and not self.busy
        if bad != self.steam_bad:
            self.steam_bad = bad
            self.changed.emit()

    def _on_shells(self, n: int) -> None:
        if n != self.dead_shells:
            self.dead_shells = n
            self.changed.emit()

    def clear_dead_processes(self) -> None:
        self.start(core.job_clear, tr("Clearing leftover processes..."), "other")

    def open_steam(self) -> None:
        desktop.open_path("steam://open/main")

    # ---------------------------------------------------------------- what the top bar shows
    def facts(self) -> topbar.Facts:
        st = self.state
        s = st.setup
        busy = self.busy
        return topbar.Facts(
            game=st.game,
            installed=bool(st.locations.game_dir()),
            profile_count=len(st.setups),
            problems=tuple(s.problems()) if s else (),
            busy=busy,
            job_label=(self.job_detail or st.job_label) if st.busy else self.step,
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

    def installed_games(self) -> dict[str, bool]:
        return {g.key: bool(installed_dir(g)) for g in games.GAMES}

    def mark_seen(self) -> None:
        save_settings(activity_seen=time.time())
        self.ctx_settings_again()
        self.failed_job = ""
        self._update_badge()
        self.changed.emit()

    def _update_badge(self) -> None:
        seen = float(load_settings().activity_seen or 0.0)
        self.unseen = len(run_logging.unseen_failures(seen))

    def me3_clicked(self) -> None:
        """The me3 update line was followed: it is not said again this session."""
        self.me3_note = ""
        self.changed.emit()

    # ---------------------------------------------------------------- the Settings page's hand-offs
    def settings_changed(self, key: str) -> None:
        """A page saved key: the shell reads the settings again and follows."""
        self.ctx_settings_again()
        if key in ("me3_path", "game_exe", "me3_profile_dir", "saves_dir"):
            self.state.reload_setups()
            self.refresh_me3()
            self.refresh_pages()
        elif key == "launcher_channel":
            self.updates.forget_offer()
        elif key in ("theme", "effects", "grain", "logo"):
            self.appearanceChanged.emit()
        self.changed.emit()

    def set_appearance(self) -> None:
        self.ctx_settings_again()
        self.appearanceChanged.emit()

    def check_for_updates(self) -> None:
        self.updates.check(force=True)

    def update_state(self) -> dict:
        return self.updates.state()

    def watch_updates(self, call) -> None:
        self.updates.watch(call)

    def notice_action(self, notice_id: str, key: str) -> None:
        self.updates.notice_action(notice_id, key)

    def dismiss_notice(self, notice_id: str) -> None:
        self.updates.dismiss(notice_id)

    def _update_toast(self, title: str, body: str, kind: str) -> None:
        self.notifier.toast(f"{title}: {body}" if body else title, error=kind == "error")

    def _cannot_update(self) -> str:
        return self.updates.cannot_update(self.game_running, self.state.game.name, self.busy)

    def restart_for_update(self, prepared) -> None:
        """Restart now: the shell closes cleanly (asking about a running job and unsaved edits), then the update is
        applied when this process exits."""
        why = self._cannot_update()
        if why:
            self.notifier.toast(f"{tr('Cannot restart now')}: {why}", error=True)
            return

        def go() -> None:
            self.instance.release()  # the new version takes the window's name when it starts
            try:
                updates.apply_update(prepared)  # Velopack applies it after this process exits, then restarts
            except Exception as e:
                self.instance.take()
                self.notifier.toast(f"{tr('Update not applied')}: {e} {tr('This version keeps running.')}", error=True)
                return
            self.quitRequested.emit()

        self.close_guard(go)

    def point_steam_shortcuts(self) -> None:
        def work(_progress):
            try:
                record = load_settings().inno_migration or {}
                if record.get("steam_pending") or (record.get("old_exe") and not record.get("steam_done")):
                    changed = migration.finish_steam_step()
                else:
                    changed = migration.point_play_shortcuts_here()
                return {"changed": [s.name for s in changed]}
            except Exception as e:
                return {"error": str(e)}

        def done(result):
            if result.get("error"):
                self.notifier.toast(f"{tr('Steam shortcuts not changed')}: {result['error']}", error=True)
            elif result.get("changed"):
                self.notifier.toast(
                    tr("Steam shortcuts updated. Now starting this copy: {names}.").format(
                        names=", ".join(result["changed"])
                    )
                )
            else:
                self.notifier.toast(tr("Nothing to change: no Steam shortcut with --play starts another copy."))

        self.jobs.start(work, on_result=done, name="steam-shortcuts")

    def save_logs_for_support(self) -> None:
        where = self.pick_folder(tr("Save logs for support: pick a folder"))
        if where is None:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                run_logging.copy_logs(Path(tmp) / "logs")
                out = shutil.make_archive(str(Path(where) / f"roundtable-souls-logs-{stamp}"), "zip", tmp)
        except OSError as e:
            self.notifier.toast(f"{tr('Could not save the logs')}: {e}", error=True)
            return
        self.notifier.toast(tr("Logs saved: {name}. User names and Steam IDs are masked.").format(name=Path(out).name))

    def open_logs_folder(self) -> None:
        logs = data_dir() / "logs"
        try:
            logs.mkdir(parents=True, exist_ok=True)
            desktop.open_path(str(logs))
        except OSError as e:
            self.notifier.toast(f"{tr('Could not open the logs folder')}: {e}", error=True)

    def me3_facts(self) -> dict:
        """me3 asked now (runs me3 info: call it on a worker thread)."""
        return me3_facts(self.state.setup, self.state.locations)

    def refresh_me3(self) -> None:
        setup, loc = self.state.setup, self.state.locations

        def work(_progress):
            try:
                return me3_facts(setup, loc)
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(work, on_result=self._on_me3)

    def _on_me3(self, f: dict) -> None:
        if f.get("reload"):  # me3 reported its folders: its profile folder may be the one to use now
            self.ctx_settings_again()
        latest = (f.get("latest") or {}).get("version")
        if f.get("update") and latest and not self._me3_said:
            self._me3_said = True  # one me3-update line per session
            self.me3_note = str(latest)
        self.changed.emit()

    # ---------------------------------------------------------------- start and stop
    def start_background(self) -> None:
        """What a running shell does from the start: the game watch, me3 and update checks."""
        self._update_badge()
        self.watch.start()
        self.refresh_me3()
        self.updates.check()

    def after_show(self, mark_ready: Callable[[], dict | None] | None = None) -> None:
        """For a real start only (tests build the shell without it), once the first page is up: tell an update's
        watchdog this version is running, report how the last update went, finish the move from the old installer
        and tidy old downloads."""
        confirmed = (mark_ready or (lambda: updates.mark_ready("window")))()
        self.state.ctx.start_imports()  # after the ready report: the imports may take a while and never delay it

        def work(report):
            outcome = confirmed or updates.update_outcome()
            report(outcome or {})
            pending = (load_settings().update_pending or {}).get("version")
            try:
                updates.clean_downloads(keep=pending)
            except Exception:
                pass
            try:
                return migration.migrate_from_inno() or {}
            except Exception as e:
                return {"status": "failed", "reason": str(e)}

        self.jobs.start(
            work, on_result=self.updates.migration, on_progress=self.updates.outcome, name="launcher-start-tasks"
        )

    def closing(self) -> dict:
        """What closing the window would lose: a running job (the save repair and cleanup after it are skipped, the
        game is left alone) and unsaved edits."""
        return {"job": self.state.busy or self.flow.active, "unsaved": self.unsaved()}

    def shutdown(self) -> None:
        self.instance.release()


def _declares_host(host: ShellHost) -> Host:  # pyright checks ShellHost against the one host contract
    return host
