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

from roundtable_souls.config.settings import data_dir, game_setting, load_settings, save_game_settings, save_settings
from roundtable_souls.game import catalog as games
from roundtable_souls.game.locate import saves_dir_problem
from roundtable_souls.platform import data_folder, desktop
from roundtable_souls.services import mods as mod_service
from roundtable_souls.services import play as play_service
from roundtable_souls.ui.models import RowsModel
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.settings import presenter as sp
from roundtable_souls.ui.text import tr

KEEP_RANGE = (5, 200)


class SettingsHost(Protocol):
    """What the page needs from the window that hosts it."""

    @property
    def busy(self) -> bool: ...
    @property
    def game(self) -> Any: ...
    @property
    def locations(self) -> Any: ...
    def run_job(self, job, status: str) -> None: ...
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


# key, title, help, is a folder, file filter
LOCATIONS = (
    (
        "me3_path",
        "me3",
        "Blank means detect: me3 from PATH, then its default install folder. Set one only for a portable or custom me3.",
        False,
        "me3 (me3.exe)",
    ),
    (
        "game_exe",
        "Game executable",
        "Blank means the Steam library that holds the game. Per game. me3 launches a custom exe directly.",
        False,
        "Game (*.exe)",
    ),
    (
        "me3_profile_dir",
        "Profile folder",
        "Blank means the folder me3 info reports. Where .me3 profiles are listed from.",
        True,
        "",
    ),
    (
        "saves_dir",
        "Saves folder",
        "Blank means detect from your Steam account. Per game. It must hold your Steam account's folder with the "
        "game's save in it; backups, repairs and the Saves page all use it.",
        True,
        "",
    ),
)
CHOICES = {
    "theme": (("dark", "Dark"), ("tarnished", "Tarnished"), ("light", "Light"), ("system", "System")),
    "effects": (("full", "Full"), ("reduced", "Reduced"), ("off", "Off")),
    "grain": (("off", "Off"), ("subtle", "Subtle"), ("film", "Film")),
    "logo": (("auto", "Follows theme"), ("dark", "Dark"), ("light", "Light")),
    "log_level": (("normal", "Normal"), ("verbose", "Verbose")),
    "launcher_channel": (("stable", "Stable"), ("beta", "Beta")),
}


class SettingsAdapter(QObject):
    changed = Signal()
    updatesChanged = Signal()
    me3Changed = Signal()

    def __init__(self, host: SettingsHost, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self._me3 = sp.Me3Line(tr("Checking me3..."), "muted", "", "", "", "", False)
        self._update: dict = {"line": "", "tone": "muted", "notices": []}
        self._locations = RowsModel(("key", "title", "help", "value", "placeholder", "isDir", "menu"), self)
        self._switches = {
            g: RowsModel(("key", "title", "blurb", "help", "checked", "shown"), self)
            for g in ("launch", "offline", "updates", "me3")
        }
        self._notices = RowsModel(("id", "level", "title", "body", "closable", "actions"), self)
        self._choices = {k: RowsModel(("key", "label"), self) for k in CHOICES}
        for k, rows in CHOICES.items():
            self._choices[k].set_rows([{"key": a, "label": tr(b)} for a, b in rows])
        self._values: dict[str, Any] = {}
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
            "launchHint": tr(
                "What Play does around the game. The game never starts with merged mods that are out of date without "
                "asking you first; the steps below can be turned off, the launch itself always runs."
            ),
            "offline": sp.OFFLINE_TITLE,
            "offlineBlurb": sp.OFFLINE_BLURB,
            "offlineHelp": sp.OFFLINE_HELP,
            "steam": tr("Steam shortcut"),
            "steamHelp": tr("Play from Steam without this window; one shortcut per game."),
            "copyTarget": tr("Copy target"),
            "copyOptions": tr("Copy launch options"),
            "pointSteam": tr("Point Steam shortcuts here"),
            "pointSteamTip": tr(
                "Steam shortcuts with --play that start a Roundtable Souls program in another folder (an older "
                "install) start this copy instead. Steam must be closed; a backup of each changed file is kept."
            ),
            "leftover": tr("Leftover processes"),
            "leftoverHelp": tr("A dead copy of the game can make Discord think it is still open."),
            "clearNow": tr("Clear now"),
            "backups": tr("Backups"),
            "backupsLocation": tr("Location"),
            "backupsLocationHelp": tr("Inside the launcher's data folder. Moving it is not offered yet."),
            "backupsKeep": tr("How many to keep"),
            "backupsKeepHelp": tr(
                "Per save file. Everything from the last 7 days is kept too, and so is any backup you marked Keep."
            ),
            "appearance": tr("Appearance"),
            "theme": tr("Theme"),
            "themeHelp": tr(
                "System follows the OS. Tarnished is the dark theme in the Lands Between olive. The older window "
                "shows Tarnished as Dark."
            ),
            "effects": tr("Effects"),
            "effectsHelp": tr("Off: no blur, no grain; blooms stay. Reduced: no blur, lighter grain."),
            "grain": tr("Grain"),
            "grainHelp": tr("Fine texture on the page backdrop and glass panels. Subtle is hardly seen; Film is."),
            "logo": tr("Logo"),
            "logoHelp": tr("Follows the theme."),
            "updates": tr("Updates"),
            "channel": tr("Update channel"),
            "channelHelp": tr(
                "Stable offers releases. Beta also offers pre-releases, which get less testing. Going back to Stable "
                "never installs an older version."
            ),
            "check": tr("Check for updates"),
            "releases": tr("Releases"),
            "releasesTip": tr("Every version of this launcher, with notes and downloads."),
            "logs": tr("Logs"),
            "logsFolder": tr("Logs folder"),
            "openFolder": tr("Open folder"),
            "saveLogs": tr("Save logs for support"),
            "saveLogsHelp": tr("A zip of the recent logs with user names and Steam IDs masked."),
            "save": tr("Save..."),
            "settingsFolder": tr("Settings folder"),
            "logLevel": tr("Log level"),
            "logLevelHelp": tr("Verbose also writes the fine detail to launcher.log. It applies from the next start."),
            "about": tr("About"),
            "aboutHelp": tr("GPL-3.0. Built on PySide6 and me3."),
            "licence": tr("Licence"),
            "notices": tr("Third-party notices"),
            "browse": tr("Browse..."),
            "more": tr("More"),
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
    labels = Property(dict, lambda self: self._values["labels"], notify=changed)
    steamTarget = Property(str, lambda self: self._values["steam_target"], notify=changed)
    steamOptions = Property(str, lambda self: self._values["steam_options"], notify=changed)
    dataFolder = Property(str, lambda self: self._values["data_folder"], notify=changed)
    versionText = Property(str, lambda self: f"{sp.TITLE} {sp.VERSION}", constant=True)
    launcherLine = Property(
        str, lambda self: self._update.get("line") or self._values["launcher_line"], notify=updatesChanged
    )
    launcherTone = Property(str, lambda self: self._update.get("tone", "muted"), notify=updatesChanged)
    me3Text = Property(str, lambda self: self._me3.text, notify=me3Changed)
    me3Tone = Property(str, lambda self: self._me3.tone, notify=me3Changed)

    # ---- reading the settings again
    def _game(self):
        return getattr(self.host, "game", None) or games.ELDEN_RING

    def _detected(self, key: str) -> str:
        """What Blank detects now, for the field's placeholder."""
        loc = self.host.locations
        if loc is None:
            return tr("detected")
        try:
            found: Path | None = None
            if key == "me3_path":
                found = loc.me3_exe()
            elif key == "game_exe":
                found = loc.game_dir()
            elif key == "me3_profile_dir":
                found = loc.me3_profiles_dir()
            elif key == "saves_dir":
                found = next(iter(loc.save_roots()), None)
            return tr("detected: {path}").format(path=found) if found else tr("detected")
        except Exception:
            return tr("detected")

    def _menu(self, key: str) -> list[dict]:
        """The row's overflow: the folder opener (the page twin of the File menu's) and, for me3, its facts."""
        opener = {
            "me3_path": ("me3", tr("Open me3 folder")),
            "game_exe": ("game", tr("Open game folder")),
            "me3_profile_dir": ("profiles", tr("Open profile folder")),
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
        s = load_settings()
        game = self._game()
        rows = []
        for key, title, help_text, is_dir, _filter in LOCATIONS:
            value = (
                str(game_setting(s, game.key, key) or "")
                if key in ("game_exe", "saves_dir")
                else str(getattr(s, key) or "")
            )
            rows.append(
                {
                    "key": key,
                    "title": tr(title),
                    "help": tr(help_text),
                    "value": value,
                    "placeholder": self._detected(key),
                    "isDir": is_dir,
                    "menu": self._menu(key),
                }
            )
        self._locations.set_rows(rows)
        try:
            overhaul = mod_service.overhaul_switch_text(game.key) if mod_service.installable_overhauls(game.key) else ""
        except Exception:
            overhaul = ""
        grouped: dict[str, list[dict]] = {g: [] for g in self._switches}
        for spec in sp.switches(overhaul, game.key):
            attr = play_service.repair_key(game) if spec.key == "play_repair_after" else spec.key
            grouped[spec.group].append(
                {
                    "key": spec.key,
                    "title": spec.title,
                    "blurb": spec.blurb,
                    "help": spec.help,
                    "checked": bool(getattr(s, attr, False)),
                    "shown": bool(spec.blurb) or spec.key != "overhaul_install",
                }
            )
        for g, rows_ in grouped.items():
            self._switches[g].set_rows(rows_)
        try:
            target, options = play_service.play_command(game)
        except Exception:
            target, options = "", ""
        self._values = {
            "theme": s.theme,
            "effects": s.effects,
            "grain": s.grain,
            "logo": s.logo,
            "log_level": s.log_level,
            "launcher_channel": s.launcher_channel,
            "backups_keep": s.backups_keep if KEEP_RANGE[0] <= s.backups_keep <= KEEP_RANGE[1] else 20,
            "backups_location": str(self._backups_folder()),
            "steam_target": target,
            "steam_options": options,
            "data_folder": sp.data_location(),
            "labels": {
                which: next((tr(b) for k, b in CHOICES[which] if k == getattr(s, which)), "") for which in CHOICES
            },
            "launcher_line": f"{sp.TITLE} {sp.VERSION}  ·  {sp.install_kind()}",
        }
        try:
            self._update = self.host.update_state()
        except Exception:
            pass
        self._show_notices()
        self.changed.emit()
        self.updatesChanged.emit()

    @staticmethod
    def _backups_folder() -> Path:
        try:
            return data_folder.data_root() / "saves"
        except RuntimeError:  # the data folder is set when the program starts
            return data_dir() / "saves"

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

    # ---- switches and choices
    @Slot(str, bool)
    def setSwitch(self, key: str, on: bool) -> None:
        game = self._game()
        attr = play_service.repair_key(game) if key == "play_repair_after" else key
        save_settings(**{attr: bool(on)})
        self.host.settings_changed(attr)
        self.refresh()

    @Slot(str, str)
    def setChoice(self, which: str, key: str) -> None:
        if which not in CHOICES or key not in dict(CHOICES[which]):
            return
        save_settings(**{which: key})
        if which in ("theme", "effects", "grain"):
            self.host.set_appearance()
        else:
            self.host.settings_changed(which)
        if which == "launcher_channel":
            self.host.check_for_updates()
        if which == "log_level":
            self.notifier.toast(tr("The log level applies from the next start."))
        self.refresh()

    @Slot(int)
    def setBackupsKeep(self, n: int) -> None:
        n = max(KEEP_RANGE[0], min(KEEP_RANGE[1], int(n)))
        save_settings(backups_keep=n)
        self.refresh()

    # ---- locations
    def _problem(self, key: str, value: str) -> str:
        is_dir = next(r[3] for r in LOCATIONS if r[0] == key)
        if key == "saves_dir":
            return saves_dir_problem(value, self._game())
        if is_dir:
            return "" if Path(value).is_dir() else tr("That folder does not exist.")
        return "" if Path(value).is_file() else tr("That file does not exist.")

    @Slot(str, str)
    def setLocation(self, key: str, value: str) -> None:
        value = value.strip()
        if value:
            problem = self._problem(key, value)
            if problem:
                self.notifier.toast(problem, error=True)
                self.refresh()
                return
        if key in ("game_exe", "saves_dir"):
            save_game_settings(self._game().key, **{key: value})
        else:
            save_settings(**{key: value})
        self.host.settings_changed(key)
        self.refresh()
        self.notifier.toast(
            tr("Location updated") + (" " + Path(value).name if value else " " + tr("Detecting again."))
        )

    @Slot(str)
    def browse(self, key: str) -> None:
        _key, title, _help, is_dir, filt = next(r for r in LOCATIONS if r[0] == key)
        picked = (
            self.host.pick_folder(tr("Pick the folder"))
            if is_dir
            else self.host.pick_file(tr("Pick the file"), filt + ";;All files (*)")
        )
        if picked:
            self.setLocation(key, str(picked))

    @Slot(str)
    def clearLocation(self, key: str) -> None:
        self.setLocation(key, "")

    def _folder(self, kind: str) -> Path | None:
        loc = self.host.locations
        try:
            if kind == "me3" and loc is not None:
                exe = loc.me3_exe()
                return Path(exe).parent if exe else None
            if kind == "game" and loc is not None:
                return loc.game_dir()
            if kind == "profiles" and loc is not None:
                return loc.me3_profiles_dir()
            if kind == "saves" and loc is not None:
                return next((r for r in loc.save_roots() if r.is_dir()), None)
        except Exception:
            return None
        if kind == "backups":
            return self._backups_folder()
        if kind == "settings":
            return data_dir()
        if kind == "me3-logs":
            return Path(self._me3.logs) if self._me3.logs else None
        return None

    @Slot(str)
    def openFolder(self, kind: str) -> None:
        if kind == "logs":
            self.host.open_logs_folder()
            return
        if kind == "backups":
            self._backups_folder().mkdir(parents=True, exist_ok=True)
        folder = self._folder(kind)
        if folder is None or not Path(folder).exists():
            self.notifier.toast(tr("That folder was not found on this PC."), error=True)
            return
        self.host.open_path(Path(folder))

    @Slot(str, str)
    def rowAction(self, key: str, action: str) -> None:
        """An item of a Locations row's overflow."""
        if action == "me3-releases":
            desktop.open_path(sp.ME3_RELEASES_URL)
        elif action == "me3-rescan":
            self.readMe3()
        else:
            self.openFolder(action)

    @Slot()
    def readMe3(self) -> None:
        """Ask me3 for its version and folders (it runs me3 info, so on a worker thread)."""

        def done(facts: dict) -> None:
            self._me3 = sp.me3_line(facts)
            self.me3Changed.emit()
            self.refresh()

        self.host.run_in_background(lambda: self._safe_me3(), done)

    def _safe_me3(self) -> dict:
        try:
            return self.host.me3_facts()
        except Exception as e:
            return {"error": str(e)}

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
        self.host.run_job(play_service.job_clear, tr("Clearing leftover processes..."))

    # ---- updates, logs, about
    @Slot()
    def checkForUpdates(self) -> None:
        self.host.check_for_updates()

    @Slot()
    def openReleases(self) -> None:
        desktop.open_path(sp.RELEASES_URL)

    @Slot()
    def saveLogs(self) -> None:
        self.host.save_logs_for_support()

    @Slot(str)
    def openLicence(self, file: str) -> None:
        if file in sp.LICENCE_FILES:
            desktop.open_path(sp.licence_url(file))

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
