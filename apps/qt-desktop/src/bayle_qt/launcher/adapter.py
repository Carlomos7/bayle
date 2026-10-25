"""The shell's adapter: the thin QObject Main.qml binds to (technical specification §8.10, Shell). It holds no
decisions: the words and rules come from the Qt-free presenters (topbar.py, menu.py), the work from the host. It
exposes the Launch pill, the status text, the drop-downs, the rail, the menus and the theme as properties; it
creates each page (and its Notifier) the first time it is visited and keeps it; it turns a menu entry, a shortcut
or a click into a call on the host or a command to a page's adapter.

An adapter may offer two optional members the shell reads, nothing else: `unsaved_words()` (what has edits that
are not written, for the prompt on leaving) and `command(name, args)` (what the menu can ask of the page)."""

from __future__ import annotations

from typing import Any

from bayle import __version__
from bayle.platform import desktop
from bayle.services import play as core
from bayle.services.settings import save_settings
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from bayle_qt.launcher import menu, topbar
from bayle_qt.launcher.host import ShellHost
from bayle_qt.launcher.menumodel import MenuModel
from bayle_qt.notifications import Notifier
from bayle_qt.pages import registry
from bayle_qt.qml_env import QML_DIR
from bayle_qt.resources import ASSETS_DIR
from bayle_qt.text import tr

# The rail, in order (Ctrl+1..5): registry name, label, icon.
RAIL = (
    ("mods", "Mods", "BookShelf"),
    ("modConfigs", "Mod Configs", "DeveloperTools"),
    ("saves", "Saves", "Save"),
    ("activity", "Activity", "History"),
    ("settings", "Settings", "Setting"),
)
ALWAYS = ("activity", "settings")  # the pages a game without support still has
SUB_PAGES = {"profileTransfer": "mods"}  # shown over the page area, under the rail item of the page it belongs to


class ShellAdapter(QObject):
    changed = Signal()  # the pill, status text, drop-downs, rail badge, menus
    pageChanged = Signal()
    appearanceChanged = Signal()
    notifiersChanged = Signal()
    visitedChanged = Signal()
    unsavedPrompt = Signal(int, list, str)  # token, what is unsaved, what is about to happen
    closePrompt = Signal()  # a job is running: confirm before closing
    quitRequested = Signal()
    forwardRequested = Signal()  # a second start: bring the window forward
    profilePickerRequested = Signal()  # a link asks for the top bar's profile drop-down
    newProfileRequested = Signal(str, bool)  # the suggested name, Seamless can come along

    def __init__(self, host: ShellHost, parent: QObject | None = None):
        super().__init__(parent)
        self.host = host
        self._adapters: dict[str, Any] = {}
        self._notifiers: dict[str, Notifier] = {}
        self._visited: list[str] = []
        self._last_page: dict[str, str] = {}  # per game: the page it was on when you left it
        self._prompts: dict[int, tuple[list[str], Any]] = {}
        self._next = 0
        self.closing_approved = False
        self._after_close_confirm: Any = None
        self._current = "mods" if host.state.game.ready else "placeholder"
        self._cache: dict[str, Any] = {}
        self._menu_models = {key: MenuModel(self) for key, _title in menu.MENUS}
        host.page_opener = self.open_page
        host.guard_prompt = self._ask_unsaved
        host.close_guard = self._guard_close
        host.changed.connect(self._host_changed)
        host.checksChanged.connect(self._checks_changed)
        host.appearanceChanged.connect(self._appearance_changed)
        host.forwardRequested.connect(self.forwardRequested)
        host.quitRequested.connect(self._quit)
        host.pageRequested.connect(self.goTo)
        host.newProfileAsked.connect(lambda: self._shell_command("newProfile", []))
        host.gameChanged.connect(self._game_changed)
        self._recompute()
        self.adapterFor(self._current)  # the first page is made before the window asks for it
        self._visited.append(self._current)

    # ---------------------------------------------------------------- recomputing what the bar shows
    def _host_changed(self) -> None:
        self._recompute()
        self.changed.emit()
        self.host.schedule_checks()  # the disk reads happen off the UI thread; checksChanged brings the result

    def _checks_changed(self) -> None:
        self._recompute()
        self.changed.emit()

    def _recompute(self) -> None:
        h = self.host
        facts = h.facts()
        pill = topbar.pill(facts)
        status = topbar.status(facts)
        self._cache = {
            "facts": facts,
            "pill": {
                "mode": pill.mode,
                "modeText": pill.mode_text,
                "state": pill.state,
                "text": pill.text,
                "reason": pill.reason,
                "canLaunch": pill.can_launch,
                "warn": pill.warn,
                "linkText": pill.link.text if pill.link else "",
                "linkAction": pill.link.action if pill.link else "",
            },
            "status": {
                "text": status.text,
                "idle": status.text == tr("Ready"),  # nothing to say: the compact strip stays away
                "tone": status.tone,
                "busy": status.busy,
                "toActivity": status.to_activity,
                "linkText": status.link.text if status.link else "",
                "linkAction": status.link.action if status.link else "",
            },
            "modes": topbar.mode_menu(pill.mode),
            "games": [
                {
                    "key": g.key,
                    "name": g.name,
                    "short": g.short,
                    "tint": g.tint,
                    "status": g.status,
                    "checked": g.checked,
                }
                for g in topbar.game_menu(h.state.game, h.installed_games())
            ],
            "profileMenu": self._profile_menu(),
            "menu_items": self._menus(facts),
        }
        for key, _title, items in self._cache["menu_items"]:
            self._menu_models[key].update(items)

    def _profile_menu(self) -> dict:
        m = topbar.profile_menu(self.host.state.launch_profiles, self.host.state.index, self.host.busy)
        return {
            "entries": [
                {"index": e.index, "label": e.label, "checked": e.checked, "managed": e.managed} for e in m.entries
            ],
            "current": m.current,
            "newText": m.new_text,
            "enabled": m.enabled,
            "managedTag": m.managed_tag,
        }

    def _menus(self, facts: topbar.Facts) -> list[tuple[str, str, tuple[menu.Item, ...]]]:
        h = self.host
        st = h.state
        can = {m: topbar.blocked(facts, m) is None and not facts.busy and not facts.game_running for m in topbar.MODES}
        commands = {p.name: frozenset(p.commands) for p in registry.QML_PAGES}
        mf = menu.MenuFacts(
            game=st.game,
            has_profile=st.launch_profile is not None,
            busy=h.busy,
            game_running=st.game_running,
            game_folder=bool(st.locations.game_dir()),
            load_order_broken=self._load_order_broken(),
            profile_outside=self._profile_outside(),
            can_launch=can,
            theme=st.settings.theme,
            rail_collapsed=bool(st.settings.rail_collapsed),
            commands=commands,
        )

        return menu.resolve(mf)

    def _profile_outside(self) -> bool:
        page: Any = self._adapters.get("mods")
        outside = getattr(page, "profile_outside", None)
        return bool(outside()) if outside is not None else False

    def _load_order_broken(self) -> bool:
        page: Any = self._adapters.get("mods")
        broken = getattr(page, "load_order_broken", None)
        return bool(broken()) if broken is not None else False

    # ---------------------------------------------------------------- properties for the bar, rail and menus
    pill = Property(dict, lambda self: self._cache["pill"], notify=changed)
    status = Property(dict, lambda self: self._cache["status"], notify=changed)
    modeMenu = Property(list, lambda self: self._cache["modes"], notify=changed)
    games = Property(list, lambda self: self._cache["games"], notify=changed)
    profileMenu = Property(dict, lambda self: self._cache["profileMenu"], notify=changed)

    @Property(list, constant=True)
    def menuBar(self) -> list:
        """The menus in order: {id, title, model}; the models update in place."""
        return [{"id": key, "title": tr(title), "model": self._menu_models[key]} for key, title in menu.MENUS]

    def _menu_enabled(self) -> dict:
        out: dict[str, bool] = {}

        def walk(items: tuple[menu.Item, ...]) -> None:
            for i in items:
                if not i.separator:
                    out[i.id] = i.enabled
                walk(i.items)

        for _key, _title, items in self._cache["menu_items"]:
            walk(items)
        return out

    menuEnabled = Property(dict, _menu_enabled, notify=changed)

    @Property(list, constant=True)
    def shortcuts(self) -> list:
        """Every menu entry with a shortcut: {id, sequence}; Main.qml keeps one Shortcut for each."""
        out = []
        for key, _title in menu.MENUS:
            for e in menu.entries_of(key):
                for found in (e, *e.submenu):
                    if found.shortcut:
                        out.append({"id": found.id, "sequence": found.shortcut})
        return out

    unseen = Property(int, lambda self: self.host.unseen, notify=changed)
    unsupported = Property(bool, lambda self: not self.host.state.game.ready, notify=changed)
    gameName = Property(str, lambda self: self.host.state.game.name, notify=changed)
    gameShort = Property(str, lambda self: self.host.state.game.short, notify=changed)
    version = Property(str, lambda self: __version__, constant=True)

    def _rail_items(self) -> list:
        ready = self.host.state.game.ready
        return [
            {
                "name": name,
                "label": tr(label),
                "icon": icon,
                "shortcut": f"Ctrl+{i}",
                "badge": self.host.unseen if name == "activity" else 0,
            }
            for i, (name, label, icon) in enumerate(RAIL, start=1)
            if ready or name in ALWAYS
        ]

    rail = Property(list, _rail_items, notify=changed)

    # ---- the look
    themeMode = Property(str, lambda self: self.host.state.settings.theme, notify=appearanceChanged)
    effects = Property(str, lambda self: self.host.state.settings.effects, notify=appearanceChanged)
    grain = Property(str, lambda self: self.host.state.settings.grain, notify=appearanceChanged)
    logoMode = Property(str, lambda self: self.host.state.settings.logo, notify=appearanceChanged)
    logoCrimson = Property(QUrl, lambda self: QUrl.fromLocalFile(str(ASSETS_DIR / "logo-crimson.png")), constant=True)
    logoIce = Property(QUrl, lambda self: QUrl.fromLocalFile(str(ASSETS_DIR / "logo-ice.png")), constant=True)
    logoGold = Property(QUrl, lambda self: QUrl.fromLocalFile(str(ASSETS_DIR / "logo-gold.png")), constant=True)

    def _appearance_changed(self) -> None:
        self.appearanceChanged.emit()
        self._host_changed()

    def _rail_collapsed(self) -> bool:
        return bool(self.host.state.settings.rail_collapsed)

    railCollapsed = Property(bool, _rail_collapsed, notify=changed)

    @Slot()
    def toggleRail(self) -> None:
        save_settings(rail_collapsed=not self._rail_collapsed())
        self.host.settings_changed("rail_collapsed")

    # ---- first-run hints: the ones not dismissed yet (a flyout only for help, never for state)
    TIPS = ("launch", "rail")

    def _tips(self) -> list:
        seen = set(self.host.state.settings.tips_seen)
        return [t for t in self.TIPS if t not in seen] if self.host.state.game.ready else []

    tips = Property(list, _tips, notify=changed)

    @Slot(str)
    def dismissTip(self, name: str) -> None:
        save_settings(tips_seen=[*self.host.state.settings.tips_seen, name])
        self.host.settings_changed("tips_seen")

    # ---------------------------------------------------------------- pages
    @Slot(str, result=QUrl)
    def pageUrl(self, name: str) -> QUrl:
        return QUrl.fromLocalFile(str(QML_DIR / registry.page(name).qml))

    @Slot(str, result="QVariant")
    def adapterFor(self, name: str) -> Any:
        """The page's adapter, made (with its Notifier) the first time it is asked for."""
        if name not in self._adapters:
            entry = registry.page(name)
            notifier = Notifier(self)
            adapter = entry.make_adapter(self.host, notifier)
            if isinstance(adapter, QObject) and adapter.parent() is None:
                adapter.setParent(self)
            self._notifiers[name] = notifier
            self._adapters[name] = adapter
            self.host.register_page(name, adapter)
            self.notifiersChanged.emit()
            self._host_changed()
        return self._adapters[name]

    @Slot(str, result="QVariant")
    def notifierFor(self, name: str) -> Any:
        self.adapterFor(name)
        return self._notifiers[name]

    def _all_notifiers(self) -> list:
        return [self.host.notifier, *self._notifiers.values()]

    allNotifiers = Property(list, _all_notifiers, notify=notifiersChanged)

    def open_page(self, name: str) -> Any:
        """Show a page and give its adapter (the host's hand-offs: open Mod Configs on a mod, the Export view...)."""
        adapter = self.adapterFor(name)
        self._set_page(name)
        return adapter

    @Property(str, notify=pageChanged)
    def currentPage(self) -> str:
        return self._current

    @Property(str, notify=pageChanged)
    def railPage(self) -> str:
        """The page whose rail item is selected: a sub-page belongs to its parent."""
        return SUB_PAGES.get(self._current, self._current)

    @Property(list, notify=visitedChanged)
    def visited(self) -> list:
        return list(self._visited)

    @Property(list, constant=True)
    def pageNames(self) -> list:
        return [p.name for p in registry.QML_PAGES]

    @Slot(str)
    def goTo(self, name: str) -> None:
        """Go to a page, asking about unsaved edits on the page being left first."""
        ready = self.host.state.game.ready
        if not ready and SUB_PAGES.get(name, name) not in ALWAYS:
            name = "placeholder"  # a game without support yet: its placeholder, Activity and Settings only
        elif ready and name == "placeholder":
            name = self._last_page.get(self.host.state.game.key, "mods")
        if name == self._current:
            return
        leaving = self._unsaved_of(self._current)
        self.host.guard(leaving, tr("leaving this page"), lambda: self._set_page(name))

    @Slot(int)
    def goToIndex(self, i: int) -> None:
        """Ctrl+1..5: the rail's pages in order."""
        rail = self._rail_items()
        if 1 <= i <= len(rail):
            self.goTo(rail[i - 1]["name"])

    def _set_page(self, name: str) -> None:
        if name == self._current:
            return
        self._current = name
        st = self.host.state
        if st.game.ready and SUB_PAGES.get(name, name) not in ALWAYS:
            self._last_page[st.game.key] = SUB_PAGES.get(name, name)  # switching back returns here
        adapter = self.adapterFor(name)
        if name not in self._visited:
            self._visited.append(name)
            self.visitedChanged.emit()
        refreshed = self.host.page_shown(name)
        if name == "activity":
            if not refreshed:
                adapter.refresh()
            adapter.seen()
        self.pageChanged.emit()

    @Property(bool, notify=pageChanged)
    def canGoBack(self) -> bool:
        return self._current in SUB_PAGES

    @Slot()
    def rescan(self) -> None:
        """F5: the page on show reads again."""
        adapter = self._adapters.get(self._current)
        if adapter is not None:
            adapter.refresh()

    @Slot()
    def saveCurrent(self) -> None:
        """Ctrl+S: the page on show writes what it has unsaved."""
        adapter = self._adapters.get(self._current)
        command = getattr(adapter, "command", None)
        if command is not None and self._unsaved_of(self._current):
            command("saveUnsaved", [])

    def _game_changed(self) -> None:
        """Another game: land on the page it was last on (Mods the first time); Activity and Settings stay."""
        st = self.host.state
        if self._current in ALWAYS:
            self._host_changed()
            return
        target = self._last_page.get(st.game.key, "mods") if st.game.ready else "placeholder"
        self._current = ""  # a switch to the same page name still counts
        self._set_page(target)
        self._host_changed()

    @Slot()
    def back(self) -> None:
        """Esc: the page's own sub-page first (a character sheet, the repair view), then a sub-page of the shell."""
        adapter = self._adapters.get(self._current)
        command = getattr(adapter, "command", None)
        if command is not None and command("back", []):
            return
        if self._current in SUB_PAGES:
            self.goTo(SUB_PAGES[self._current])

    def _unsaved_of(self, name: str) -> list[str]:
        words = getattr(self._adapters.get(name), "unsaved_words", None)
        return list(words()) if words is not None else []

    # ---------------------------------------------------------------- the top bar
    @Slot()
    def launch(self) -> None:
        self.host.launch()

    @Slot(str)
    def setMode(self, mode: str) -> None:
        self.host.set_mode(mode)

    @Slot(str)
    def launchIn(self, mode: str) -> None:
        self.host.launch(mode)

    @Slot(str)
    def requestGame(self, key: str) -> None:
        self.host.request_game(key)

    @Slot(int)
    def cycleGame(self, step: int) -> None:
        self.host.cycle_game(step)

    @Slot(int)
    def pickProfile(self, index: int) -> None:
        self.host.guard(self.host.unsaved(), tr("switching profile"), lambda: self.host.pick_profile(index))

    @Slot()
    def statusClicked(self) -> None:
        """The status text: a failed job or a running one opens in Activity."""
        self.goTo("activity")

    @Slot(str)
    def followLink(self, action: str) -> None:
        """A link in the pill's reason or the status text."""
        h = self.host
        if action == topbar.NEW_PROFILE:
            self._shell_command("newProfile", [])
        elif action == topbar.PICK_PROFILE:
            self.profilePickerRequested.emit()
        elif action == topbar.LOCATIONS:
            self.runCommand("settings", "show", ["locations"])
        elif action == topbar.ME3_UPDATE:
            h.me3_clicked()
            self.runCommand("settings", "show", ["locations"])
        elif action == topbar.MODS:
            self.goTo("mods")
        elif action == topbar.MOD_CONFIGS:
            self.goTo("modConfigs")
        elif action == topbar.OPEN_STEAM:
            h.open_steam()
        elif action == topbar.CLEAR_DEAD:
            h.clear_dead_processes()
        elif action == topbar.STOP_REBUILD:
            h.flow.stop_after_rebuild()

    # ---------------------------------------------------------------- menus and commands
    @Slot(str)
    def menuAction(self, entry_id: str) -> None:
        entry = menu.find(entry_id)
        if entry is None:
            return
        if entry.target == menu.SHELL:
            self._shell_command(entry.command, list(entry.args))
        else:
            self.runCommand(entry.target, entry.command, list(entry.args))

    @Slot(str, str, list)
    def runCommand(self, page: str, name: str, args: list) -> None:
        """Go to a page and give its adapter a command (`show` is just the visit)."""
        self.goTo(page)
        if self._current != page and page != self._current:
            return  # the unsaved prompt is open, or the visit was refused
        adapter = self.adapterFor(page)
        if name == "show":
            return
        command = getattr(adapter, "command", None)
        if command is not None:
            command(name, args)

    def _shell_command(self, name: str, args: list) -> None:
        h = self.host
        st = h.state
        if name == "game":
            h.request_game(args[0])
        elif name == "launch":
            h.launch(args[0])
        elif name == "theme":
            save_settings(theme=args[0])
            h.set_appearance()
        elif name == "toggleRail":
            self.toggleRail()
        elif name == "newProfile":
            self.newProfileRequested.emit(tr("{game} mods").format(game=st.game.name), h.seamless_offer())
        elif name == "quit":
            self.requestClose()
        elif name == "addProfile":
            picked = h.pick_file(
                tr("Pick a me3 profile"), "me3 profile or installation.json (*.me3 *.json);;All files (*.*)"
            )
            if picked is not None:
                h.add_profile(picked)
        elif name in ("openProfileFolder", "openGameFolder"):
            places = core.places(st.launch_profile, st.locations)
            where = places.get("profile" if name == "openProfileFolder" else "game")
            if where:
                h.open_path(where)
            else:
                h.notifier.toast(tr("That folder is not known yet."), error=True)
        elif name == "openLogsFolder":
            h.open_logs_folder()
        elif name == "howToUse":
            desktop.open_path(_readme_url())
        elif name == "about":
            self.goTo("settings")

    # ---------------------------------------------------------------- the unsaved-changes prompt and closing
    def _ask_unsaved(self, words: list[str], action: str, proceed) -> None:
        self._next += 1
        self._prompts[self._next] = (words, proceed)
        self.unsavedPrompt.emit(self._next, words, action)

    @Slot(int, str)
    def unsavedAnswer(self, token: int, choice: str) -> None:
        """Save, Discard or Cancel on the unsaved-changes prompt."""
        words, proceed = self._prompts.pop(token, ([], None))
        if proceed is None or choice == "cancel":
            return
        ok = True
        for adapter in list(self._adapters.values()):
            if not getattr(adapter, "unsaved_words", lambda: [])():
                continue
            command = getattr(adapter, "command", None)
            if command is not None:
                ok = bool(command("saveUnsaved" if choice == "save" else "discardUnsaved", [])) and ok
        if ok and not self.host.unsaved():
            proceed()

    def _guard_close(self, proceed) -> None:
        """Ask what closing would lose (a running job, unsaved edits), then proceed."""
        closing = self.host.closing()

        def after_job() -> None:
            self.host.guard(closing["unsaved"], tr("closing"), proceed)

        if closing["job"]:
            self._after_close_confirm = after_job
            self.closePrompt.emit()
        else:
            after_job()

    @Slot(str, bool)
    def createProfile(self, name: str, include_seamless: bool) -> None:
        self.host.new_profile(name, include_seamless)

    @Slot()
    def requestClose(self) -> None:
        self._guard_close(self._approve_close)

    @Slot()
    def closeConfirmed(self) -> None:
        """ "Close anyway" on the running-job prompt."""
        go, self._after_close_confirm = self._after_close_confirm, None
        if go is not None:
            go()

    def _approve_close(self) -> None:
        self.closing_approved = True
        self.quitRequested.emit()

    closeApproved = Property(bool, lambda self: self.closing_approved, notify=quitRequested)

    def _quit(self) -> None:
        self.closing_approved = True
        self.quitRequested.emit()


def _readme_url() -> str:
    """The project's home page (How to use is its README)."""
    from bayle.config import identity

    return identity.get().releases_page.rsplit("/releases", 1)[0] + "#readme"
