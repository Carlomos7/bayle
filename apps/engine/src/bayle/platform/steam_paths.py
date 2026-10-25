"""Where a game is installed, found through the Steam libraries (steam.py lists those)."""

from pathlib import Path

from bayle.platform import steam
from bayle.platform.paths import detected


def find_installed(key: str, install_dir: str, exe: str) -> Path | None:
    """The folder with exe under steamapps/common/install_dir in any Steam library, or None (cached per key for the
    session)."""

    def find():
        for root in steam.steam_libraries():
            candidate = root / "steamapps" / "common" / Path(install_dir)
            if (candidate / exe).exists():
                return candidate
        return None

    return detected(("installed_dir", key), find)
