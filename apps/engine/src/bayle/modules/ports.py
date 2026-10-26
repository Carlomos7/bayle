"""The ports more than one feature needs: the launcher's data folder, its settings file and the install's facts; me3,
Steam and the desktop (other programs); and the database's record index. Ports only one feature needs live with it
(games/ports.py: finding the game; mods/ports.py: the tool backends).

The runtime binds them (bayle.runtime.bootstrap): the machine and program ports once for the process (bind_ports;
each function reads its slot when called, so a test that swaps a function of the bound module is seen, and an unbound
call raises), the record index per engine (its _SLOTS; unbound, storage is off and the files alone work: record and
forget do nothing and keep_doubt is False)."""

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


# ----------------------------------------------------------------------------- other programs and the desktop
class Me3Info(Protocol):
    def version_tuple(self, v: str | None) -> tuple: ...

    def me3_version(self, me3: Path | str | None) -> str | None: ...

    def me3_info(self, me3: Path | str | None) -> dict: ...

    def latest_release(self) -> dict | None: ...

    def update_available(self, installed: str | None, latest: str | None) -> bool: ...


class Me3Paths(Protocol):
    def profile_games(self, profile: Path) -> tuple[str, ...]: ...


class Me3Session(Protocol):
    def me3_log_path(self) -> Path: ...

    def clear_dead_shells(self, exe_name: Any, when: str) -> Any: ...

    def ensure_steam(self, timeout: Any) -> Any: ...

    def ensure_steam_running(self, timeout: Any = ...) -> Any: ...

    def launch(
        self, game: Any, profile: Any, me3: Any, exe_name: Any, exe: Any = ..., extra_args: Any = ...
    ) -> Any: ...

    def wait_for_game(self, exe_name: Any, appear_timeout: Any, quiet: bool = ...) -> bool: ...


class Steam(Protocol):
    def steam_running(self) -> bool: ...

    def steam_logged_in(self) -> Any: ...

    def steam_exe(self) -> Any: ...


class Desktop(Protocol):
    def open_path(self, target: Any) -> None: ...


# bound by bayle.runtime.bootstrap.bind_ports only; the concrete modules are the bound objects, so a test that patches
# one of their functions is seen at the next call
_ME3_INFO: Me3Info | None = None
_ME3_PATHS: Me3Paths | None = None
_ME3_SESSION: Me3Session | None = None
_STEAM: Steam | None = None
_DESKTOP: Desktop | None = None


def version_tuple(v: str | None) -> tuple:
    return _bound(_ME3_INFO).version_tuple(v)


def me3_version(me3: Path | str | None) -> str | None:
    return _bound(_ME3_INFO).me3_version(me3)


def me3_info(me3: Path | str | None) -> dict:
    return _bound(_ME3_INFO).me3_info(me3)


def latest_release() -> dict | None:
    return _bound(_ME3_INFO).latest_release()


def update_available(installed: str | None, latest: str | None) -> bool:
    return _bound(_ME3_INFO).update_available(installed, latest)


def profile_games(profile: Path) -> tuple[str, ...]:
    return _bound(_ME3_PATHS).profile_games(profile)


def me3_log_path() -> Path:
    return _bound(_ME3_SESSION).me3_log_path()


def clear_dead_shells(exe_name: Any, when: str) -> Any:
    return _bound(_ME3_SESSION).clear_dead_shells(exe_name, when)


def ensure_steam(timeout: Any) -> Any:
    return _bound(_ME3_SESSION).ensure_steam(timeout)


def ensure_steam_running(timeout: Any = 60) -> Any:
    return _bound(_ME3_SESSION).ensure_steam_running(timeout)


def launch(game: Any, profile: Any, me3: Any, exe_name: Any, exe: Any = None, extra_args: Any = ()) -> Any:
    return _bound(_ME3_SESSION).launch(game, profile, me3, exe_name, exe=exe, extra_args=extra_args)


def wait_for_game(exe_name: Any, appear_timeout: Any, quiet: bool = False) -> bool:
    return _bound(_ME3_SESSION).wait_for_game(exe_name, appear_timeout, quiet=quiet)


def steam_running() -> bool:
    return _bound(_STEAM).steam_running()


def steam_logged_in() -> Any:
    return _bound(_STEAM).steam_logged_in()


def steam_exe() -> Any:
    return _bound(_STEAM).steam_exe()


def open_path(target: Any) -> None:
    _bound(_DESKTOP).open_path(target)


# ----------------------------------------------------------------------------- the database's record index
BACKUP_NOTE, LIBRARY, HISTORY = "backup-note", "library", "history"


class RecordIndex(Protocol):
    def record(self, kind: str, path: Path) -> None: ...

    def forget(self, kind: str, path: Path) -> None: ...

    def keep_doubt(self, path: Path) -> bool: ...


_RECORD_INDEX: RecordIndex | None = None  # bound by bayle.runtime.bootstrap (_SLOTS: unbound when storage is off)


def record(kind: str, path: Path) -> None:
    if _RECORD_INDEX is not None:
        _RECORD_INDEX.record(kind, path)


def forget(kind: str, path: Path) -> None:
    if _RECORD_INDEX is not None:
        _RECORD_INDEX.forget(kind, path)


def keep_doubt(path: Path) -> bool:
    return _RECORD_INDEX is not None and _RECORD_INDEX.keep_doubt(path)
