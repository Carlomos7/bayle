"""The Settings page's presenter (technical specification §8.10, Settings): every word of the page and the rows it
shows, made from what the engine's Settings interface (modules.settings.service.SettingsService) returns. Plain Python,
no Qt: the adapter (adapter.py) hands these to QML. The engine returns data and error codes; the switch titles, choice
labels, location words, "Location updated" sentences, the three confirms and the refusals are worded here. The update
notices and the launcher status line stay in views.settings, which the shell uses too. Every string goes through
tr()."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bayle.errors import OperationError
from bayle.modules.launch import play as play_service
from bayle.modules.launch.play import TITLE, VERSION
from bayle.modules.settings.service import (
    KEEP_RANGE,
    LOCATIONS,
    Changed,
    NameCheck,
    RelocateFacts,
    SettingsFacts,
    game_setting,
)
from bayle.work.prompts import Confirm, Refusal
from pydantic import BaseModel

from bayle_qt.launcher.presenter import install_kind
from bayle_qt.shell import updates as updates_flow
from bayle_qt.text import tr
from bayle_qt.updater import apply as updates
from bayle_qt.updater.service import RELEASES_URL

ME3_RELEASES_URL = "https://github.com/garyttierney/me3/releases"
LICENCE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md")
GITHUB_BLOB = RELEASES_URL.removesuffix("/releases") + "/blob"  # + /v<version>/<file>

# the label of each choice, by setting
CHOICE_LABELS: dict[str, tuple[tuple[str, str], ...]] = {
    "theme": (("dark", "Dark"), ("tarnished", "Tarnished"), ("light", "Light"), ("system", "System")),
    "effects": (("full", "Full"), ("reduced", "Reduced"), ("off", "Off")),
    "grain": (("off", "Off"), ("subtle", "Subtle"), ("film", "Film")),
    "logo": (("auto", "Follows theme"), ("crimson", "Crimson"), ("ice", "Ice"), ("gold", "Tarnished")),
    "log_level": (("normal", "Normal"), ("verbose", "Verbose")),
    "launcher_channel": (("stable", "Stable"), ("beta", "Beta")),
}
# location key -> title, help, file filter (files only)
LOCATION_WORDS: dict[str, tuple[str, str, str]] = {
    "me3_path": (
        "me3",
        "Leave empty to find me3 automatically. Set it only if you keep me3 somewhere unusual, such as a portable copy.",
        "me3 (me3.exe)",
    ),
    "game_exe": (
        "Game executable",
        "Leave empty to use the game from your Steam library. Set it only to launch a different copy of the game. Saved per game.",
        "Game (*.exe)",
    ),
    "me3_profile_dir": (
        "me3 profiles folder",
        "Where me3 keeps its own profiles. Leave empty to use the folder me3 uses.",
        "",
    ),
    "saves_dir": (
        "Saves folder",
        "Leave empty to find your saves automatically. Set it only if the game keeps them somewhere else. The Saves page, "
        "backups and repairs all use this folder. Saved per game.",
        "",
    ),
}
LOG_LEVEL_SAID = "The log level applies from the next start."
# draft field -> label, in the confirm of a rename
LAYOUT_LABELS = {
    "pattern": "Game folder",
    "packages": "Game-file mods",
    "natives": "DLL mods",
    "shared": "Shared mods",
}


def said(changed: Changed) -> str:
    """What saving a setting says ("" for most): a location, or the log level."""
    if changed.kind == "location":
        value = str(changed.value)
        return tr("Location updated") + (" " + Path(value).name if value else " " + tr("Detecting again."))
    if changed.key == "log_level":
        return tr(LOG_LEVEL_SAID)
    return ""


# ----------------------------------------------------------------------------- the switches
@dataclass(frozen=True)
class SwitchSpec:
    key: str  # the settings key (play_repair_after is the game's own, see play.repair_key)
    title: str
    blurb: str
    help: str
    group: str  # launch | updates | me3 | offline


def repair_blurb(game_key: str) -> str:
    """The Repair saves line, per game (game model, 2026-10-20)."""
    if game_key == "nightreign":
        return tr("Re-signs the save's encrypted sections after quitting. Leave it on.")
    return tr("Only save editors need this. The game never reads this part of the save back.")


def switches(overhaul_text: str = "", game_key: str = "eldenring") -> tuple[SwitchSpec, ...]:
    """Every switch of the page, in the order it is shown. overhaul_text is the overhaul switch's sentence for the
    game (empty when the game has no overhaul the launcher can install; the page then hides that row)."""
    return (
        SwitchSpec(
            "play_update_merge",
            tr("Rebuild merged mods automatically before launch"),
            tr(
                "When mods, their load order or the game changed, Launching rebuilds the merged ones first (combined "
                "parameters, and a mod's own rebuild tool), then starts the game."
            ),
            tr(
                "Off: Launch asks first (rebuild, or launch once with the previous result), and a Steam shortcut "
                "does not start the game. A failed rebuild keeps the previous result and asks before starting. "
                "Only the newest 3 rebuild-tool backups are kept; older ones go to the Recycle Bin."
            ),
            "launch",
        ),
        SwitchSpec(
            "overhaul_install",
            tr("Install overhauls with the launcher (preview)"),
            overhaul_text,
            tr(
                "Every change is shown before it happens, and each install or removal can be undone from Activity. "
                "The launcher keeps a copy of the download and its notes in its own folder in me3's profiles "
                "folder; the overhaul's own folder stays beside your profile. An overhaul another installer set up "
                "isn't changed by the launcher. Off: the button is hidden; nothing installed with it changes."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_boot_boost",
            tr("Boot boost"),
            tr(
                "me3 keeps a decrypted copy of the game's archive indexes so the game starts faster. If DLC areas "
                "or items are sometimes missing, try turning this off."
            ),
            tr("Off passes --no-boot-boost to me3."),
            "launch",
        ),
        SwitchSpec(
            "play_show_logos",
            tr("Show intro logos"),
            tr("Shows the publisher logos that me3 skips by default."),
            tr("On passes --show-logos to me3."),
            "launch",
        ),
        SwitchSpec(
            "play_diagnostics",
            tr("me3 diagnostics"),
            tr("Extra detail for troubleshooting, with a slower start and a bigger log."),
            tr("Passes --diagnostics. me3's output is kept with that launch in the logs folder."),
            "launch",
        ),
        SwitchSpec(
            "play_backup_before",
            tr("Back up saves before launch"),
            tr("Backs up every save before each session. Listed under Backups on Saves."),
            tr(
                "Off by default: the game keeps its own backup and each repair makes a copy anyway. If a backup "
                "fails, Launch asks: Retry, Launch without backup or Cancel. A Steam shortcut stops unless it has "
                "--allow-without-backup."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_clear_before",
            tr("Clear leftover processes before launch"),
            tr("Closes hidden copies of the game still running, so Steam agrees to start it."),
            "",
            "launch",
        ),
        SwitchSpec(
            "play_repair_after",
            tr("Repair saves after quitting"),
            repair_blurb(game_key),
            tr(
                "Each game keeps its own setting. Elden Ring copies regulation.bin into the save so editors can "
                "read it. Nightreign never does: its Game\regulation.bin is a different encoding."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_clear_after",
            tr("Clear leftover processes after quitting"),
            tr("Closes hidden copies of the game so Discord and Steam stop showing it as running."),
            tr("Needs admin once."),
            "launch",
        ),
        SwitchSpec(
            "warn_dead_shells",
            tr("Warn about leftover processes"),
            tr("Shows a bar at the top of the window when one is found."),
            "",
            "launch",
        ),
        SwitchSpec(
            "check_launcher_updates",
            tr("Check for updates on start"),
            tr("Checks GitHub at most once an hour. You choose when to install."),
            "",
            "updates",
        ),
        SwitchSpec(
            "check_me3_updates",
            tr("Check for me3 updates"),
            tr("Once a day, from me3's GitHub releases. A notice only; nothing is installed."),
            tr("Bayle never replaces me3 itself: a mod that bundles its own copy keeps it."),
            "me3",
        ),
        SwitchSpec(
            "offline_strip_overhaul",
            tr("Skip the overhaul too"),
            tr("Leave an overhaul the launcher has a config for off for this launch."),
            tr("Turns its packages and natives off in a temporary copy. Your real profile is not changed."),
            "offline",
        ),
        SwitchSpec(
            "offline_start_steam",
            tr("Start Steam if needed"),
            tr("Opens Steam before launch if it is not running."),
            "",
            "offline",
        ),
        SwitchSpec(
            "offline_skip_confirm",
            tr("Skip the confirmation"),
            tr("Launch Offline starts straight away, without the prompt."),
            "",
            "offline",
        ),
    )


OFFLINE_TITLE = tr("Offline play")
OFFLINE_BLURB = tr(
    "Launch Offline starts this profile without Seamless Co-op and with online play off. The game then uses its "
    "standard save (.sl2), not Seamless's (.co2)."
)
OFFLINE_HELP = tr(
    "Steam must be running; pick Start in Offline Mode if it asks. Co-op needs Steam online. The launcher follows a "
    "me3 savefile setting or ersc_settings.ini if they change the save names."
)


@dataclass(frozen=True)
class Me3Line:
    text: str
    tone: str  # muted | accent
    path: str
    folder: str  # "" when me3's folder is unknown
    logs: str
    profiles: str
    error: bool


def me3_line(f: dict) -> Me3Line:
    """The me3 line and the folders it can open, from modules.mods.service.me3_facts."""
    if f.get("error"):
        return Me3Line(f"me3: {f['error']}", "muted", "", "", "", "", True)
    v = f.get("version")
    latest = (f.get("latest") or {}).get("version")
    text = f"me3 {v}" if v else tr("me3 version unknown")
    if f.get("update") and latest:
        text += "  ·  " + tr("{version} is available").format(version=latest)
    elif v and latest:
        text += "  ·  " + tr("up to date")
    info = f.get("info") or {}
    where = info.get("install_prefix") or (str(Path(f["path"]).parent) if f.get("path") else "")
    return Me3Line(
        text,
        "accent" if f.get("update") else "muted",
        f.get("path") or "",
        where if where and Path(where).is_dir() else "",
        info.get("logs_dir") or "",
        info.get("profile_dir") or "",
        False,
    )


# ----------------------------------------------------------------------------- what the page shows
class SwitchRow(BaseModel):
    key: str
    title: str
    blurb: str
    help: str
    group: str  # launch | updates | me3 | offline
    checked: bool
    shown: bool


class LocationRow(BaseModel):
    key: str
    title: str
    help: str
    value: str
    placeholder: str  # what blank detects now
    is_dir: bool
    filter: str = ""


class SettingsState(BaseModel):
    game: str
    theme: str
    effects: str
    grain: str
    logo: str
    log_level: str
    launcher_channel: str
    labels: dict[str, str]  # setting -> the label of its current choice
    backups_keep: int
    backups_location: str
    profiles_root: str  # what the page shows (the saved folder, else me3's)
    saved_profiles_root: str  # the saved one as it is ("" when none): what a relocation is checked against
    steam_target: str
    steam_options: str
    data_folder: str
    launcher_line: str
    layout: dict[str, str]  # pattern | packages | natives | shared -> the saved name
    locations: list[LocationRow]
    switches: list[SwitchRow]


def build(page: SettingsFacts) -> SettingsState:
    facts, game = page.facts, page.game
    s = facts.settings
    rows = []
    for key, (title, help_text, filt) in LOCATION_WORDS.items():
        is_dir, per_game = LOCATIONS[key]
        value = game_setting(s, game.key, key) if per_game else getattr(s, key)
        found = facts.detected.get(key)
        rows.append(
            LocationRow(
                key=key,
                title=tr(title),
                help=tr(help_text),
                value=str(value or ""),
                placeholder=tr("detected: {path}").format(path=found) if found else tr("detected"),
                is_dir=is_dir,
                filter=filt,
            )
        )
    switch_rows = [
        SwitchRow(
            key=spec.key,
            title=spec.title,
            blurb=spec.blurb,
            help=spec.help,
            group=spec.group,
            checked=bool(
                getattr(s, play_service.repair_key(game) if spec.key == "play_repair_after" else spec.key, False)
            ),
            shown=bool(spec.blurb) or spec.key != "overhaul_install",
        )
        for spec in switches(facts.overhaul, game.key)
    ]
    keep = s.backups_keep
    return SettingsState(
        game=game.key,
        theme=s.theme,
        effects=s.effects,
        grain=s.grain,
        logo=s.logo,
        log_level=s.log_level,
        launcher_channel=s.launcher_channel,
        labels={
            which: next((tr(b) for k, b in rows_ if k == getattr(s, which)), "")
            for which, rows_ in CHOICE_LABELS.items()
        },
        backups_keep=keep if KEEP_RANGE[0] <= keep <= KEEP_RANGE[1] else 20,
        backups_location=facts.backups_folder,
        profiles_root=s.profiles_root or facts.me3_profiles or tr("me3's folder"),
        saved_profiles_root=str(s.profiles_root or ""),
        steam_target=facts.steam_target,
        steam_options=facts.steam_options,
        data_folder=updates.data_location_text(),
        launcher_line=f"{TITLE} {VERSION}  ·  {install_kind(updates_flow.install_kind())}",
        layout=dict(page.layout),
        locations=rows,
        switches=switch_rows,
    )


def name_errors(check: NameCheck) -> dict[str, str]:
    """The sentence under each unusable folder name."""
    return {f: tr(p) for f, p in check.errors.items()}


def licence_url(file: str) -> str:
    """A licence file on GitHub at the tag of the running version (D8)."""
    return f"{GITHUB_BLOB}/v{VERSION}/{file}"


# ----------------------------------------------------------------------------- the confirms and the refusals


_SYNC = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "box sync")
LONG_PATH = 200  # a profile's files add roughly 60 more; Windows stops at 260


def path_warnings(path: str, size: int, free: int | None) -> list[str]:
    """Cautions for a new profiles folder: a cloud-synced folder, too little free space, a path that is too long."""
    out = []
    low = path.lower().replace("\\", "/")
    if any(s in low for s in _SYNC):
        out.append(
            tr("This folder looks synced by OneDrive, Dropbox or Google Drive. Syncing can lock or damage mods.")
        )
    if free is not None and free < size * 1.1:
        out.append(
            tr("There is not enough free space: {need} needed, {have} free.").format(
                need=size_text(size), have=size_text(free)
            )
        )
    if len(path) > LONG_PATH:
        out.append(tr("This path is very long. Some mod files may not fit."))
    return out


def size_text(size: int) -> str:
    n = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def relocate_confirm(facts: RelocateFacts) -> Confirm:
    """The Profiles folder > Change confirm."""
    count = tr("1 profile, {size}.") if facts.profiles == 1 else tr("{n} profiles, {size}.")
    return Confirm(
        tr("Move your profiles and mods to {path}?").format(path=facts.folder),
        (
            count.format(n=facts.profiles, size=size_text(facts.size)),
            *path_warnings(facts.folder, facts.size, facts.free),
        ),
        tr("Move"),
        safety=tr("Undo in Activity."),
    )


def rename_confirm(changes: dict[str, tuple[str, str]]) -> Confirm:
    """changes: draft field -> (old, new). The confirm of Folder names > Apply."""
    return Confirm(
        tr("Rename folders?"),
        tuple(
            tr("{label}: {old} becomes {new}.").format(label=tr(LAYOUT_LABELS[k]), old=o, new=n)
            for k, (o, n) in changes.items()
        ),
        tr("Rename"),
        safety=tr("Undo in Activity."),
    )


def move_all_confirm(names: list[str]) -> Confirm:
    shown = ", ".join(names[:8]) + (tr(" and {n} more").format(n=len(names) - 8) if len(names) > 8 else "")
    count = tr("1 profile moves: {names}.") if len(names) == 1 else tr("{n} profiles move: {names}.")
    return Confirm(
        tr("Move all profiles into Bayle's folder?"),
        (count.format(n=len(names), names=shown),),
        tr("Move all"),
        safety=tr("Undo in Activity."),
    )


def refusal(e: OperationError) -> Refusal:
    """Why the engine would not do it, in words (title "" when the body alone says it)."""
    match e.code:
        case "busy":
            return Refusal(tr("Wait for the current job."), tr("Another job is running."))
        case "game_running":
            return Refusal(tr("The game is running."), tr("Close it first."))
        case "nothing_to_move":
            return Refusal(tr("Nothing to move"), tr("No profiles are outside Bayle's folder."))
        case "nothing_to_change":
            return Refusal("", tr("The names are the ones in use already."))
        case "invalid_params":
            return Refusal("", tr("Pick a folder."))
        case "stale":
            return Refusal("", tr("Things changed since you were asked. Ask again."))
        case "unknown_setting":
            return Refusal("", tr("There is no setting called {key}.").format(key=e.details.get("key", "")))
        case "unknown_folder":
            return Refusal("", tr("There is no folder called {kind}.").format(kind=e.details.get("kind", "")))
        case _:  # invalid_value, invalid_choice, path_problem, invalid_names: the engine's sentence has the detail
            return Refusal("", tr(e.message))


def refusal_line(e: OperationError, body_only: bool = False) -> str:
    r = refusal(e)
    return r.body if body_only or not r.title else f"{r.title}. {r.body}"
