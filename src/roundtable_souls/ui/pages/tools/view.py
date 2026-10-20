"""Settings (the Tools page): locations, folders, me3, Play session switches, appearance, the launcher's own updates
and its Steam shortcuts.

Part of the window: ui/shell.Launcher inherits ToolsView, so its methods share the window's state (self). Moved
from ui/window.py as it was; the page's presenter (plain Python, no Qt) comes in the page-by-page work."""

# The window's state is spread over the shell and the page views, which pyright cannot follow across mixins.
# pyright: reportAttributeAccessIssue=false

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    FlowLayout,
    LineEdit,
    SwitchButton,
    Theme,
    setTheme,
    setThemeColor,
)
from qfluentwidgets import FluentIcon as FI

from roundtable_souls.config.settings import FROZEN
from roundtable_souls.platform import desktop
from roundtable_souls.services import mods as mod_service
from roundtable_souls.services import play as play_service
from roundtable_souls.services.mods import (
    me3_facts,
)
from roundtable_souls.services.play import (
    TITLE,
    VERSION,
    discover,
    job_clear,
    job_repair,
    places,
    play_command,
    remembered_setup,
)
from roundtable_souls.services.saves import (
    dead_shells_count,
)
from roundtable_souls.services.settings import (
    game_setting,
    load_settings,
    save_game_settings,
    save_settings,
)
from roundtable_souls.services.updates import RELEASES_URL
from roundtable_souls.ui.pages.settings import presenter as sp
from roundtable_souls.ui.theme import (
    ACCENT,
    ACCENT_LIGHT,
    ghost_btn,
    hint,
    primary_btn,
    tone_label,
    widgets_dark,
)
from roundtable_souls.ui.widgets.cards import ExpandGroupSettingCard, LogoPreview, PairRow, SettingRow, card, icon_btn
from roundtable_souls.ui.widgets.layout import action_row, page, titled
from roundtable_souls.ui.widgets.notices import notice
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import feed
from roundtable_souls.updates import inno as migration


class ToolsView:
    """The tools page's widgets and handlers (a mixin of ui/shell.Launcher)."""

    # ---------------------------------------------------------------- Tools page
    def _build_tools(self):
        self.tools_page, lay = page("toolsPage")
        titled(lay, "Settings", FI.SETTING)
        b = ghost_btn(sp.OPEN_WINDOW_TEXT, FI.LINK)
        b.setToolTip(sp.OPEN_WINDOW_TIP)
        b.clicked.connect(self._open_settings_window)
        row_w, row = action_row()
        row.addWidget(b)
        lay.addWidget(row_w)
        c, cl = card("Launcher", FI.INFO)
        self.launcher_line = BodyLabel(f"{TITLE} {VERSION}  \u00b7  {sp.install_kind()}")
        tone_label(self.launcher_line, "muted")
        self.launcher_line.setWordWrap(True)
        cl.addWidget(self.launcher_line)
        row_w, row = action_row()
        b = ghost_btn("Check for updates", FI.UPDATE)
        b.setToolTip("Ask GitHub now whether a newer version exists.")
        b.clicked.connect(lambda: self._check_launcher_update(force=True))
        row.addWidget(b)
        b = ghost_btn("Releases", FI.LINK)
        b.setToolTip("Every version of this launcher, with notes and downloads.")
        b.clicked.connect(lambda: desktop.open_path(RELEASES_URL))
        row.addWidget(b)
        b = ghost_btn("Logs", FI.DOCUMENT)
        b.setToolTip("This launcher's own logs, for when something goes wrong.")
        b.clicked.connect(lambda: self._open_logs_folder())
        row.addWidget(b)
        cl.addWidget(row_w)
        sw = SwitchButton()
        sw.setOnText("On")
        sw.setOffText("Off")
        sw.setChecked(bool(self.settings.check_launcher_updates))
        sw.checkedChanged.connect(lambda checked: self._remember_play("check_launcher_updates", checked))
        self.play_sw = {"check_launcher_updates": sw}
        spec = sp.switch("check_launcher_updates")
        cl.addWidget(SettingRow(spec.title, spec.blurb, sw, spec.help))
        self.channel_box = ComboBox()
        self.channel_box.addItems(["Stable", "Beta"])
        self.channel_box.setMinimumWidth(140)
        self.channel_box.blockSignals(True)
        self.channel_box.setCurrentIndex(1 if self.settings.launcher_channel == "beta" else 0)
        self.channel_box.blockSignals(False)
        self.channel_box.currentIndexChanged.connect(self._on_channel)
        cl.addWidget(
            SettingRow(
                "Update channel",
                "Stable offers releases. Beta also offers pre-releases, which get less testing.",
                self.channel_box,
                "Going back to Stable never installs an older version: the next stable release is offered once it is "
                "newer than this one.",
            )
        )
        lay.addWidget(c)
        c, cl = card("Steam shortcut", FI.GAME)
        self.shortcut_hint = hint("")
        cl.addWidget(self.shortcut_hint)
        self.shortcut_fields = {}
        target, options = play_command(self.game)
        for label, value in (("Target", target), ("Launch options", options)):
            row_w, row = action_row()
            field = LineEdit()
            field.setText(value)
            field.setReadOnly(True)
            field.setMinimumWidth(220)
            field.setAccessibleName(label)
            self.shortcut_fields[label] = field
            row.addWidget(BodyLabel(label))
            row.addWidget(field)
            copy = ghost_btn("Copy", FI.COPY)
            copy.clicked.connect(
                lambda _=False, f=field, n=label: (
                    QApplication.clipboard().setText(f.text()),
                    self._toast("Copied", n, info=True),
                )
            )
            row.addWidget(copy)
            cl.addWidget(row_w)
        row_w, row = action_row()
        b = ghost_btn("Point Steam shortcuts here", FI.LINK)
        b.setToolTip(
            "Steam shortcuts with --play that start a Roundtable Souls program in another folder (an older install) "
            "start this copy instead. Steam must be closed; a backup of each changed file is kept."
        )
        b.clicked.connect(self._point_steam_shortcuts)
        row.addWidget(b)
        cl.addWidget(row_w)
        lay.addWidget(c)
        c, cl = card("Appearance", FI.BRUSH)
        row = QHBoxLayout()
        self.theme_sw = SwitchButton()
        self.theme_sw.setOnText("Dark")
        self.theme_sw.setOffText("Light")
        self.theme_sw.setChecked(widgets_dark(self.settings.theme))
        self.theme_sw.checkedChanged.connect(self._on_theme)
        row.addWidget(BodyLabel("Theme"))
        row.addWidget(self.theme_sw)
        row.addStretch()
        cl.addLayout(row)
        brand = QHBoxLayout()
        brand.setSpacing(12)
        self.logo_preview = LogoPreview()
        brand.addWidget(self.logo_preview, 0, Qt.AlignVCenter)
        brand.addWidget(BodyLabel("Logo"), 0, Qt.AlignVCenter)
        self.logo_box = ComboBox()
        self.logo_box.addItems(["Follow theme", "Dark", "Light"])
        self.logo_box.setMinimumWidth(140)
        mode = self.settings.logo
        self.logo_box.blockSignals(True)
        self.logo_box.setCurrentIndex({"auto": 0, "dark": 1, "light": 2}.get(mode, 0))
        self.logo_box.blockSignals(False)
        self.logo_box.currentIndexChanged.connect(self._on_logo)
        brand.addWidget(self.logo_box, 0, Qt.AlignVCenter)
        brand.addStretch()
        cl.addLayout(brand)
        cl.addWidget(hint("Follow theme switches the logo with light and dark."))
        lay.addWidget(c)
        self._apply_logo()
        c, cl = card("Maintenance", FI.UPDATE)
        b = ghost_btn("Repair", FI.UPDATE)
        b.clicked.connect(lambda: self.start(job_repair, "Repairing saves...", need_setup=False))
        self.repair_row = PairRow(
            "Repair saves",
            "Runs after a session when this game needs it. Use this if the window was closed first.",
            b,
        )
        cl.addWidget(self.repair_row)
        b = ghost_btn("Clear", FI.DELETE)
        b.clicked.connect(lambda: self.start(job_clear, "Clearing leftover processes...", need_setup=False))
        cl.addWidget(
            PairRow("Leftover processes", "A dead copy of the game can make Discord think it is still open.", b)
        )
        lay.addWidget(c)
        c, cl = card("Play session", FI.PLAY)
        cl.addWidget(
            hint(
                "What Play does around the game. The game never starts with merged mods that are out of date (a "
                "removed or changed mod still inside them) without asking you first. The steps below can be turned "
                "off; the launch itself always runs."
            )
        )
        rows = tuple(
            (sw.key, sw.title, sw.blurb, sw.help)
            for sw in sp.switches(mod_service.overhaul_switch_text(self.game.key), self.game.key)
            if sw.group == "launch"
        )
        self.play_rows = {}
        for key, title, blurb, help_text in rows:
            sw = SwitchButton()
            sw.setOnText("On")
            sw.setOffText("Off")
            sw.setChecked(bool(getattr(self.settings, key)))
            sw.checkedChanged.connect(lambda checked, k=key: self._remember_play(k, checked))
            self.play_sw[key] = sw
            self.play_rows[key] = SettingRow(title, blurb, sw, help_text)
            cl.addWidget(self.play_rows[key])
        lay.addWidget(c)
        c, cl = card("Locations", FI.FOLDER)
        cl.addWidget(
            hint(
                "Blank means detect: me3 from PATH or its installer, the game from Steam, profiles from where me3 info says. Set one only when that is wrong for this PC. The game executable is kept per game."
            )
        )
        self.loc = {}
        for key, title, blurb, is_dir, filt in (
            ("me3_path", "me3.exe", "A portable or custom me3 install.", False, "me3 (me3.exe)"),
            (
                "game_exe",
                "Game executable",
                "The game's exe outside Steam's usual folder, for the game picked at the top. me3 then launches it directly.",
                False,
                "Game (*.exe)",
            ),
            ("me3_profile_dir", "Profile folder", "Where .me3 profiles are listed from.", True, ""),
        ):
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            lab = hint(str(self._location_value(key)) or "detected")
            lab.setMaximumWidth(360)
            bl.addWidget(lab, 1)
            b = ghost_btn("Browse", FI.FOLDER)
            b.clicked.connect(lambda _=False, k=key, d=is_dir, f=filt: self._pick_location(k, d, f))
            bl.addWidget(b)
            x = icon_btn(FI.CANCEL, "Clear: detect it again")
            x.clicked.connect(lambda _=False, k=key: self._set_location(k, ""))
            bl.addWidget(x)
            self.loc[key] = lab
            cl.addWidget(SettingRow(title, blurb, box, blurb))
        lay.addWidget(c)
        c, cl = card("me3", FI.CODE)
        self.me3_line = BodyLabel("Checking me3...")
        self.me3_line.setWordWrap(True)
        cl.addWidget(self.me3_line)
        row_w, row = action_row()
        self.me3_dir_btn = ghost_btn("me3 folder", FI.FOLDER)
        self.me3_dir_btn.setEnabled(False)
        self.me3_dir_btn.clicked.connect(lambda: desktop.open_path(self.me3_dir_btn.toolTip()))
        row.addWidget(self.me3_dir_btn)
        self.me3_logs_btn = ghost_btn("me3 logs", FI.DOCUMENT)
        self.me3_logs_btn.setEnabled(False)
        self.me3_logs_btn.clicked.connect(lambda: desktop.open_path(self.me3_logs_btn.toolTip()))
        row.addWidget(self.me3_logs_btn)
        self.me3_prof_btn = ghost_btn("Profile folder", FI.FOLDER)
        self.me3_prof_btn.setEnabled(False)
        self.me3_prof_btn.clicked.connect(lambda: desktop.open_path(self.me3_prof_btn.toolTip()))
        row.addWidget(self.me3_prof_btn)
        b = ghost_btn("me3 releases", FI.LINK)
        b.setToolTip("me3's own releases page on GitHub.")
        b.clicked.connect(lambda: desktop.open_path("https://github.com/garyttierney/me3/releases"))
        row.addWidget(b)
        b = ghost_btn("Refresh", FI.SYNC)
        b.setToolTip("Read the installed me3 again.")
        b.clicked.connect(self._refresh_me3)
        row.addWidget(b)
        cl.addWidget(row_w)
        sw = SwitchButton()
        sw.setOnText("On")
        sw.setOffText("Off")
        sw.setChecked(bool(self.settings.check_me3_updates))
        sw.checkedChanged.connect(lambda checked: self._remember_play("check_me3_updates", checked))
        self.play_sw["check_me3_updates"] = sw
        spec = sp.switch("check_me3_updates")
        cl.addWidget(SettingRow(spec.title, spec.blurb, sw, spec.help))
        lay.addWidget(c)
        offline = ExpandGroupSettingCard(FI.CLOUD, sp.OFFLINE_TITLE, "Solo on the standard save.")
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(8, 4, 8, 12)
        bl.setSpacing(4)
        bl.addWidget(hint(sp.OFFLINE_BLURB + " " + sp.OFFLINE_HELP))
        self.off_revive = SwitchButton()
        self.off_revive.setOnText("On")
        self.off_revive.setOffText("Off")
        self.off_revive.setChecked(bool(self.settings.offline_strip_revive))
        self.off_steam = SwitchButton()
        self.off_steam.setOnText("On")
        self.off_steam.setOffText("Off")
        self.off_steam.setChecked(bool(self.settings.offline_start_steam))
        self.off_quiet = SwitchButton()
        self.off_quiet.setOnText("On")
        self.off_quiet.setOffText("Off")
        self.off_quiet.setChecked(bool(self.settings.offline_skip_confirm))
        off = {x.key: x for x in sp.switches() if x.group == "offline"}
        self.off_revive_row = SettingRow(
            off["offline_strip_revive"].title,
            off["offline_strip_revive"].blurb,
            self.off_revive,
            off["offline_strip_revive"].help,
        )
        bl.addWidget(self.off_revive_row)
        for key, sw in (("offline_start_steam", self.off_steam), ("offline_skip_confirm", self.off_quiet)):
            bl.addWidget(SettingRow(off[key].title, off[key].blurb, sw, off[key].help))
        for sw in (self.off_revive, self.off_steam, self.off_quiet):
            sw.checkedChanged.connect(self._remember_offline)
        row = QHBoxLayout()
        b = ghost_btn("Play offline", FI.PLAY)
        b.clicked.connect(self.launch_offline)
        row.addWidget(b)
        row.addStretch()
        bl.addLayout(row)
        offline.addGroupWidget(body)
        lay.addWidget(offline)
        self.offline_exp = offline
        files = ExpandGroupSettingCard(
            FI.FOLDER, "Folders", "me3, the game, your saves, and this launcher's own files."
        )
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(16, 8, 16, 12)
        row = FlowLayout(needAni=False)
        row.setContentsMargins(0, 0, 0, 0)
        row.setHorizontalSpacing(8)
        row.setVerticalSpacing(8)
        row.addWidget(self._folder_btn("me3", "me3", FI.CODE, "Where me3.exe lives."))
        row.addWidget(
            self._folder_btn(
                "game", "Game", FI.GAME, "The game's own folder: its exe, regulation.bin, and mods that install there."
            )
        )
        row.addWidget(
            self._folder_btn("saves", "Saves", FI.SAVE, "The folder with your save files and the backup folders.")
        )
        b = ghost_btn("Logs", FI.DOCUMENT)
        b.setToolTip("The launcher's own logs.")
        b.clicked.connect(lambda: self._open_logs_folder())
        row.addWidget(b)
        b = ghost_btn("Settings folder", FI.FOLDER)
        b.setToolTip("Roundtable Souls's settings file.")
        b.clicked.connect(lambda: desktop.open_path(str(self.ctx.data_dir)))
        row.addWidget(b)
        bl.addLayout(row)
        where = updates.data_location_text()
        p = hint(where)
        p.setToolTip(str(self.ctx.data_dir))
        bl.addWidget(p)
        files.addGroupWidget(body)
        lay.addWidget(files)
        lay.addStretch(1)

    def _open_logs_folder(self):
        logs = self.ctx.data_dir / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        desktop.open_path(str(logs))

    def _open_place(self, key, label):
        p = places(self.setup, self.ctx.locations).get(key)
        if not p:
            why = {
                "me3": "me3 was not found on this PC. Set it under Locations, or install it.",
                "game": f"The game folder is unknown: Steam did not report {self.game.name}, and no game exe is set under Locations.",
                "saves": f"No {self.game.name} save folder in this Windows account yet.",
                "profile": "Pick a setup on Play first.",
                "mods": "Pick a setup on Play first.",
            }.get(key, "Unknown folder.")
            self._toast(f"No {label.lower()} folder", why, error=True)
            return
        desktop.open_path(str(p))

    def _folder_btn(self, key, label, icon=FI.FOLDER, tip=""):
        b = ghost_btn(label, icon)
        b.setToolTip(tip or f"Open the {label.lower()} folder in Explorer.")
        b.clicked.connect(lambda _=False, k=key, l=label: self._open_place(k, l))
        return b

    def _location_value(self, key):
        """A Locations value; the game executable is the active game's own."""
        if key == "game_exe":
            return str(game_setting(self.settings, self.game.key, "game_exe") or "")
        return str(getattr(self.settings, key) or "")

    def _pick_location(self, key, is_dir, filt):
        if is_dir:
            p = QFileDialog.getExistingDirectory(self, "Pick the folder", self._location_value(key))
        else:
            p, _ = QFileDialog.getOpenFileName(
                self, "Pick the file", self._location_value(key), filt + ";;All files (*)"
            )
        if p:
            self._set_location(key, p)

    def _set_location(self, key, value):
        if key == "game_exe":
            save_game_settings(self.game.key, game_exe=value)
        else:
            save_settings(**{key: value})
        self._after_location(key)
        self._toast("Location updated", "Detecting again." if not value else Path(value).name)

    def _after_location(self, key):
        """A location was saved (here or on the new Settings page): read the settings again and detect again."""
        self.settings = self.ctx.reload_settings()
        if key in self.loc:
            value = self._location_value(key)
            self.loc[key].setText(value or "detected")
            self.loc[key].setToolTip(value)
        self.setups = (
            discover(remembered_setup(self.settings, self.game), self.ctx.locations) if self.game.ready else []
        )
        self._fill_setups()
        self._refresh_me3()
        self._fill_mods()
        self._update_plan()
        if key == "saves_dir":
            self.refresh_saves()

    def _settings_changed(self, key):
        """The new Settings page saved key: this window follows (its switches, locations, theme and logo)."""
        if key in ("me3_path", "game_exe", "me3_profile_dir", "saves_dir"):
            self._after_location(key)
            return
        self.settings = self.ctx.reload_settings()
        if key == "warn_dead_shells":
            self._on_shells(dead_shells_count(loc=self.ctx.locations))
        elif key == "overhaul_install":
            self._sync_overhaul_button()
        elif key == "logo":
            self.logo_box.blockSignals(True)
            self.logo_box.setCurrentIndex({"auto": 0, "dark": 1, "light": 2}.get(self.settings.logo, 0))
            self.logo_box.blockSignals(False)
            self._apply_logo()
        elif key == "theme":
            dark = widgets_dark(self.settings.theme)
            self.theme_sw.blockSignals(True)
            self.theme_sw.setChecked(dark)
            self.theme_sw.blockSignals(False)
            setTheme(Theme.DARK if dark else Theme.LIGHT)
            setThemeColor(ACCENT if dark else ACCENT_LIGHT)
            self._restyle()
        elif key == "launcher_channel":
            self._offered = None
            self.channel_box.blockSignals(True)
            self.channel_box.setCurrentIndex(1 if self.settings.launcher_channel == "beta" else 0)
            self.channel_box.blockSignals(False)
        switches = {**self.play_sw, "offline_strip_revive": self.off_revive}
        switches.update(offline_start_steam=self.off_steam, offline_skip_confirm=self.off_quiet)
        for name, sw in switches.items():
            attr = play_service.repair_key(self.game) if name == "play_repair_after" else name
            want = bool(getattr(self.settings, attr))
            if sw.isChecked() != want:
                sw.blockSignals(True)
                sw.setChecked(want)
                sw.blockSignals(False)

    # ---- the update state both windows show (the Settings page reads it through LauncherHost)
    def update_state(self) -> dict:
        return {"line": self.launcher_line.text(), "tone": self._launcher_tone, "notices": list(self._notices.values())}

    def _notify_update(self):
        for call in list(self._update_listeners):
            try:
                call()
            except RuntimeError:  # the page's window is gone
                self._update_listeners.remove(call)

    def _drop_notice(self, notice_id, bar=None):
        if bar is None or self._notice_bars.get(notice_id) is bar:
            self._notice_bars.pop(notice_id, None)
            if self._notices.pop(notice_id, None) is not None:
                self._notify_update()

    def _dismiss_notice(self, notice_id):
        bar = self._notice_bars.get(notice_id)
        if bar is not None:
            try:
                bar.close()  # its closedSignal drops the notice
                return
            except RuntimeError:
                pass
        self._drop_notice(notice_id)

    def _run_notice_action(self, notice_id, key):
        """A notice button pressed on the new Settings page: the same path as pressing it on this window."""
        n = self._notices.get(notice_id)
        a = next((a for a in (n.actions if n else ()) if a.key == key), None)
        if a is not None:
            self._notice_action(a, self._notice_bars.get(notice_id))

    def _refresh_me3(self):
        setup, loc = self.setup, self.ctx.locations

        def work(_progress):
            try:
                return me3_facts(setup, loc)
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(work, on_result=self._on_me3)

    def _check_launcher_update(self, force=False):
        def work(_progress):
            try:
                check = feed.check_launcher_update(force=force)
            except Exception as e:
                check = feed.UpdateCheck("error", reason=str(e))
            try:
                advisory = feed.check_advisory(force=force)
            except Exception:
                advisory = None
            return {"check": check, "advisory": advisory, "force": force}

        self.jobs.start(work, on_result=self._on_update, name="launcher-update")

    def _on_channel(self, index):
        channel = "beta" if index == 1 else "stable"
        save_settings(launcher_channel=channel)
        self.settings.launcher_channel = channel
        self._offered = None
        self._check_launcher_update(force=True)

    def _on_update(self, payload):
        check, advisory, force = payload["check"], payload.get("advisory"), payload.get("force")
        text, tone = sp.launcher_status(check, self.settings.launcher_channel)
        self.launcher_line.setText(text)
        tone_label(self.launcher_line, tone)
        self._launcher_tone = tone
        self._notify_update()
        if advisory:
            self._show_advisory(advisory, check.offer)
        said = sp.check_toast(check) if force else None
        if said:
            self._toast(said[0], said[1], error=said[2] == "error", info=said[2] == "info")
        if check.offer and check.offer["version"] != self._offered:
            self._offer_update(check.offer)

    def _show_notice(self, n):
        """A presenter notice as a Widgets notice; its buttons run through _notice_action."""
        icons = {"download": FI.DOWNLOAD, "releases": FI.LINK, "details": FI.LINK, "again": FI.UPDATE}
        box = []
        buttons = []
        for a in n.actions:
            b = primary_btn(a.label) if a.primary else ghost_btn(a.label, icons.get(a.key))
            if a.tip:
                b.setToolTip(a.tip)
            b.clicked.connect(lambda _=False, a=a: self._notice_action(a, box[0]))
            buttons.append(b)
        old = self._notice_bars.pop(n.id, None)  # a new notice with the same id replaces the old one
        if old is not None:
            try:
                old.close()
            except RuntimeError:
                pass
        bar = notice(self, n.level, n.title, n.body, actions=buttons, closable=n.closable)
        box.append(bar)
        self._notice_bars[n.id] = bar
        self._notices[n.id] = n
        bar.closedSignal.connect(lambda: self._drop_notice(n.id, bar))
        self._notify_update()
        return bar

    def _notice_action(self, a, bar):
        if a.url:
            desktop.open_path(a.url)
        elif a.key == "update":
            self._start_update(self._offer_info, bar)
        elif a.key == "skip":
            feed.skip_update(self._offer_info["version"])
            bar.close()
        elif a.key == "restart":
            self._restart_updated(self._prepared)
        elif a.key == "later":
            bar.close()
        elif a.key == "again":
            self._check_launcher_update(force=True)

    def _show_advisory(self, advisory, offer):
        """The project asks everyone below a version to update (advisory.json on main). A notice only."""
        if getattr(self, "_advisory_shown", False):
            return
        self._advisory_shown = True
        self._show_notice(sp.advisory_notice(advisory, offer))

    def _offer_update(self, info):
        self._offered = info["version"]
        self._offer_info = info
        self._show_notice(sp.offer_notice(info, FROZEN))

    def _cannot_update(self) -> str:
        """Why the program cannot be replaced now, or ''."""
        return sp.cannot_update(self.game_running, self.game.name, self.busy, updates.busy_reason())

    def _start_update(self, info, bar=None):
        why = self._cannot_update()
        if why:
            self._toast("Cannot update now", why, error=True)
            return
        if bar is not None:
            bar.close()
        version = info["version"]
        self._update_bar = self._show_notice(sp.downloading_notice(version))

        def work(report):
            def progress(done, total):
                mb = done / 1_000_000
                report(f"{mb:.0f} of {total / 1_000_000:.0f} MB" if total else f"{mb:.0f} MB")

            try:
                prepared = updates.download_update(info, progress=progress)
                report("Keeping this version, to put it back if the new one does not start")
                prepared.rollback = updates.stage_rollback()
                return {"prepared": prepared, "version": version}
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(
            work, on_result=self._on_update_ready, on_progress=self._on_update_progress, name="launcher-download"
        )

    def _on_update_progress(self, text):
        if self._update_bar is not None:
            try:
                self._update_bar.contentLabel.setText(text)
            except RuntimeError:
                self._update_bar = None
        if "flow" in self._notices and self._offer_info:
            self._notices["flow"] = sp.downloading_notice(self._offer_info["version"], text)
            self._notify_update()

    def _on_update_ready(self, result):
        if self._update_bar is not None:
            try:
                self._update_bar.close()
            except RuntimeError:
                pass
            self._update_bar = None
        if result.get("error"):
            self._offered = None  # the next check offers it again
            self._show_notice(sp.failed_notice(result["error"]))
            return
        self._prepared = result["prepared"]
        self._show_notice(sp.ready_notice(result["version"], bool(self._prepared.delta)))

    def _restart_updated(self, prepared):
        why = self._cannot_update()
        if why:
            self._toast("Cannot restart now", why, error=True)
            return
        self.close()  # asks about unsaved edits; a cancel there leaves the window open
        if self.isVisible():
            return
        self._release_instance()  # the new version takes the window's name when it starts
        try:
            updates.apply_update(prepared)  # Velopack applies after this process exits, then restarts the launcher
        except Exception as e:
            self._take_instance()
            self.show()
            self._toast("Update not applied", f"{e} This version keeps running.", error=True)
            return
        QApplication.instance().quit()

    def _on_update_outcome(self, result):
        """How the last update went, shown once."""
        if not result:
            return
        updates.clear_outcome()
        n = sp.outcome_notice(result)
        if n is None:
            title, body = sp.outcome_ok_text(result)
            self._toast(title, body)
            return
        self._offered = None
        self._show_notice(n)

    def _on_migration(self, record):
        """The move from the old (Inno Setup) install, reported once per state."""
        n = sp.migration_notice(record)
        if n is not None:
            self._show_notice(n)

    def _point_steam_shortcuts(self):
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

        self.jobs.start(work, on_result=self._on_steam_retarget, name="steam-shortcuts")

    def _on_steam_retarget(self, result):
        if result.get("error"):
            self._toast("Steam shortcuts not changed", result["error"], error=True)
        elif result.get("changed"):
            self._toast("Steam shortcuts updated", f"Now starting this copy: {', '.join(result['changed'])}.")
        else:
            self._toast("Nothing to change", "No Steam shortcut with --play starts another copy.", info=True)

    def _on_me3(self, f):
        self._me3 = f
        if f.get("reload"):  # me3 reported its folders: its profile folder may be the one to use now
            self.ctx.reload_settings()
        if getattr(self, "_conf_result", None):  # the Load order card may need the version note
            self._fill_conflicts(self._conf_result)
        line = sp.me3_line(f)
        self.me3_line.setText(line.text)
        if line.error:
            return
        tone_label(self.me3_line, line.tone)
        self.me3_line.setToolTip(line.path)
        self.me3_dir_btn.setEnabled(bool(line.folder))
        self.me3_dir_btn.setToolTip(line.folder or "me3 was not found")
        self.me3_logs_btn.setEnabled(bool(line.logs))
        self.me3_prof_btn.setEnabled(bool(line.profiles))
        self.me3_logs_btn.setToolTip(line.logs or "me3 info did not report a logs folder")
        self.me3_prof_btn.setToolTip(line.profiles)
        self._update_plan()

    def _remember_play(self, key, checked):
        if key == "play_repair_after":
            key = play_service.repair_key(self.game)  # one switch on screen, a setting per game
        save_settings(**{key: bool(checked)})
        setattr(self.settings, key, bool(checked))
        if key == "warn_dead_shells":
            self._on_shells(dead_shells_count(loc=self.ctx.locations))
        if key == "overhaul_install":
            self._sync_overhaul_button()

    def _sync_overhaul_switch(self):
        """The overhaul switch shows for a game with an overhaul the launcher can install, saying which."""
        row = self.play_rows["overhaul_install"]
        try:
            names = mod_service.installable_overhauls(self.game.key)
            text = mod_service.overhaul_switch_text(self.game.key)
        except Exception:
            names, text = [], ""
        row.setVisible(bool(names))
        if row.d is not None and text:
            row.d.setText(text)
        self._sync_overhaul_button()

    def _on_theme(self, dark):
        save_settings(theme="dark" if dark else "light")
        self.settings.theme = "dark" if dark else "light"
        setTheme(Theme.DARK if dark else Theme.LIGHT)
        setThemeColor(ACCENT if dark else ACCENT_LIGHT)
        self._restyle()

    def _on_logo(self, index):
        mode = ("auto", "dark", "light")[index] if 0 <= index < 3 else "auto"
        save_settings(logo=mode)
        self.settings.logo = mode
        self._apply_logo()
