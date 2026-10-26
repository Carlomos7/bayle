"""The shell's host (technical specification §8.10): the one object every page adapter talks to, the QML-shell twin
of the Widgets window's `LauncherHost`. It implements the host contract (ui/host.py: busy, game_running, locations,
the current profile, run_job, run_in_background, the pickers, the Settings hand-offs) and owns what the shell shows
and does around the pages: the game and its profiles (LauncherState), logged jobs and their bookkeeping, the Launch
flow, the game watch, the launcher's update flow, the single-instance server and the close rules.

It holds no QML. The shell's adapter (ui/launcher/adapter.py) connects to its signals and reads `facts()`; pages are
registered with `register_page` so the host can tell them to read again and ask them what is unsaved."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from bayle.adapters.system import desktop
from bayle.adapters.system import logging as run_logging
from bayle.errors import Busy, OperationError
from bayle.modules.games import catalog as games
from bayle.modules.launch import play as core
from bayle.modules.settings.service import load_settings
from bayle.work.events import Event
from bayle.work.prompts import Question
from PySide6.QtCore import QObject, QTimer, Signal

from bayle_qt.host import Host
from bayle_qt.jobs import Jobs, run_async
from bayle_qt.launcher import presenter
from bayle_qt.launcher.instance import InstanceServer
from bayle_qt.notifications import Notifier
from bayle_qt.shell import facts as topbar
from bayle_qt.shell.service import Shell
from bayle_qt.shell.state import Context
from bayle_qt.text import tr
from bayle_qt.updater import apply as updates
from bayle_qt.updater import inno as migration
from bayle_qt.updater import retitle


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


class ShellHost(QObject):
    changed = Signal()  # anything the top bar shows (pill, status text, drop-downs, rail badge)
    gameChanged = Signal()  # another game is the current one
    appearanceChanged = Signal()  # theme, effects or grain were saved
    pageRequested = Signal(str)  # show this page (a registered page's name)
    newProfileAsked = Signal()  # a page asks for the shell's New profile dialog
    quitRequested = Signal()
    forwardRequested = Signal()  # a second start asked this window to come forward
    checksChanged = Signal()  # the disk checks behind the pill came back different (or are slow)
    _session_event = Signal()  # the shell's bus has events (from a worker thread)

    def __init__(self, ctx: Context, parent: QObject | None = None):
        super().__init__(parent)
        self.jobs = Jobs(self)  # the shell's background: results come back on this (the UI) thread
        self.shell = Shell(ctx, background=self.jobs, restart=self.restart_for_update, open_url=desktop.open_path)
        self.state = self.shell.state
        self.job_manager = self.shell.jobs  # the engine's one JobManager
        self.features = self.shell.features
        self.activity = self.shell.activity
        self.settings_service = self.shell.settings
        self.saves_service = self.shell.saves
        self.flow = self.shell.flow
        self.updates = self.shell.updates
        self.watch = self.shell.watch
        self.notifier = Notifier(self)  # the shell's own toasts and forks (a page's Notifier is its own)
        self.pickers: Pickers = NoPickers()
        self.pages: dict[str, Any] = {}  # registered page adapters, by registry name
        self.shown_page = ""  # the page on show: the only one that reads at once
        self._stale: set[str] = set()  # pages that missed a refresh while hidden; each reads when it is shown
        self.page_opener: Callable[[str], Any] | None = None  # opens a page (creating it) and gives its adapter
        self.close_guard: Callable[[Callable[[], None]], None] = lambda proceed: proceed()
        # asks Save / Discard / Cancel about unsaved edits (words, what is about to happen, how to go on)
        self.guard_prompt: Callable[[list[str], str, Callable[[], None]], None] | None = None
        self._check_running = self._check_dirty = False
        self._detail_seen = ""
        self._session_jobs: dict[str, str] = {}  # jobs running, by id: their title
        self._followers: dict[str, Callable[[Any], None]] = {}  # job id -> what to do with its end (follow_job)
        self._quiet: set[str] = set()  # jobs whose end the page words itself: no generic "done" toast
        self.shell.coop_unsaved = self.coop_unsaved
        self.shell.save_pending = self._save_pending
        self._events = self.shell.bus.subscribe(notify=self._session_event.emit)
        self._session_event.connect(self._drain)
        self.instance = InstanceServer(self)
        self.instance.showRequested.connect(self.forwardRequested)
        self.instance.playRequested.connect(self._play_requested)

    # ---------------------------------------------------------------- the shell's events
    def _drain(self) -> None:
        """What the shell published (job events, game.state, invalidated, notice, navigate, prompt), on the UI thread."""
        while (e := self._events.get(0)) is not None:
            if e.type == "prompt":
                self._ask(e)
            elif e.job_id is not None:
                self._job_event(e)
            elif e.type == "invalidated":
                if "pages" in (e.data.get("what") or ()):
                    self.refresh_pages()  # what a page may write depends on the game and the jobs
                self.changed.emit()
            elif e.type == "game.state":
                self.changed.emit()
            elif e.type == "notice":
                text = (
                    presenter.say_text(e.data["code"], e.data.get("facts"))
                    if e.data.get("code")
                    else str(e.data.get("text") or "")
                )
                if e.data.get("details"):
                    self.notifier.toast_action(text, tr("Details"), lambda: self.show_page("activity"))
                else:
                    self.notifier.toast(text, error=bool(e.data.get("error")))
            elif e.type == "navigate":
                self.show_page(str(e.data.get("page") or ""))

    def _ask(self, e: Event) -> None:
        """A question on the bus (the Launch flow's forks): shown as the shell's dialog, the answer goes back by id."""
        prompts = self.shell.jobs.prompts
        prompt_id = str(e.data.get("prompt_id") or "")
        words = prompts.words(prompt_id)
        if isinstance(words, Question):
            words = presenter.question_words(words)
        if words is not None:
            self.notifier.choose(words, lambda key: prompts.answer(prompt_id, key))

    def _job_event(self, e: Event) -> None:
        job_id = str(e.job_id)
        if e.type == "started":
            self._session_jobs[job_id] = str(e.data.get("title") or "")
            if e.data.get("quiet"):
                self._quiet.add(job_id)
            self._detail_seen = ""
            self.changed.emit()
        elif e.type in ("log", "progress"):
            if self.shell.job_detail != self._detail_seen:
                self._detail_seen = self.shell.job_detail
                self.changed.emit()
        elif e.type in ("finished", "failed", "cancelled"):
            label = self._session_jobs.pop(job_id, "")
            kind = self.shell.kinds.get(job_id, "other")
            quiet = job_id in self._quiet
            self._quiet.discard(job_id)
            if e.type != "finished":
                status = "Error (see details)" if e.data.get("unexpected") else "Stopped (see details)"
                self.notifier.toast_action(
                    f"{label.rstrip('. ')}: {status}", tr("Details"), lambda: self.show_page("activity"), error=True
                )
            elif kind == "other" and not quiet:
                self.notifier.toast(tr("{job}: done").format(job=label.rstrip(". ")))
            self.changed.emit()
            follower = self._followers.pop(job_id, None)
            if follower is not None:
                follower(self.job_manager.get(job_id))

    def follow_job(self, job_id: str, done: Callable[[Any], None]) -> None:
        """done(JobSnapshot) on the UI thread when the session job ends (at once when it already has). A page tells
        the job's result with it (a toast with Undo, a read of the page)."""
        snap = self.job_manager.get(job_id)
        if snap is not None and snap.state != "running":
            done(snap)
        else:
            self._followers[job_id] = done

    # ---------------------------------------------------------------- the host contract: state
    @property
    def busy(self) -> bool:
        return self.shell.busy

    @property
    def game_running(self) -> bool:
        return self.state.game_running

    @property
    def locations(self):
        return self.state.locations

    @property
    def launch_profile(self):
        return self.state.launch_profile

    @property
    def profile(self) -> Path | None:
        return self.state.profile_path()

    @property
    def settings(self):
        return self.state.settings

    @property
    def game(self) -> games.Game:
        return self.state.game

    # what the shell keeps for the top bar
    @property
    def step(self) -> str:
        return self.shell.step

    @property
    def job_detail(self) -> str:
        return self.shell.job_detail

    @property
    def steam_bad(self) -> bool:
        return self.shell.steam_bad

    @property
    def dead_shells(self) -> int:
        return self.shell.dead_shells

    @property
    def unseen(self) -> int:
        return self.shell.unseen

    @property
    def failed_job(self) -> str:
        return self.shell.failed_job

    @property
    def me3_note(self) -> str:
        return self.shell.me3_note

    # ---------------------------------------------------------------- the host contract: work
    def run_job(self, job, status: str, on_done: Callable[[bool], None] | None = None) -> None:
        # on_done: the page speaks for itself (its own toast), so the generic "done" toast is skipped
        self.start(job, status, "other" if on_done is None else "page", on_done)

    def run_in_background(self, work, on_result) -> None:
        self.jobs.start(lambda _progress: work(), on_result=on_result)

    def defer(self, call: Callable[[], None]) -> None:
        """Run call on the UI thread after the current event-loop turn (requests made in one turn share one read)."""
        QTimer.singleShot(0, call)

    def start(self, job, status: str, kind: str = "other", on_done: Callable[[bool], None] | None = None) -> bool:
        """Run job as a logged job of the shell. One job at a time; nothing but clearing leftover processes runs
        while the game does."""
        try:
            self.shell.start(job, status, kind, on_done=on_done)
        except Busy as e:
            if e.details.get("reason") == "game_running":
                self.notifier.toast(
                    tr("{game} is already running. Close it first.").format(game=self.state.game.name), error=True
                )
            return False
        return True

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
                if name != self.shown_page:  # a hidden page reads when it is shown, not after every job
                    self._stale.add(name)
                    continue
                try:
                    getattr(adapter, "refresh_if_changed", adapter.refresh)()
                except RuntimeError:  # the page is gone
                    self.pages.pop(name, None)

    def page_shown(self, name: str) -> bool:
        """The shell shows this page now; True when it read again because it had missed a refresh."""
        self.shown_page = name
        if name not in self._stale:
            return False
        self._stale.discard(name)
        adapter = self.pages.get(name)
        if adapter is None:
            return False
        try:
            adapter.refresh()
        except RuntimeError:  # the page is gone
            self.pages.pop(name, None)
            return False
        return True

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

    def _save_pending(self) -> str | None:
        save: Any = getattr(self.pages.get("modConfigs"), "save_pending_seamless", None)
        return None if save is None else save()

    # ---------------------------------------------------------------- the host contract: hand-offs
    def profile_changed(self, note: str) -> None:
        run_logging.log_shown(note)
        self.refresh_pages()
        self.changed.emit()

    def profile_deleted(self, profile: Path, moved_to: Path) -> None:
        run_logging.log_shown(f"profile: moved {profile.name} to {moved_to}")
        core.forget_profile(self.state.game)
        self.ctx_settings_again()
        self.state.reload_profiles()
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
        """The save files the profile in use plays on; the locations learn them too, so the Saves page finds a profile's
        custom save names."""
        names = core.profile_saves(self.state.launch_profile, self.state.game)
        self.state.ctx.note_profile_saves({k: names[k] for k in ("standard", "coop")})
        return names

    def open_path(self, path: Path) -> None:
        run_async(lambda: desktop.open_path(str(path)))  # the shell hand-off can wait on a slow disk

    # ---------------------------------------------------------------- the profile list
    def profiles(self) -> list[str]:
        return topbar.profile_labels(self.state.launch_profiles)

    def profile_index(self) -> int:
        return self.state.index

    def request_new_profile(self) -> None:
        self.newProfileAsked.emit()

    def pick_profile(self, index: int) -> None:
        """Make the index'th profile the current one, as the profile drop-down does."""
        self.shell.pick_profile(index)

    def seamless_offer(self) -> bool:
        """Seamless Co-op sits in the game folder: a new profile may take it along (moved into the profile)."""
        from bayle.modules.coop import service as coop_service

        g = self.state.game
        try:
            return bool(g.coop_dll) and bool(coop_service.seamless_in_game_folder(self.state.locations))
        except OSError:
            return False

    def new_profile(self, name: str, include_seamless: bool) -> bool:
        """File > New profile: a profile for this game (and Seamless Co-op moved into it when asked), as a logged job."""
        try:
            self.shell.new_profile(name, include_seamless)
        except Busy:
            return False
        return True

    def add_profile(self, path: Path) -> bool:
        """File > Add existing profile: a .me3 profile or an installation.json becomes a profile of this game."""
        if not self.shell.add_profile(path):
            self.notifier.toast(
                tr("That file is not a .me3 profile, and it is not a launcher installation.json."), error=True
            )
            return False
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
        try:
            self.shell.set_game(key, remember)
        except Busy as e:
            self.notifier.toast(e.message)
            return False
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
        return self.shell.launch(mode, allow_without_backup)

    def mode(self) -> str:
        return self.shell.mode()

    def set_mode(self, mode: str) -> None:
        self.shell.set_mode(mode)

    def _play_requested(self, arg: str) -> None:
        """A Steam shortcut (--play) started while this window is open: Launch here, for that game. "<key>
        allow-without-backup" (--allow-without-backup): a failed backup before it doesn't stop it."""
        key, _, flag = arg.partition(" ")
        g = games.resolve(key)
        if g is None:
            return
        if self.busy or self.game_running:
            self.notifier.toast(
                tr("Launch from Steam ignored: {game} or a job is already running here.").format(
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
    def clear_dead_processes(self) -> None:
        self.start(core.job_clear, tr("Clearing leftover processes..."), "other")

    def open_steam(self) -> None:
        desktop.open_path("steam://open/main")

    # ---------------------------------------------------------------- what the top bar shows
    def facts(self) -> topbar.Facts:
        return self.shell.facts()

    def schedule_checks(self) -> None:
        """Read the disk checks again off the UI thread; the view updates when they are back, and says "Checking..."
        only when that takes over 200 ms. Not while a job runs (its progress lines come fast, nothing edits then)."""
        if self.busy:
            return
        if self._check_running:
            self._check_dirty = True
            return
        self._check_running, self.shell.checks_late = True, False
        key, s = self.shell.checks_key(), self.state.launch_profile
        QTimer.singleShot(200, self._checks_late)
        self.run_in_background(lambda: self.shell.read_checks(s), lambda r: self._checks_back(key, r))

    def _checks_late(self) -> None:
        if self._check_running and not self.shell.checks_late:
            self.shell.checks_late = True
            self.checksChanged.emit()

    def _checks_back(self, key: tuple, result) -> None:
        self._check_running, was_late, self.shell.checks_late = False, self.shell.checks_late, False
        if self.shell.store_checks(key, result) or was_late:
            self.checksChanged.emit()
        if self._check_dirty or key != self.shell.checks_key():
            self._check_dirty = False
            self.schedule_checks()

    def installed_games(self) -> dict[str, bool]:
        return self.shell.installed_games()

    def mark_seen(self) -> None:
        self.activity.mark_seen()
        self.ctx_settings_again()
        self.shell.failed_job = ""
        self.shell.update_badge()
        self.changed.emit()

    def me3_clicked(self) -> None:
        """The me3 update line was followed: it is not said again this session."""
        self.shell.me3_clicked()

    # ---------------------------------------------------------------- the Settings page's hand-offs
    def settings_changed(self, key: str) -> None:
        """A page saved key: the shell reads the settings again and follows."""
        self.ctx_settings_again()
        if key in ("me3_path", "game_exe", "me3_profile_dir", "saves_dir"):
            self.state.reload_profiles()
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
        return presenter.update_state(self.updates.state())

    def watch_updates(self, call) -> None:
        self.updates.watch(call)

    def notice_action(self, notice_id: str, key: str) -> None:
        self.updates.notice_action(notice_id, key)

    def dismiss_notice(self, notice_id: str) -> None:
        self.updates.dismiss(notice_id)

    def restart_for_update(self, prepared) -> None:
        """Restart now: the shell closes cleanly (asking about a running job and unsaved edits), then the update is
        applied when this process exits."""
        why = self.shell.cannot_update()
        if why is not None:
            self.notifier.toast(f"{tr('Cannot restart now')}: {presenter.say_text(why.code, why.facts)}", error=True)
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
                return {"changed": self.shell.point_steam_shortcuts()}
            except OperationError as e:
                return {"error": e.message}

        def done(result):
            if result.get("error"):
                self.notifier.toast(result["error"], error=True)
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

        def work(_progress):
            try:
                return {"path": self.shell.save_logs(where)}
            except OperationError as e:
                return {"error": e.message}

        def done(result):
            if result.get("error"):
                self.notifier.toast(result["error"], error=True)
            else:
                self.notifier.toast(
                    tr("Logs saved: {name}. User names and Steam IDs are masked.").format(name=result["path"].name)
                )

        self.jobs.start(work, on_result=done, name="support-logs")

    def open_logs_folder(self) -> None:
        try:
            desktop.open_path(str(self.shell.logs_folder()))
        except (OperationError, OSError) as e:
            self.notifier.toast(str(getattr(e, "message", e)), error=True)

    def me3_facts(self) -> dict:
        """me3 asked now (runs me3 info: call it on a worker thread)."""
        return self.shell.me3_facts()

    def refresh_me3(self) -> None:
        self.shell.refresh_me3()

    # ---------------------------------------------------------------- start and stop
    def start_background(self) -> None:
        """What a running shell does from the start: the shell's start-up sequence (the recoveries, the game watch,
        me3 and update checks), once."""
        self.shell.startup()

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
                retitle.run()
            except Exception:
                pass  # shortcut names are cosmetic: never hold up the start
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
        return {"job": self.shell.busy, "unsaved": self.unsaved()}

    def shutdown(self) -> bool:
        """Stop the watch and give the pool 3 s; False when work is still running (the caller exits anyway)."""
        self.shell.stop()
        self._events.close()
        drained = self.jobs.shutdown()
        self.instance.release()
        return drained


def _declares_host(host: ShellHost) -> Host:  # pyright checks ShellHost against the one host contract
    return host
