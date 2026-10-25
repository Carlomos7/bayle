"""What the launch feature (and the mods that read me3) need from other programs and the desktop: me3 (its version,
profiles and the session that runs it), Steam, and the desktop's open handler. The runtime binds the concrete
adapters (bayle.runtime.bootstrap.bind_ports); called unbound, the functions raise."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


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


def _need[T](port: T | None) -> T:
    if port is None:
        raise RuntimeError("launch ports are unbound: bind_ports() was not called")
    return port


def version_tuple(v: str | None) -> tuple:
    return _need(_ME3_INFO).version_tuple(v)


def me3_version(me3: Path | str | None) -> str | None:
    return _need(_ME3_INFO).me3_version(me3)


def me3_info(me3: Path | str | None) -> dict:
    return _need(_ME3_INFO).me3_info(me3)


def latest_release() -> dict | None:
    return _need(_ME3_INFO).latest_release()


def update_available(installed: str | None, latest: str | None) -> bool:
    return _need(_ME3_INFO).update_available(installed, latest)


def profile_games(profile: Path) -> tuple[str, ...]:
    return _need(_ME3_PATHS).profile_games(profile)


def me3_log_path() -> Path:
    return _need(_ME3_SESSION).me3_log_path()


def clear_dead_shells(exe_name: Any, when: str) -> Any:
    return _need(_ME3_SESSION).clear_dead_shells(exe_name, when)


def ensure_steam(timeout: Any) -> Any:
    return _need(_ME3_SESSION).ensure_steam(timeout)


def ensure_steam_running(timeout: Any = 60) -> Any:
    return _need(_ME3_SESSION).ensure_steam_running(timeout)


def launch(game: Any, profile: Any, me3: Any, exe_name: Any, exe: Any = None, extra_args: Any = ()) -> Any:
    return _need(_ME3_SESSION).launch(game, profile, me3, exe_name, exe=exe, extra_args=extra_args)


def wait_for_game(exe_name: Any, appear_timeout: Any, quiet: bool = False) -> bool:
    return _need(_ME3_SESSION).wait_for_game(exe_name, appear_timeout, quiet=quiet)


def steam_running() -> bool:
    return _need(_STEAM).steam_running()


def steam_logged_in() -> Any:
    return _need(_STEAM).steam_logged_in()


def steam_exe() -> Any:
    return _need(_STEAM).steam_exe()


def open_path(target: Any) -> None:
    _need(_DESKTOP).open_path(target)
