"""What a game's location answers by looking at the machine: its install folder in the Steam libraries, its save
folders, whether it runs, the me3 that launches it and the profiles beside it. Locations (locate.py) holds the game and
the Settings > Locations overrides and hands each question here with the override that applies. On Linux (desktop or
Steam Deck) the game runs through Proton, so its saves live inside the game's Proton prefix and the game process is a
Wine process whose command line names the game's exe."""

from __future__ import annotations

from pathlib import Path

from bayle.adapters.games import me3_paths, paths, steam_paths
from bayle.modules.games import catalog


def installed_dir(game: catalog.Game) -> Path | None:
    """The folder with this game's exe in any Steam library, or None (cached per game for the session)."""
    return steam_paths.find_installed(game.key, game.install_dir, game.exe)


def game_dir(game: catalog.Game, game_exe: str) -> Path | None:
    if game_exe and Path(game_exe).is_file():
        return Path(game_exe).parent
    return installed_dir(game)


def game_running(exe_name: str) -> bool:
    return paths.exe_running(exe_name)


def dead_game_shells(exe_name: str) -> list[int]:
    """Leftover zero-memory copies of the game. A Windows problem; Proton cleans up after itself."""
    return paths.dead_exe_shells(exe_name)


def save_roots(game: catalog.Game) -> list[Path]:
    """Folders that hold the per-account save folders: %APPDATA%\\<game> on Windows, the same folder inside the
    game's Proton prefix on Linux (in whichever Steam library the prefix lives)."""
    return paths.save_roots_for(game.save_dir, game.app_id)


def me3_exe(override: str) -> Path | None:
    return me3_paths.me3_exe(override)


def me3_profiles_dir(override: str) -> Path | None:
    return me3_paths.me3_profiles_dir(override)


def me3_profiles(home: Path | None, game: catalog.Game) -> list[Path]:
    """User-made .me3 profiles for the game (the *-default.me3 ones me3 generates are skipped). A profile that
    names no game in [[supports]] counts for Elden Ring, the only game older profiles were written for."""
    from bayle.modules.settings import layout

    also = [layout.game_root(home, game.key)] if home is not None else []
    return me3_paths.find_profiles(home, game.key, catalog.ELDEN_RING.key, also)
