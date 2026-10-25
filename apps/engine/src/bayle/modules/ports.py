"""What every feature needs from this machine: the launcher's data folder, its settings file and the install's facts.
The runtime binds them (bayle.runtime.bootstrap.bind_ports); each function below reads its slot when called, so a
test that swaps a function of the bound module is seen. Unbound, a call raises."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from bayle.modules.settings.models import LauncherSettings


class DataFolder(Protocol):
    def data_root(self) -> Path: ...

    def temp(self, name: str) -> Path: ...

    def deleted_profiles(self, profile_dir: Path) -> Path: ...

    def adopt_legacy_profile_folders(self, profile_dir: Path) -> None: ...


class SettingsFile(Protocol):
    def settings_path(self) -> Path: ...

    def load_settings(self) -> LauncherSettings: ...

    def change_settings(self, change: Callable[[LauncherSettings], dict[str, Any]]) -> LauncherSettings: ...

    def save_settings(self, **changes: Any) -> None: ...

    def save_game_settings(self, game: str, **changes: Any) -> None: ...


class AppPaths(Protocol):
    FROZEN: bool

    def data_dir(self) -> Path: ...

    def exe_dir(self) -> Path: ...

    def launch_target(self) -> Path: ...


# bound by bayle.runtime.bootstrap.bind_ports only
_DATA_FOLDER: DataFolder | None = None
_SETTINGS_FILE: SettingsFile | None = None
_APP_PATHS: AppPaths | None = None


def _bound[T](port: T | None) -> T:
    if port is None:
        raise RuntimeError("bind_ports() was not called")
    return port


# ----------------------------------------------------------------------------- the data folder
def data_root() -> Path:
    return _bound(_DATA_FOLDER).data_root()


def temp(name: str) -> Path:
    return _bound(_DATA_FOLDER).temp(name)


def deleted_profiles(profile_dir: Path) -> Path:
    return _bound(_DATA_FOLDER).deleted_profiles(profile_dir)


def adopt_legacy_profile_folders(profile_dir: Path) -> None:
    _bound(_DATA_FOLDER).adopt_legacy_profile_folders(profile_dir)


# ----------------------------------------------------------------------------- the settings file
def settings_path() -> Path:
    return _bound(_SETTINGS_FILE).settings_path()


def load_settings() -> LauncherSettings:
    return _bound(_SETTINGS_FILE).load_settings()


def change_settings(change: Callable[[LauncherSettings], dict[str, Any]]) -> LauncherSettings:
    return _bound(_SETTINGS_FILE).change_settings(change)


def save_settings(**changes: Any) -> None:
    _bound(_SETTINGS_FILE).save_settings(**changes)


def save_game_settings(game: str, **changes: Any) -> None:
    _bound(_SETTINGS_FILE).save_game_settings(game, **changes)


# ----------------------------------------------------------------------------- the install's facts
def frozen() -> bool:
    return _bound(_APP_PATHS).FROZEN


def data_dir() -> Path:
    return _bound(_APP_PATHS).data_dir()


def exe_dir() -> Path:
    return _bound(_APP_PATHS).exe_dir()


def launch_target() -> Path:
    return _bound(_APP_PATHS).launch_target()
