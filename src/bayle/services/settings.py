"""The launcher settings and install facts the window reads and writes (the file itself: config.settings), and the
rules for changing one: the schema of every setting, what values it takes, where it is stored (per game or global)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from bayle.config.settings import (
    FROZEN,
    data_dir,
    exe_dir,
    game_setting,
    launch_target,
    load_settings,
    save_game_settings,
    save_settings,
)
from bayle.errors import OperationError
from bayle.game.locate import PATH_SETTINGS, saves_dir_problem
from bayle.platform import data_folder
from bayle.platform.text import tr
from bayle.services import mods as mod_service
from bayle.services import play as play_service

__all__ = [
    "FROZEN",
    "data_dir",
    "exe_dir",
    "game_setting",
    "launch_target",
    "load_settings",
    "save_game_settings",
    "save_settings",
    "PATH_SETTINGS",
]


def read() -> dict:
    """The settings as plain JSON-able data."""
    return load_settings().model_dump(mode="json")


def update(**changes) -> dict:
    """Save the changed fields and return the settings after."""
    save_settings(**changes)
    return read()


# ----------------------------------------------------------------------------- the schema: what each setting is
KEEP_RANGE = (5, 200)  # backups kept per save file: a number outside it is brought inside
CHOICES: dict[str, tuple[str, ...]] = {
    "theme": ("dark", "tarnished", "light", "system"),
    "effects": ("full", "reduced", "off"),
    "grain": ("off", "subtle", "film"),
    "logo": ("auto", "crimson", "ice", "gold"),
    "log_level": ("normal", "verbose"),
    "launcher_channel": ("stable", "beta"),
}
LOCATIONS: dict[str, tuple[bool, bool]] = {  # location key -> (is a folder, saved per game)
    "me3_path": (False, False),
    "game_exe": (False, True),
    "me3_profile_dir": (True, False),
    "saves_dir": (True, True),
}
APPEARANCE = ("theme", "effects", "grain")


class SettingSpec(BaseModel):
    """One setting a client may change: its kind decides which values are allowed, its scope where it is stored."""

    key: str
    kind: Literal["switch", "choice", "number", "location"]
    scope: Literal["global", "game"] = "global"  # game: the value belongs to the current game
    choices: list[str] = []  # kind choice: the allowed values
    low: int | None = None  # kind number: the range a value is brought into
    high: int | None = None
    is_dir: bool = False  # kind location: a folder, else a file
    follow: Literal["none", "settings", "appearance", "updates"] = "settings"  # what the window does after a save


def schema(switch_keys: tuple[str, ...] = ()) -> dict[str, SettingSpec]:
    """Every setting by key. switch_keys: the on/off settings (the page's switch table owns that list)."""
    out = {k: SettingSpec(key=k, kind="switch") for k in switch_keys}
    for k, allowed in CHOICES.items():
        follow = "appearance" if k in APPEARANCE else "updates" if k == "launcher_channel" else "settings"
        out[k] = SettingSpec(key=k, kind="choice", choices=list(allowed), follow=follow)
    out["backups_keep"] = SettingSpec(
        key="backups_keep", kind="number", low=KEEP_RANGE[0], high=KEEP_RANGE[1], follow="none"
    )
    for k, (is_dir, per_game) in LOCATIONS.items():
        out[k] = SettingSpec(key=k, kind="location", is_dir=is_dir, scope="game" if per_game else "global")
    return out


def location_problem(spec: SettingSpec, value: str, game) -> str:
    """Why value cannot be this location, or "" when it can."""
    if spec.key == "saves_dir":
        return saves_dir_problem(value, game)
    if spec.is_dir:
        return "" if Path(value).is_dir() else tr("That folder does not exist.")
    return "" if Path(value).is_file() else tr("That file does not exist.")


def normalise(spec: SettingSpec, value: Any, game) -> bool | int | str:
    """The value as it is saved. Raises OperationError: invalid_value (wrong type), invalid_choice, path_problem."""
    bad = OperationError("invalid_value", tr("That value does not fit {key}.").format(key=spec.key), {"key": spec.key})
    if spec.kind == "switch":
        if not isinstance(value, bool):
            raise bad
        return value
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad
        assert spec.low is not None and spec.high is not None
        return max(spec.low, min(spec.high, value))
    if not isinstance(value, str):
        raise bad
    if spec.kind == "choice":
        if value not in spec.choices:
            raise OperationError(
                "invalid_choice",
                tr("{value} is not one of the choices.").format(value=value),
                {"key": spec.key, "choices": spec.choices},
            )
        return value
    value = value.strip()
    if value and (problem := location_problem(spec, value, game)):
        raise OperationError("path_problem", problem, {"key": spec.key, "value": value})
    return value


def store(spec: SettingSpec, value: bool | int | str, game) -> str:
    """Save one setting where it belongs (this game's or global); returns the key it was saved under."""
    key = play_service.repair_key(game) if spec.key == "play_repair_after" else spec.key
    if spec.scope == "game":
        save_game_settings(game.key, **{key: value})
    else:
        save_settings(**{key: value})
    return key


# ----------------------------------------------------------------------------- what the page reads
@dataclass(frozen=True)
class Facts:
    """What the Settings page reads from the disk and the system, as plain data."""

    settings: Any  # config.settings.LauncherSettings
    detected: dict[str, str | None]  # location key -> the path found when it is left blank
    overhaul: str  # the overhaul switch's sentence ("" when the game has none)
    steam_target: str
    steam_options: str
    backups_folder: str
    me3_profiles: str | None  # me3's own profiles folder, as me3 reports it


def backups_folder() -> Path:
    try:
        return data_folder.data_root() / "saves"
    except RuntimeError:  # the data folder is set when the program starts
        return data_dir() / "saves"


def _detected(key: str, loc) -> str | None:
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
        return str(found) if found else None
    except Exception:
        return None


def facts(game, loc) -> Facts:
    """Read only. loc: the game's Locations, or None when no game is selected."""
    try:
        overhaul = mod_service.overhaul_switch_text(game.key)
    except Exception:
        overhaul = ""
    try:
        target, options = play_service.play_command(game)
    except Exception:
        target, options = "", ""
    return Facts(
        load_settings(),
        {k: (_detected(k, loc) if loc is not None else None) for k in LOCATIONS},
        overhaul,
        target,
        options,
        str(backups_folder()),
        _detected("me3_profile_dir", loc) if loc is not None else None,
    )


def folder(kind: str, loc, make: bool = False) -> Path | None:
    """The folder an "Open ... folder" button means, or None when it is not on this PC. make: create the backups
    folder first. Raises OperationError unknown_folder."""
    found: Any = None
    try:
        if kind == "me3" and loc is not None:
            exe = loc.me3_exe()
            found = Path(exe).parent if exe else None
        elif kind == "game" and loc is not None:
            found = loc.game_dir()
        elif kind == "profiles" and loc is not None:
            found = loc.me3_profiles_dir()
        elif kind == "saves" and loc is not None:
            found = next((r for r in loc.save_roots() if r.is_dir()), None)
        elif kind == "backups":
            found = backups_folder()
            if make:
                found.mkdir(parents=True, exist_ok=True)
        elif kind == "settings":
            found = data_dir()
        elif kind not in ("me3", "game", "profiles", "saves"):
            raise OperationError(
                "unknown_folder", tr("There is no folder called {kind}.").format(kind=kind), {"kind": kind}
            )
    except OperationError:
        raise
    except Exception:
        return None
    return Path(found) if found is not None and Path(found).exists() else None
