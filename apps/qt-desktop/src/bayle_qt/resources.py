"""Files shipped inside the desktop package: the window's icon and logos, the self-test list, the updater's data."""

from importlib.resources import files
from pathlib import Path

PACKAGE_DIR = Path(str(files("bayle_qt")))
ASSETS_DIR = PACKAGE_DIR / "assets"
UPDATER_DATA = PACKAGE_DIR / "updater" / "data"  # the watchdog scripts and the release-signing key
