"""What the games feature needs from this machine: where a game, its saves and me3 are, and whether the game runs
(adapters.games.discovery and adapters.games.paths implement these). The runtime binds them
(bayle.runtime.bootstrap.bind_ports); called unbound, they raise."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bayle.modules.games import catalog


class Discovery(Protocol):
    def installed_dir(self, game: catalog.Game) -> Path | None: ...

    def game_dir(self, game: catalog.Game, game_exe: str) -> Path | None: ...

    def game_running(self, exe_name: str) -> bool: ...

    def dead_game_shells(self, exe_name: str) -> list[int]: ...

    def save_roots(self, game: catalog.Game) -> list[Path]: ...

    def me3_exe(self, override: str) -> Path | None: ...

    def me3_profiles_dir(self, override: str) -> Path | None: ...

    def me3_profiles(self, home: Path | None, game: catalog.Game) -> list[Path]: ...


class GamePaths(Protocol):
    def exe_running(self, exe_name: str) -> bool: ...


# bound by bayle.runtime.bootstrap.bind_ports only; the concrete modules are the bound objects, so a test that patches
# one of their functions is seen at the next call
_DISCOVERY: Discovery | None = None
_PATHS: GamePaths | None = None


def _discovery() -> Discovery:
    if _DISCOVERY is None:
        raise RuntimeError("games ports are unbound: bind_ports() was not called")
    return _DISCOVERY


def installed_dir(game: catalog.Game) -> Path | None:
    return _discovery().installed_dir(game)


def game_dir(game: catalog.Game, game_exe: str) -> Path | None:
    return _discovery().game_dir(game, game_exe)


def game_running(exe_name: str) -> bool:
    return _discovery().game_running(exe_name)


def dead_game_shells(exe_name: str) -> list[int]:
    return _discovery().dead_game_shells(exe_name)


def save_roots(game: catalog.Game) -> list[Path]:
    return _discovery().save_roots(game)


def me3_exe(override: str) -> Path | None:
    return _discovery().me3_exe(override)


def me3_profiles_dir(override: str) -> Path | None:
    return _discovery().me3_profiles_dir(override)


def me3_profiles(home: Path | None, game: catalog.Game) -> list[Path]:
    return _discovery().me3_profiles(home, game)


def exe_running(exe_name: str) -> bool:
    if _PATHS is None:
        raise RuntimeError("games ports are unbound: bind_ports() was not called")
    return _PATHS.exe_running(exe_name)
