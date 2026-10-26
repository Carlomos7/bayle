"""The launcher settings file: read it, and change it under a lock. The settings themselves are modules.settings.models;
the folder the file lives in is adapters.system.app_paths.data_dir."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bayle.adapters.filesystem import filelock
from bayle.adapters.system import app_paths
from bayle.modules.settings.models import LauncherSettings


def settings_path() -> Path:
    return app_paths.data_dir() / "launcher_settings.json"


def load_settings() -> LauncherSettings:
    """The settings, read now (validated, defaults filled). A broken file yields the defaults."""
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except OSError, ValueError:
        raw = {}
    return LauncherSettings.from_raw(raw)


_WRITE_LOCK = threading.RLock()  # threads of this process; the lock file covers other processes
_tmp_count = 0


def _write(model: LauncherSettings) -> None:
    global _tmp_count
    path = settings_path()
    _tmp_count += 1
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{_tmp_count}.tmp")  # never shared with another writer
    try:
        tmp.write_text(json.dumps(model.to_file(), indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def change_settings(change: Callable[[LauncherSettings], dict[str, Any]]) -> LauncherSettings:
    """Read, change and write the file as one step: change(current) returns the keys to set. No other thread or
    launcher process writes in between, so a value computed from the current one (a counter) is never lost.
    Returns the settings as written."""
    with _WRITE_LOCK, filelock.locked(settings_path()):
        current = load_settings()
        new = LauncherSettings.model_validate({**current.to_file(), **change(current)})
        _write(new)
        return new


def save_settings(**changes: Any) -> None:
    """Merge changes into the file, atomically, without losing another thread's or process's change."""
    change_settings(lambda current: changes)


def save_game_settings(game: str, **changes: Any) -> None:
    """Merge per-game values for one game into the file."""
    if game == "eldenring":
        save_settings(**changes)
        return
    games = dict(load_settings().games)
    games[game] = {**(games.get(game) or {}), **changes}
    save_settings(games=games)
