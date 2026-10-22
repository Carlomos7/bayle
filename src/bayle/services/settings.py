"""The launcher settings and install facts the window reads and writes (the file itself: config.settings)."""

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
from bayle.game.locate import PATH_SETTINGS

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
