"""The menu bar's model, without Qt (technical specification §8.10, Shell): File, Profile, Game, Saves, View and Help,
with their shortcuts and the rule that enables each entry. It is data: an entry names the page it works on and the
command to give that page (`adapter.command(name, args)`), or "shell" for what the shell itself does. No page knows
the menu; an entry whose page does not offer its command is disabled, not hidden, so the menu is also the list of
what is still to come.

`resolve(facts)` gives the menus for the current state: every entry with its enabled flag and check mark."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from bayle.modules.games import catalog as games

from bayle_qt.launcher import topbar
from bayle_qt.text import tr

SHELL = "shell"  # the target of an entry the shell itself runs


@dataclass(frozen=True)
class Entry:
    id: str
    label: str
    target: str = SHELL  # a page name (ui/pages/registry) or SHELL
    command: str = ""
    args: tuple = ()
    shortcut: str = ""
    icon: str = ""
    rule: str = "always"
    separator: bool = False
    submenu: tuple[Entry, ...] = ()
    checked_when: str = ""  # what makes it checked: "game:<key>", "theme:<mode>"


SEP = Entry("", "", separator=True)

# The page names are the keys of ui/pages/registry.QML_PAGES.
MODS, MOD_CONFIGS, SAVES, ACTIVITY, SETTINGS, TRANSFER = (
    "mods",
    "modConfigs",
    "saves",
    "activity",
    "settings",
    "profileTransfer",
)

FILE = (
    Entry("file.new", "New profile...", SHELL, "newProfile", shortcut="Ctrl+N", icon="Add", rule="game_ready"),
    Entry("file.add", "Add existing profile...", SHELL, "addProfile", icon="FolderAdd", rule="game_ready"),
    Entry("file.import", "Import profile...", TRANSFER, "import", icon="Download", rule="game_ready"),
    Entry("file.export", "Export profile...", TRANSFER, "export", icon="Share", rule="profile"),
    SEP,
    Entry("file.profile_folder", "Open profile folder", SHELL, "openProfileFolder", icon="Folder", rule="profile"),
    Entry("file.game_folder", "Open game folder", SHELL, "openGameFolder", icon="Folder", rule="game_folder"),
    SEP,
    Entry("file.exit", "Exit", SHELL, "quit", shortcut="Ctrl+Q"),
)
PROFILE = (
    Entry("profile.rename", "Rename...", MODS, "rename", icon="Edit", rule="profile_idle"),
    Entry("profile.duplicate", "Duplicate...", MODS, "duplicate", icon="Copy", rule="profile_idle"),
    Entry("profile.move_in", "Move into Bayle's folder...", MODS, "moveIn", icon="Folder", rule="profile_outside"),
    Entry("profile.delete", "Delete...", MODS, "deleteProfile", icon="Delete", rule="profile_idle"),
    SEP,
    Entry("profile.settings", "Profile settings...", MODS, "profileSettings", icon="Setting", rule="profile"),
    Entry("profile.edit", "Edit .me3...", MODS, "editText", icon="Code", rule="profile"),
    Entry("profile.fix_order", "Fix load order", MODS, "fixOrder", rule="fix_order"),
    Entry("profile.versions", "Versions...", MODS, "versions", icon="History", rule="profile"),
)
SAVES_MENU = (
    Entry("saves.backup", "Back up now", SAVES, "backUpNow", icon="Save", rule="idle"),
    Entry("saves.transfer", "Transfer character...", SAVES, "transferCharacter", icon="People", rule="idle"),
    Entry("saves.import", "Import save file...", SAVES, "importSave", icon="Download", rule="idle"),
    SEP,
    Entry("saves.folder", "Open saves folder", SAVES, "openSavesFolder", icon="Folder", rule="game_ready"),
    Entry("saves.library", "Open library folder", SAVES, "openLibrary", icon="Folder", rule="game_ready"),
    Entry("saves.backups", "Open backups folder", SAVES, "openBackups", icon="Folder", rule="game_ready"),
)
THEMES = (("dark", "Dark"), ("tarnished", "Tarnished"), ("light", "Light"), ("system", "System"))
VIEW = (
    Entry("view.mods", "Mods", MODS, "show", shortcut="Ctrl+1", icon="BookShelf", rule="game_ready"),
    Entry(
        "view.configs", "Mod Configs", MOD_CONFIGS, "show", shortcut="Ctrl+2", icon="DeveloperTools", rule="game_ready"
    ),
    Entry("view.saves", "Saves", SAVES, "show", shortcut="Ctrl+3", icon="Save", rule="game_ready"),
    Entry("view.activity", "Activity", ACTIVITY, "show", shortcut="Ctrl+4", icon="History"),
    Entry("view.settings", "Settings", SETTINGS, "show", shortcut="Ctrl+5", icon="Setting"),
    SEP,
    Entry(
        "view.theme",
        "Theme",
        icon="Brush",
        submenu=tuple(
            Entry(f"view.theme.{mode}", label, SHELL, "theme", (mode,), checked_when=f"theme:{mode}")
            for mode, label in THEMES
        ),
    ),
    Entry("view.rail", "Collapse navigation", SHELL, "toggleRail", icon="Menu"),
)
HELP = (
    Entry("help.how", "How to use", SHELL, "howToUse", shortcut="F1", icon="Help"),
    Entry("help.updates", "Check for updates", SETTINGS, "checkForUpdates", icon="Update"),
    Entry("help.logs_save", "Save logs for support...", SETTINGS, "saveLogs", icon="Save"),
    Entry("help.logs_folder", "Open logs folder", SHELL, "openLogsFolder", icon="Folder"),
    SEP,
    Entry("help.about", "About", SHELL, "about", icon="Info"),
)


def game_entries() -> tuple[Entry, ...]:
    """The Game menu: the four games (the current one checked), then one Launch entry per mode."""
    pick = tuple(
        Entry(f"game.{g.key}", g.name, SHELL, "game", (g.key,), checked_when=f"game:{g.key}") for g in games.GAMES
    )
    launch = tuple(
        Entry(
            f"game.launch.{m}",
            tr("Launch {mode}").format(mode=tr(topbar.MODE_WORDS[m])),
            SHELL,
            "launch",
            (m,),
            icon={"profile": "Play", "offline": "Cloud", "vanilla": "Game"}[m],
            rule=f"launch:{m}",
        )
        for m in topbar.MODES
    )
    return (*pick, SEP, *launch)


MENUS: tuple[tuple[str, str], ...] = (
    ("file", "File"),
    ("profile", "Profile"),
    ("game", "Game"),
    ("saves", "Saves"),
    ("view", "View"),
    ("help", "Help"),
)


def entries_of(menu: str) -> tuple[Entry, ...]:
    return {"file": FILE, "profile": PROFILE, "game": game_entries(), "saves": SAVES_MENU, "view": VIEW, "help": HELP}[
        menu
    ]


@dataclass(frozen=True)
class MenuFacts:
    game: games.Game
    has_profile: bool = False
    busy: bool = False
    game_running: bool = False
    game_folder: bool = False  # the game's folder is known
    load_order_broken: bool = False  # the stays-last check fails
    profile_outside: bool = False  # the profile is not in Bayle's folder (it can be moved there)
    can_launch: Mapping[str, bool] | None = None  # mode -> the pill would launch in it
    theme: str = "dark"
    rail_collapsed: bool = False
    commands: Mapping[str, frozenset[str]] | None = None  # page -> the commands its adapter offers


def _rule(rule: str, f: MenuFacts) -> bool:
    if rule == "always":
        return True
    if rule == "game_ready":
        return f.game.ready
    if rule == "profile":
        return f.game.ready and f.has_profile
    if rule == "idle":
        return f.game.ready and not f.busy and not f.game_running
    if rule == "profile_idle":
        return f.game.ready and f.has_profile and not f.busy and not f.game_running
    if rule == "profile_outside":
        return f.game.ready and f.has_profile and f.profile_outside and not f.busy and not f.game_running
    if rule == "game_folder":
        return f.game.ready and f.game_folder
    if rule == "fix_order":
        return f.has_profile and f.load_order_broken and not f.busy
    if rule.startswith("launch:"):
        return bool((f.can_launch or {}).get(rule.split(":", 1)[1]))
    raise ValueError(f"unknown menu rule {rule!r}")


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    enabled: bool = True
    checked: bool = False
    shortcut: str = ""
    icon: str = ""
    separator: bool = False
    items: tuple[Item, ...] = ()


def _checked(when: str, f: MenuFacts) -> bool:
    kind, _, value = when.partition(":")
    return (kind == "game" and f.game.key == value) or (kind == "theme" and f.theme == value)


def _offered(e: Entry, f: MenuFacts) -> bool:
    """The page the entry works on offers its command (the shell's own entries and plain page switches always do)."""
    if e.target == SHELL or e.command == "show":
        return True
    return e.command in (f.commands or {}).get(e.target, frozenset())


def _item(e: Entry, f: MenuFacts) -> Item:
    if e.separator:
        return Item("", "", separator=True)
    label = tr(e.label)
    if e.id == "view.rail":
        label = tr("Expand navigation") if f.rail_collapsed else tr("Collapse navigation")
    subs = tuple(_item(s, f) for s in e.submenu)
    enabled = _rule(e.rule, f) and _offered(e, f)
    return Item(
        e.id, label, enabled, _checked(e.checked_when, f) if e.checked_when else False, e.shortcut, e.icon, items=subs
    )


def resolve(f: MenuFacts) -> list[tuple[str, str, tuple[Item, ...]]]:
    """(id, title, items) of each menu, for the current state."""
    return [(key, tr(title), tuple(_item(e, f) for e in entries_of(key))) for key, title in MENUS]


def find(entry_id: str) -> Entry | None:
    """The entry with this id (what a click on an item asks the shell to run)."""
    for key, _ in MENUS:
        for e in entries_of(key):
            for found in (e, *e.submenu):
                if found.id == entry_id:
                    return found
    return None
