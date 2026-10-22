"""The Settings page's snapshot (technical specification §8.10, Settings): what the page shows of the saved settings,
as plain data a client can render. The rules for changing a setting are in services.settings; the other words of the
page are in views.settings. No Qt. Every string goes through tr()."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from bayle.platform.text import tr
from bayle.services import play as play_service
from bayle.services import settings as store
from bayle.services.settings import Facts, SettingSpec
from bayle.views import settings as sp

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


def location_said(value: str) -> str:
    """What saving a location says."""
    return tr("Location updated") + (" " + Path(value).name if value else " " + tr("Detecting again."))


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


class ChoiceRow(BaseModel):
    key: str
    label: str


class SettingsState(BaseModel):
    game: str
    theme: str
    effects: str
    grain: str
    logo: str
    log_level: str
    launcher_channel: str
    labels: dict[str, str]  # setting -> the label of its current choice
    choices: dict[str, list[ChoiceRow]]
    backups_keep: int
    keep_from: int
    keep_to: int
    backups_location: str
    profiles_root: str
    steam_target: str
    steam_options: str
    data_folder: str
    launcher_line: str
    layout: dict[str, str]  # pattern | packages | natives | shared -> the saved name
    locations: list[LocationRow]
    switches: list[SwitchRow]
    specs: list[SettingSpec]


def switch_keys() -> tuple[str, ...]:
    return tuple(s.key for s in sp.switches())


def build(facts: Facts, game) -> SettingsState:
    s = facts.settings
    rows = []
    for key, (title, help_text, filt) in LOCATION_WORDS.items():
        is_dir, per_game = store.LOCATIONS[key]
        value = store.game_setting(s, game.key, key) if per_game else getattr(s, key)
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
    switches = [
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
        for spec in sp.switches(facts.overhaul, game.key)
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
        choices={which: [ChoiceRow(key=k, label=tr(b)) for k, b in rows_] for which, rows_ in CHOICE_LABELS.items()},
        backups_keep=keep if store.KEEP_RANGE[0] <= keep <= store.KEEP_RANGE[1] else 20,
        keep_from=store.KEEP_RANGE[0],
        keep_to=store.KEEP_RANGE[1],
        backups_location=facts.backups_folder,
        profiles_root=s.profiles_root or facts.me3_profiles or tr("me3's folder"),
        steam_target=facts.steam_target,
        steam_options=facts.steam_options,
        data_folder=sp.data_location(),
        launcher_line=f"{sp.TITLE} {sp.VERSION}  ·  {sp.install_kind()}",
        layout=layout_saved(s),
        locations=rows,
        switches=switches,
        specs=list(store.schema(switch_keys()).values()),
    )


def layout_saved(s) -> dict[str, str]:
    """The four folder names as saved, by draft field."""
    return {
        "pattern": str(s.game_folder_pattern),
        "packages": str(s.packages_folder),
        "natives": str(s.natives_folder),
        "shared": str(s.shared_folder),
    }


# draft field -> label, in the confirm of a rename
LAYOUT_LABELS = {
    "pattern": "Game folder",
    "packages": "Game-file mods",
    "natives": "DLL mods",
    "shared": "Shared mods",
}

KEEP_RANGE = store.KEEP_RANGE
