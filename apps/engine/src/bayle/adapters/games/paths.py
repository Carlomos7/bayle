"""Where things are on this machine (a game's folder and saves, whether it runs), on Windows and Linux. Steam is in
steam.py and steam_paths.py, me3 in me3_paths.py, the process list in proc.py.

These are the primitives: each takes what it looks for (an exe name, a save folder, an override). A game's own answers,
with the Settings > Locations overrides applied, are modules/games/locate.py's Locations. On Linux (desktop or Steam
Deck) the game runs through Proton, so its saves live inside the game's Proton prefix and the game process is a Wine
process whose command line names the game's exe. Nothing here writes to disk.
"""

import os
import sys
from pathlib import Path

from bayle.adapters.integrations.steam import steam
from bayle.adapters.system import proc

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")

# Detection (Steam libraries, the game folder, me3.exe) scans PATH and the disk. The answers are stable within a
# session, but Setup.summary()/problems() ask for them many times per game-tab switch, so they are memoised here and
# cleared whenever the settings or the game change (runtime.bootstrap.Engine).
_DETECT_CACHE: dict = {}


def detected(key, compute):
    if key not in _DETECT_CACHE:
        _DETECT_CACHE[key] = compute()
    return _DETECT_CACHE[key]


def clear_detection_cache() -> None:
    _DETECT_CACHE.clear()
    steam.clear_cache()


def exe_running(exe_name: str) -> bool:
    """A real copy of the game whose exe is exe_name runs (one with threads; a starting game, even one me3 holds
    suspended, has at least one, a dead shell has none)."""
    return any(threads > 0 for _, threads in proc.processes(exe_name))


def dead_exe_shells(exe_name: str) -> list[int]:
    """Leftover zero-thread copies of the game. A Windows problem; Proton cleans up after itself."""
    if not IS_WINDOWS:
        return []
    return [pid for pid, threads in proc.processes(exe_name) if threads == 0]


# ------------------------------------------------------------------- saves


def save_roots_for(save_dir: str, app_id: str) -> list[Path]:
    """The per-account save folders' parent for a game whose saves go to %APPDATA%/<save_dir> on Windows, or the
    same folder inside its Proton prefix (compatdata/<app_id>) on Linux, in whichever Steam library that lives."""
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / save_dir] if appdata else []
    roaming = Path("pfx") / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming" / save_dir
    roots: list[Path] = []
    for lib in steam.steam_libraries():
        candidate = lib / "steamapps" / "compatdata" / app_id / roaming
        if candidate.is_dir() and candidate.resolve() not in [r.resolve() for r in roots]:
            roots.append(candidate)
    return roots
