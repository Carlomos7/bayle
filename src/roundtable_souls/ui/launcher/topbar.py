"""The top bar's words and rules, without Qt (technical specification §8.10, Shell): the Launch pill (its three modes
and four states, each with its reason and the link that fixes it), the status text (the one place launcher state
shows), and the contents of the game and profile drop-downs. The shell's adapter turns these into properties; nothing
here knows a window exists, so the rules are checked without one.

The inputs are one frozen `Facts` snapshot; every output is a pure function of it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.config.settings import LauncherSettings, game_setting
from roundtable_souls.game import catalog as games
from roundtable_souls.ui.text import tr

PROFILE, OFFLINE, VANILLA = "profile", "offline", "vanilla"
MODES = (PROFILE, OFFLINE, VANILLA)
MODE_WORDS = {PROFILE: "Profile", OFFLINE: "Offline", VANILLA: "Vanilla"}  # shown through tr()

ENABLED, BUSY, RUNNING, BLOCKED = "enabled", "busy", "running", "blocked"

# What a link does; the shell maps each to a page or a flow.
NEW_PROFILE = "new_profile"
LOCATIONS = "settings:locations"
MODS = "mods"
MOD_CONFIGS = "mod_configs"
ME3_UPDATE = "settings:me3"
OPEN_STEAM = "open_steam"
CLEAR_DEAD = "clear_dead"
STOP_REBUILD = "stop_rebuild"
ACTIVITY = "activity"


@dataclass(frozen=True)
class Link:
    text: str
    action: str


@dataclass(frozen=True)
class Facts:
    """Everything the top bar depends on, read once by the host."""

    game: games.Game
    installed: bool = True  # the game's folder or exe is known
    profile_count: int = 0
    problems: tuple[str, ...] = ()  # the current setup's, from Setup.problems()
    busy: bool = False
    job_label: str = ""
    job_kind: str = ""  # "" | "launch" | "update" | "other"
    game_running: bool = False
    steam_bad: bool = False  # Steam runs but is not signed in (for long enough to say so)
    dead_shells: int = 0
    warn_dead_shells: bool = True
    coop_unsaved: bool = False  # Seamless settings edited and not saved: they apply on launch
    me3_update: str = ""  # the newer me3 version, or "" (said once a session)
    failed_job: str = ""  # a job that failed and was not looked at yet
    mode: str = PROFILE


@dataclass(frozen=True)
class Pill:
    mode: str
    mode_text: str  # "Profile"
    state: str  # ENABLED | BUSY | RUNNING | BLOCKED
    text: str  # the left zone: "Launch", "Launching...", "Updating...", "Running"
    reason: str = ""  # why it is blocked, or the tooltip for the other states
    link: Link | None = None
    can_launch: bool = False


@dataclass(frozen=True)
class Status:
    text: str
    tone: str = "muted"  # "muted" | "accent" | "danger"
    link: Link | None = None
    busy: bool = False  # a spinner beside the text
    to_activity: bool = True  # a click on the text opens the job in Activity


# ------------------------------------------------------------------------------------------------ mode memory
def mode_of(settings: LauncherSettings, game: games.Game) -> str:
    """The Launch mode remembered for the game; Profile when none (or an unknown word)."""
    value = game_setting(settings, game.key, "launch_mode")
    return value if value in MODES else PROFILE


def mode_menu(current: str) -> list[dict]:
    """The pill's mode menu: one entry per mode, the current one checked."""
    return [
        {"mode": m, "text": tr("Launch {mode}").format(mode=tr(MODE_WORDS[m])), "checked": m == current} for m in MODES
    ]


# ------------------------------------------------------------------------------------------------ blocked
def _short(problem: str) -> str:
    """The reason in plain words, without a long path (so the line is not this PC's folder tree)."""
    low = problem.lower()
    name = Path(problem.split(": ", 1)[1]).name if ": " in problem else ""
    if low.startswith("game exe"):
        return (
            tr("The game program is missing: {name}").format(name=name) if name else tr("The game program is missing")
        )
    if low.startswith("me3 missing"):
        return tr("me3 is missing: {name}").format(name=name) if name else tr("me3 is missing")
    if low.startswith("me3 is not installed"):
        return tr("me3 is not installed on this PC")
    if low.startswith("profile missing"):
        return tr("The profile file is missing")
    if ": " not in problem:
        return problem
    kind, rest = problem.split(": ", 1)
    return f"{kind}: {Path(rest).name}" if ("\\" in rest or "/" in rest) else problem


def _problem_link(problem: str) -> Link:
    low = problem.lower()
    if low.startswith(("me3 ", "game exe")) or "me3 is not installed" in low:
        return Link(tr("Settings > Locations"), LOCATIONS)
    return Link(tr("Mods"), MODS)


def blocked(facts: Facts, mode: str) -> tuple[str, Link | None] | None:
    """Why `mode` cannot launch now, with the link to the fix; None when it can (the job and the running game are
    states of their own, not blocks)."""
    g = facts.game
    if not g.ready:
        return tr("Not supported yet"), None
    if not facts.installed:
        return tr("{game} is not installed").format(game=g.name), Link(tr("Settings > Locations"), LOCATIONS)
    if mode == VANILLA:
        return None
    if facts.profile_count == 0:
        return tr("No profile"), Link(tr("Create a profile"), NEW_PROFILE)
    if facts.problems:
        return tr("Blocked: {why}").format(why=_short(facts.problems[0])), _problem_link(facts.problems[0])
    return None


def pill(facts: Facts) -> Pill:
    """The Launch pill for the current mode: enabled (gold), busy (spinner), running (disabled) or blocked (grey,
    the reason is in the status text)."""
    mode = facts.mode if facts.mode in MODES else PROFILE
    words = tr(MODE_WORDS[mode])
    if facts.game_running:
        return Pill(mode, words, RUNNING, tr("Running"), tr("{game} is running").format(game=facts.game.name))
    if facts.busy:
        text = {"launch": tr("Launching..."), "update": tr("Updating...")}.get(facts.job_kind, tr("Working..."))
        return Pill(mode, words, BUSY, text, facts.job_label)
    why = blocked(facts, mode)
    if why is not None:
        return Pill(mode, words, BLOCKED, tr("Launch"), why[0], why[1])
    return Pill(mode, words, ENABLED, tr("Launch"), tr("Launch {mode} (Ctrl+L)").format(mode=words), None, True)


# ------------------------------------------------------------------------------------------------ status text
def status(facts: Facts) -> Status:
    """The one line of launcher state, in order of importance. A running job and the running game come first; a
    failed job stays red until it is looked at; blocks and warnings follow; nothing to say is "Ready"."""
    g = facts.game
    if not g.ready:
        return Status(tr("Not supported yet"))
    if facts.busy:
        link = Link(tr("Stop after the rebuild"), STOP_REBUILD) if facts.job_kind == "update" else None
        return Status(facts.job_label or tr("Working..."), "accent", link, busy=True)
    if facts.game_running:
        return Status(tr("{game} running  ·  leave this window open").format(game=g.name))
    if facts.failed_job:
        return Status(tr("{job} failed").format(job=facts.failed_job.rstrip(". ")), "danger")
    if facts.steam_bad:
        return Status(tr("Steam is not signed in"), "danger", Link(tr("Open Steam"), OPEN_STEAM), to_activity=False)
    if facts.dead_shells > 0 and facts.warn_dead_shells:
        return Status(tr("Dead game process"), "danger", Link(tr("Clear"), CLEAR_DEAD), to_activity=False)
    why = blocked(facts, facts.mode if facts.mode in MODES else PROFILE)
    if why is not None:
        return Status(why[0], "danger", why[1], to_activity=False)
    if facts.coop_unsaved:
        return Status(
            tr("Unsaved co-op settings apply on launch"),
            "accent",
            Link(tr("Mod Configs"), MOD_CONFIGS),
            to_activity=False,
        )
    if facts.me3_update:
        return Status(
            tr("me3 {version} is available").format(version=facts.me3_update),
            "muted",
            Link(tr("Settings > Locations"), ME3_UPDATE),
            to_activity=False,
        )
    return Status(tr("Ready"))


# ------------------------------------------------------------------------------------------------ drop-downs
@dataclass(frozen=True)
class GameEntry:
    key: str
    name: str
    short: str
    tint: str
    status: str  # "installed" | "not installed" | "coming soon"
    checked: bool


def game_menu(current: games.Game, installed: dict[str, bool]) -> list[GameEntry]:
    """The game drop-down: the four games, the current one checked, each with its status. `installed` maps a game's
    key to whether Steam knows its folder."""
    out = []
    for g in games.GAMES:
        state = tr("coming soon") if not g.ready else tr("installed") if installed.get(g.key) else tr("not installed")
        out.append(GameEntry(g.key, g.name, g.short, g.tint, state, g is current))
    return out


@dataclass(frozen=True)
class ProfileEntry:
    index: int
    label: str
    checked: bool
    managed: bool  # a managed install (installation.json): shown with the "Managed install" tag


@dataclass(frozen=True)
class ProfileMenu:
    entries: tuple[ProfileEntry, ...]
    current: str  # the button's text
    new_text: str  # "New profile..." (always last)
    enabled: bool  # off while a job runs
    managed_tag: str


def profile_labels(setups) -> list[str]:
    """One label per setup, as the profile list names them (a file name; the folder too when two share a name)."""
    labels = [s.label for s in setups]
    return [
        f"{label}  ·  {Path(s.source).parent.name}" if labels.count(label) > 1 else label
        for s, label in zip(setups, labels)
    ]


def _bare(setup, label: str) -> str:
    """A managed install's label without the file-kind suffix its tag now says."""
    return label.replace("  ·  installation.json", "", 1) if setup.kind == "manifest" else label


def profile_menu(setups, index: int, busy: bool) -> ProfileMenu:
    """The profile drop-down: every profile of the game, the current one checked, "New profile..." last, nothing else.
    Managed installs carry the tag; the whole menu is off while a job runs."""
    labels = profile_labels(setups)
    entries = tuple(
        ProfileEntry(i, _bare(s, labels[i]), i == index, s.kind == "manifest") for i, s in enumerate(setups)
    )
    current = entries[index].label if 0 <= index < len(entries) else tr("No profile")
    return ProfileMenu(entries, current, tr("New profile..."), not busy, tr("Managed install"))
