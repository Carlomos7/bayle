"""Where me3 and its profiles are on this machine, on Windows and Linux. Nothing here writes to disk."""

import os
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

from bayle.platform.paths import detected

IS_WINDOWS = sys.platform == "win32"


def me3_exe(override: str | None = None):
    """The me3 set in the launcher's settings (override), else me3 on PATH, else its default per-user install
    location. The PATH search and default-folder check are cached for the session (cleared when the settings
    change)."""
    if override and Path(override).is_file():
        return Path(override)
    return detected("me3_exe", _me3_exe_detected)


def _me3_exe_detected():
    found = shutil.which("me3")
    if found:
        return Path(found)
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        candidate = Path(local) / "Programs" / "garyttierney" / "me3" / "bin" / "me3.exe" if local else None
    else:
        candidate = Path.home() / ".local" / "bin" / "me3"
    return candidate if candidate and candidate.exists() else None


def me3_config_dir():
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / "garyttierney" / "me3" / "config" if local else None
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "me3"


def me3_profiles_dir(override: str | None = None):
    """The me3 profile folder set in the launcher's settings (override), else me3's own."""
    if override and Path(override).is_dir():
        return Path(override)
    config = me3_config_dir()
    return config / "profiles" if config else None


# A .me3 profile sits at the top of the profiles folder or one level down in a "<name>-mods" folder beside its assets.
# Those asset folders (mod overrides, natives, ReShade) can hold thousands of files, so the walk stops at this depth
# and skips folders that clearly hold mod content rather than profiles: a full rglob here took seconds on real setups.
_PROFILE_SCAN_DEPTH = 2
_PROFILE_PRUNE = {"mod", "natives", "reshade", "reshade-shaders", "modengine2", "cache", "sd", "movie", "logs"}


def _iter_me3_files(root: Path, depth: int = 0):
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for e in entries:
        if e.is_file() and e.name.endswith(".me3"):
            yield Path(e.path)
        elif (
            e.is_dir()
            and depth < _PROFILE_SCAN_DEPTH
            and e.name.lower() not in _PROFILE_PRUNE
            and not e.name.startswith(".")
        ):
            yield from _iter_me3_files(Path(e.path), depth + 1)


def find_profiles(root: Path | None, game_key: str, unnamed_key: str, also: Iterable[Path] = ()) -> list[Path]:
    """The user-made .me3 profiles under root for one game (the *-default.me3 ones me3 generates are skipped); a
    profile that names no game in [[supports]] counts for unnamed_key. also: the launcher's game folders
    (mods.library.game_root), whose <name>/<name>.me3 are found wherever they are; a folder starting with a dot is
    never a profile's."""
    if not root or not root.exists():
        return []
    ours = [  # the launcher's own folders, deeper than the scan goes
        *root.glob(f"roundtable/{game_key}/profiles/*/*.me3"),
        *(p for d in also for p in Path(d).glob("*/*.me3") if not p.parent.name.startswith(".")),
    ]
    return sorted(
        (
            p
            for p in {*_iter_me3_files(root), *ours}
            if not p.name.endswith("-default.me3") and game_key in (profile_games(p) or (unnamed_key,))
        ),
        key=lambda p: (p.name.lower(), str(p).lower()),  # the Play list shows file names, so order by those
    )


_PROFILE_GAMES_CACHE: dict = {}  # path -> (mtime, games); parsing every .me3 on each game-tab switch is pure waste


def profile_games(profile: Path) -> tuple[str, ...]:
    """The games a .me3 profile says it supports ([[supports]] game = ...), lower-case; empty when it names none.
    Cached by file modification time, so a profile is parsed once until it changes on disk."""
    import tomllib

    profile = Path(profile)
    try:
        mtime = profile.stat().st_mtime
    except OSError:
        return ()
    cached = _PROFILE_GAMES_CACHE.get(profile)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = tomllib.loads(profile.read_text(encoding="utf-8", errors="replace"))
    except OSError, tomllib.TOMLDecodeError:
        data = {}  # unreadable counts as naming no game, and is cached like any answer until the file changes
    rows = data.get("supports") or []
    if isinstance(rows, dict):
        rows = [rows]
    result = tuple(
        str(r.get("game") or "").strip().lower()
        for r in rows
        if isinstance(r, dict) and str(r.get("game") or "").strip()
    )
    _PROFILE_GAMES_CACHE[profile] = (mtime, result)
    return result
