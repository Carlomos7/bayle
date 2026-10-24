"""The Settings page's adapter: the thin QObject the QML page binds to (technical specification §8.10, Settings). It
holds no decisions: the words and rules come from the presenter; its slots save through config.settings and tell the
host (the Widgets launcher until the shell, S9) to follow; folder and file picks, jobs and the updater run through
the host's existing paths. The page never calls the updater: Update now and Restart now are notice buttons, and the
host runs them with its own checks (the game and jobs stopped, the program's identity, the prepared package)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from bayle.errors import OperationError
from bayle.platform import desktop
from bayle.platform.text import tr
from bayle.platform.threads import assert_not_ui_thread
from bayle.services.play import TITLE, VERSION
from bayle.services.settings import KEEP_RANGE, Changed, SettingsService
from bayle.services.updates import RELEASES_URL
from bayle.ui.models import RowsModel
from bayle.ui.notifications import Notifier
from bayle.ui.pages.settings import presenter as view
from bayle.ui.pages.settings.presenter import CHOICE_LABELS, LAYOUT_LABELS, LOCATION_WORDS, SettingsState
from bayle.ui.refresh import Refresher

LAYOUT = tuple(LAYOUT_LABELS)  # the draft fields


class SettingsHost(Protocol):
    """What the page needs from the window that hosts it."""

    @property
    def busy(self) -> bool: ...
    @property
    def job_manager(self) -> Any:
        """The engine's JobManager: the running move of the profiles folder is followed and cancelled there."""

    @property
    def settings_service(self) -> SettingsService: ...
    def run_in_background(self, work, on_result) -> None: ...
    def open_path(self, path: Path) -> None: ...
    def pick_folder(self, title: str) -> Path | None: ...
    def pick_file(self, title: str, filters: str) -> Path | None: ...
    def settings_changed(self, key: str) -> None:
        """key was saved: the window reads the settings again and follows (its switches, locations, theme)."""

    def set_appearance(self) -> None:
        """The saved theme, effects and grain, applied to every window."""

    def check_for_updates(self) -> None: ...
    def point_steam_shortcuts(self) -> None: ...
    def save_logs_for_support(self) -> None: ...
    def open_logs_folder(self) -> None: ...
    def me3_facts(self) -> dict: ...
    def update_state(self) -> dict: ...
    def watch_updates(self, call) -> None: ...
    def notice_action(self, notice_id: str, key: str) -> None: ...
    def dismiss_notice(self, notice_id: str) -> None: ...


class SettingsAdapter(QObject):
    changed = Signal()
    updatesChanged = Signal()
    me3Changed = Signal()

    def __init__(self, host: SettingsHost, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self._me3 = view.Me3Line(tr("Checking me3..."), "muted", "", "", "", "", False)
        self._update: dict = {"line": "", "tone": "muted", "notices": []}
        self._locations = RowsModel(("key", "title", "help", "value", "placeholder", "isDir", "menu"), self)
        self._switches = {
            g: RowsModel(("key", "title", "blurb", "help", "checked", "shown"), self)
            for g in ("launch", "offline", "updates", "me3")
        }
        self._notices = RowsModel(("id", "level", "title", "body", "closable", "actions"), self)
        self._choices = {k: RowsModel(("key", "label"), self) for k in CHOICE_LABELS}
        for k, rows in CHOICE_LABELS.items():
            self._choices[k].set_rows([{"key": a, "label": tr(b)} for a, b in rows])
        self._saved_layout: dict[str, str] = {}
        self._saved_root = ""  # the saved profiles folder as the last read saw it (what a move is checked against)
        self._layout_check: dict[str, Any] = {"errors": {}, "preview": ""}
        # what the page shows until the first read lands (it is built on a worker)
        self._values: dict[str, Any] = {
            **dict.fromkeys(
                (
                    "theme",
                    "effects",
                    "grain",
                    "logo",
                    "log_level",
                    "launcher_channel",
                    "backups_location",
                    "profiles_root",
                    "steam_target",
                    "steam_options",
                    "data_folder",
                    "launcher_line",
                ),
                "",
            ),
            "backups_keep": 20,
            "labels": dict.fromkeys(CHOICE_LABELS, ""),
        }
        self._draft: dict[str, str] = {}
        self._move_job = ""  # the running move of the profiles folder (its Cancel stops it)
        self._moving = False
        self._refresher = Refresher(host, lambda: None, self._build, self._apply)
        self.refresh()
        try:
            host.watch_updates(self._on_update_state)
        except Exception:
            pass

    # ---- the words
    title = Property(str, lambda self: tr("Settings"), constant=True)
    words = Property(
        dict,
        lambda self: {
            "locations": tr("Locations"),
            "launch": tr("Launch"),
            "launchHint": tr("Steps that run around Launch. Each can be turned off; Launch itself always runs."),
            "offline": view.OFFLINE_TITLE,
            "offlineBlurb": view.OFFLINE_BLURB,
            "offlineHelp": view.OFFLINE_HELP,
            "steam": tr("Steam shortcut"),
            "steamHelp": tr("Launches from Steam without this window. One shortcut per game."),
            "copyTarget": tr("Copy target"),
            "copyOptions": tr("Copy launch options"),
            "pointSteam": tr("Point Steam shortcuts here"),
            "pointSteamTip": tr(
                "Makes Steam shortcuts that start an older install start this copy instead. Close Steam first. Each "
                "changed file is backed up."
            ),
            "leftover": tr("Leftover processes"),
            "leftoverHelp": tr("Hidden copies of the game left running after it closes."),
            "clearNow": tr("Clear now"),
            "backups": tr("Backups"),
            "backupsLocation": tr("Location"),
            "backupsLocationHelp": tr("Inside the launcher's data folder."),
            "backupsKeep": tr("How many to keep"),
            "backupsKeepHelp": tr(
                "Per save file. Backups from the last 7 days and any you marked Keep are kept as well."
            ),
            "appearance": tr("Appearance"),
            "theme": tr("Theme"),
            "themeHelp": tr("System follows Windows. Tarnished is a dark olive theme."),
            "effects": tr("Effects"),
            "effectsHelp": tr("Off has no blur or grain. Reduced has no blur and lighter grain."),
            "grain": tr("Grain"),
            "grainHelp": tr("Fine texture behind pages and panels."),
            "logo": tr("Logo"),
            "logoHelp": tr(
                "Sets the top bar emblem and the window icon. Follows theme is crimson on dark themes and ice on the light theme."
            ),
            "updates": tr("Updates"),
            "channel": tr("Update channel"),
            "channelHelp": tr(
                "Beta also offers pre-releases, which get less testing. Going back to Stable never installs an older "
                "version."
            ),
            "check": tr("Check for updates"),
            "releases": tr("Releases"),
            "releasesTip": tr("Every version, with notes and downloads."),
            "logs": tr("Logs"),
            "logsFolder": tr("Logs folder"),
            "openFolder": tr("Open folder"),
            "saveLogs": tr("Save logs for support"),
            "saveLogsHelp": tr("A zip of recent logs with user names and Steam IDs masked."),
            "save": tr("Save..."),
            "settingsFolder": tr("Settings folder"),
            "logLevel": tr("Log level"),
            "logLevelHelp": tr("Verbose adds fine detail to launcher.log."),
            "about": tr("About"),
            "aboutHelp": tr(
                "GPL-3.0. Built on PySide6 and me3. Bayle is an unofficial fan project and is not affiliated with or endorsed by FromSoftware or Bandai Namco."
            ),
            "licence": tr("Licence"),
            "notices": tr("Third-party notices"),
            "browse": tr("Browse..."),
            "more": tr("More"),
            "profilesFolder": tr("Profiles folder"),
            "profilesFolderHelp": tr("Where Bayle keeps its profiles and mods."),
            "change": tr("Change..."),
            "moveAll": tr("Move all..."),
            "otherProfiles": tr("Profiles outside Bayle"),
            "moveAllTip": tr("Moves every me3 profile of this game into Bayle's folder."),
            "folderNames": tr("Folder names"),
            "gameFolder": tr("Game folder"),
            "gameFiles": tr("Game-file mods"),
            "dllMods": tr("DLL mods"),
            "sharedMods": tr("Shared mods"),
            "apply": tr("Apply"),
            "cancel": tr("Cancel"),
            "moving": tr("Moving..."),
            "dismiss": tr("Dismiss"),
        },
        constant=True,
    )

    # ---- models
    locations = Property(QObject, lambda self: self._locations, constant=True)
    launchSwitches = Property(QObject, lambda self: self._switches["launch"], constant=True)
    offlineSwitches = Property(QObject, lambda self: self._switches["offline"], constant=True)
    updateSwitches = Property(QObject, lambda self: self._switches["updates"], constant=True)
    me3Switches = Property(QObject, lambda self: self._switches["me3"], constant=True)
    notices = Property(QObject, lambda self: self._notices, constant=True)
    themes = Property(QObject, lambda self: self._choices["theme"], constant=True)
    effectsChoices = Property(QObject, lambda self: self._choices["effects"], constant=True)
    grains = Property(QObject, lambda self: self._choices["grain"], constant=True)
    logos = Property(QObject, lambda self: self._choices["logo"], constant=True)
    logLevels = Property(QObject, lambda self: self._choices["log_level"], constant=True)
    channels = Property(QObject, lambda self: self._choices["launcher_channel"], constant=True)

    # ---- values
    theme = Property(str, lambda self: self._values["theme"], notify=changed)
    effects = Property(str, lambda self: self._values["effects"], notify=changed)
    grain = Property(str, lambda self: self._values["grain"], notify=changed)
    logo = Property(str, lambda self: self._values["logo"], notify=changed)
    logLevel = Property(str, lambda self: self._values["log_level"], notify=changed)
    channel = Property(str, lambda self: self._values["launcher_channel"], notify=changed)
    backupsKeep = Property(int, lambda self: self._values["backups_keep"], notify=changed)
    backupsLocation = Property(str, lambda self: self._values["backups_location"], notify=changed)
    keepFrom = Property(int, lambda self: KEEP_RANGE[0], constant=True)
    keepTo = Property(int, lambda self: KEEP_RANGE[1], constant=True)
    profilesRoot = Property(str, lambda self: self._values["profiles_root"], notify=changed)
    layoutDraft = Property(dict, lambda self: dict(self._draft), notify=changed)
    layoutErrors = Property(dict, lambda self: dict(self._layout_check["errors"]), notify=changed)
    gamePreview = Property(str, lambda self: self._layout_check["preview"], notify=changed)
    layoutDirty = Property(bool, lambda self: self._layout_changes() != {}, notify=changed)
    layoutValid = Property(bool, lambda self: not self._layout_check["errors"], notify=changed)
    moving = Property(bool, lambda self: self._moving, notify=changed)
    labels = Property(dict, lambda self: self._values["labels"], notify=changed)
    steamTarget = Property(str, lambda self: self._values["steam_target"], notify=changed)
    steamOptions = Property(str, lambda self: self._values["steam_options"], notify=changed)
    dataFolder = Property(str, lambda self: self._values["data_folder"], notify=changed)
    versionText = Property(str, lambda self: f"{TITLE} {VERSION}", constant=True)
    launcherLine = Property(
        str, lambda self: self._update.get("line") or self._values["launcher_line"], notify=updatesChanged
    )
    updateChecking = Property(bool, lambda self: bool(self._update.get("checking")), notify=updatesChanged)
    launcherTone = Property(str, lambda self: self._update.get("tone", "muted"), notify=updatesChanged)
    me3Text = Property(str, lambda self: self._me3.text, notify=me3Changed)
    me3Tone = Property(str, lambda self: self._me3.tone, notify=me3Changed)

    # ---- reading the settings again
    def _menu(self, key: str) -> list[dict]:
        """The row's overflow: the folder opener (the page twin of the File menu's) and, for me3, its facts."""
        opener = {
            "me3_path": ("me3", tr("Open me3 folder")),
            "game_exe": ("game", tr("Open game folder")),
            "me3_profile_dir": ("profiles", tr("Open me3 profiles folder")),
            "saves_dir": ("saves", tr("Open saves folder")),
        }[key]
        out = [{"key": opener[0], "label": opener[1], "enabled": True}]
        if key == "me3_path":
            out += [
                {"key": "me3-logs", "label": tr("Open me3 logs"), "enabled": bool(self._me3.logs)},
                {"key": "me3-releases", "label": tr("me3 releases"), "enabled": True},
                {"key": "me3-rescan", "label": tr("Read me3 again"), "enabled": True},
            ]
        return out

    # ---- what the shell's menu and keys may ask of this page (ui/launcher/menu.py)
    COMMANDS = {
        "checkForUpdates": "checkForUpdates",
        "saveLogs": "saveLogs",
    }

    def command(self, name: str, args) -> bool:
        """Run a menu command; False when this page has none by that name."""
        method = self.COMMANDS.get(name)
        if method is None:
            return False
        getattr(self, method)(*args)
        return True

    @Slot()
    def refresh(self) -> None:
        self._refresher.request()

    def _build(self, _snap: object) -> SettingsState:
        """Everything the page reads from the disk or the system (on a worker)."""
        assert_not_ui_thread("Settings facts")
        return view.build(self.host.settings_service.page())

    def _apply(self, st: SettingsState) -> None:
        self._locations.set_rows(
            [
                {
                    "key": r.key,
                    "title": r.title,
                    "help": r.help,
                    "value": r.value,
                    "placeholder": r.placeholder,
                    "isDir": r.is_dir,
                    "menu": self._menu(r.key),
                }
                for r in st.locations
            ]
        )
        grouped: dict[str, list[dict]] = {g: [] for g in self._switches}
        for r in st.switches:
            grouped[r.group].append(
                {
                    "key": r.key,
                    "title": r.title,
                    "blurb": r.blurb,
                    "help": r.help,
                    "checked": r.checked,
                    "shown": r.shown,
                }
            )
        for g, rows_ in grouped.items():
            self._switches[g].set_rows(rows_)
        self._values = {
            "theme": st.theme,
            "effects": st.effects,
            "grain": st.grain,
            "logo": st.logo,
            "log_level": st.log_level,
            "launcher_channel": st.launcher_channel,
            "backups_keep": st.backups_keep,
            "backups_location": st.backups_location,
            "profiles_root": st.profiles_root,
            "steam_target": st.steam_target,
            "steam_options": st.steam_options,
            "data_folder": st.data_folder,
            "labels": st.labels,
            "launcher_line": st.launcher_line,
        }
        edited = self._layout_changes() != {}
        self._saved_layout = dict(st.layout)
        self._saved_root = st.saved_profiles_root
        if not edited:
            self._draft = dict(self._saved_layout)
        self._check_layout()
        if self._moving and not self._move_running():
            self._moving = False
        try:
            self._update = self.host.update_state()
        except Exception:
            pass
        self._show_notices()
        self.changed.emit()
        self.updatesChanged.emit()

    def _move_running(self) -> bool:
        job = self.host.job_manager.get(self._move_job) if self._move_job else None
        return job is not None and job.state == "running"

    def _on_update_state(self) -> None:
        self._update = self.host.update_state()
        self._show_notices()
        self.updatesChanged.emit()

    def _show_notices(self) -> None:
        self._notices.set_rows(
            [
                {
                    "id": n.id,
                    "level": n.level,
                    "title": n.title,
                    "body": n.body,
                    "closable": n.closable,
                    "actions": [
                        {"key": a.key, "label": a.label, "primary": a.primary, "tip": a.tip} for a in n.actions
                    ],
                }
                for n in self._update.get("notices", [])
            ]
        )

    # ---- asking the engine (on the host's worker thread; an OperationError comes back as the result)
    def _ask(self, call, done, quiet: bool = False) -> None:
        """call() on a worker; done(result) on the UI thread, or the refusal's words as a toast. quiet: the refusal is
        a plain notice, not an error."""

        def work() -> Any:
            try:
                return call()
            except OperationError as e:
                return e

        def landed(got: Any) -> None:
            if isinstance(got, OperationError):
                self.notifier.toast(view.refusal_line(got, body_only=quiet), error=not quiet)
                self.refresh()
            else:
                done(got)

        self.host.run_in_background(work, landed)

    # ---- switches and choices
    def _set(self, key: str, value: bool | int | str) -> None:
        self._ask(lambda: self.host.settings_service.set(key, value), self._saved)

    def _saved(self, got: Changed) -> None:
        """A setting was saved: the host follows as the setting says, then the page reads again."""
        if got.follow == "appearance":
            self.host.set_appearance()
        elif got.follow != "none":
            self.host.settings_changed(got.stored_as)
        if got.follow == "updates":
            self.host.check_for_updates()
        self.refresh()
        if line := view.said(got):
            self.notifier.toast(line)

    @Slot(str, bool)
    def setSwitch(self, key: str, on: bool) -> None:
        self._set(key, bool(on))

    @Slot(str, str)
    def setChoice(self, which: str, key: str) -> None:
        self._set(which, key)

    @Slot(int)
    def setBackupsKeep(self, n: int) -> None:
        self._set("backups_keep", int(n))

    # ---- locations
    @Slot(str, str)
    def setLocation(self, key: str, value: str) -> None:
        self._set(key, value)

    @Slot(str)
    def browse(self, key: str) -> None:
        row = next(r for r in self._locations.rows() if r["key"] == key)
        filt = LOCATION_WORDS[key][2]
        picked = (
            self.host.pick_folder(tr("Pick the folder"))
            if row["isDir"]
            else self.host.pick_file(tr("Pick the file"), filt + ";;All files (*)")
        )
        if picked:
            self.setLocation(key, str(picked))

    @Slot(str)
    def clearLocation(self, key: str) -> None:
        self.setLocation(key, "")

    @Slot(str)
    def openFolder(self, kind: str) -> None:
        if kind == "logs":
            self.host.open_logs_folder()
            return
        if kind == "me3-logs":
            logs = Path(self._me3.logs) if self._me3.logs else None
            self._open(str(logs) if logs is not None and logs.exists() else None)
            return
        self._ask(lambda: self.host.settings_service.folder(kind), lambda path: self._open(str(path) if path else None))

    def _open(self, path: str | None) -> None:
        if path is None:
            self.notifier.toast(tr("That folder was not found on this PC."), error=True)
            return
        self.host.open_path(Path(path))

    @Slot(str, str)
    def rowAction(self, key: str, action: str) -> None:
        """An item of a Locations row's overflow."""
        if action == "me3-releases":
            desktop.open_path(view.ME3_RELEASES_URL)
        elif action == "me3-rescan":
            self.readMe3()
        else:
            self.openFolder(action)

    @Slot()
    def readMe3(self) -> None:
        """Ask me3 for its version and folders (it runs me3 info, so on a worker thread)."""

        def done(facts: dict) -> None:
            self._me3 = view.me3_line(facts)
            self.me3Changed.emit()
            self.refresh()

        self.host.run_in_background(lambda: self._safe_me3(), done)

    def _safe_me3(self) -> dict:
        try:
            return self.host.me3_facts()
        except Exception as e:
            return {"error": str(e)}

    # ---- where profiles live, and what the folders are called
    def _layout_changes(self) -> dict[str, tuple[str, str]]:
        return {
            tr(LAYOUT_LABELS[k]): (self._saved_layout[k], v)
            for k, v in self._draft.items()
            if v != self._saved_layout.get(k)
        }

    def _check_layout(self) -> None:
        """The names' problems and the preview, from the engine (a pure read, so it answers at once)."""
        got = self.host.settings_service.check_names(self._draft)
        self._layout_check = {"errors": view.name_errors(got), "preview": got.preview}

    @Slot(str, str)
    def editLayout(self, field: str, value: str) -> None:
        if field in LAYOUT:
            self._draft[field] = value
            self._check_layout()
            self.changed.emit()

    @Slot()
    def applyLayout(self) -> None:
        if not self._layout_changes() or self._layout_check["errors"] or self._moving:
            return
        service, names = self.host.settings_service, dict(self._draft)
        self._offer(
            lambda: service.check_rename(names),
            view.rename_confirm,
            lambda changes: service.rename(names, changes, tr("Renaming folders...")),
        )

    @Slot()
    def changeProfilesFolder(self) -> None:
        picked = self.host.pick_folder(tr("Pick the profiles folder"))
        if not picked:
            return
        service, root = self.host.settings_service, self._saved_root
        self._offer(
            lambda: service.check_relocate(str(picked)),
            view.relocate_confirm,
            lambda checked: service.relocate(checked.folder, root, tr("Moving profiles and mods...")),
            moves_root=True,
        )

    @Slot()
    def cancelMove(self) -> None:
        if self._move_job:
            self.host.job_manager.cancel(self._move_job)

    @Slot()
    def moveAll(self) -> None:
        service = self.host.settings_service
        self._offer(
            service.check_move_all,
            view.move_all_confirm,
            lambda names: service.move_all(names, tr("Moving profiles...")),
            quiet=True,
        )

    def _offer(self, check, confirm, start, quiet: bool = False, moves_root: bool = False) -> None:
        """Check on a worker, show the Confirm of what was checked, and on OK start the job with exactly that (the
        engine says stale when it changed since); the host follows the job on the event bus."""

        def started(job_id: str) -> None:
            if moves_root:
                self._move_job, self._moving = str(job_id), True
                self.changed.emit()

        def shown(checked: Any) -> None:
            self.notifier.confirm(
                confirm(checked), lambda ok: self._ask(lambda: start(checked), started, quiet) if ok else None
            )

        self._ask(check, shown, quiet)

    # ---- launch
    def _copy(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)
        self.notifier.toast(tr("Copied"))

    @Slot(str)
    def copySteam(self, which: str) -> None:
        self._copy(self._values["steam_target"] if which == "target" else self._values["steam_options"])

    @Slot()
    def pointSteamShortcuts(self) -> None:
        self.host.point_steam_shortcuts()

    @Slot()
    def clearLeftovers(self) -> None:
        if self.host.busy:
            self.notifier.toast(tr("Wait for the current job."), error=True)
            return
        self._ask(
            lambda: self.host.settings_service.clear_leftovers(tr("Clearing leftover processes...")), lambda _id: None
        )

    # ---- updates, logs, about
    @Slot()
    def checkForUpdates(self) -> None:
        self.host.check_for_updates()

    @Slot()
    def openReleases(self) -> None:
        desktop.open_path(RELEASES_URL)

    @Slot()
    def saveLogs(self) -> None:
        self.host.save_logs_for_support()

    @Slot(str)
    def openLicence(self, file: str) -> None:
        if file in view.LICENCE_FILES:
            desktop.open_path(view.licence_url(file))

    @Slot(str, str)
    def noticeAction(self, notice_id: str, key: str) -> None:
        self.host.notice_action(notice_id, key)

    @Slot(str)
    def dismissNotice(self, notice_id: str) -> None:
        self.host.dismiss_notice(notice_id)

    # ---- for tests and the self-test
    def snapshot(self) -> dict:
        return {
            "locations": self._locations.rows(),
            "launch": self._switches["launch"].rows(),
            "values": dict(self._values),
        }
