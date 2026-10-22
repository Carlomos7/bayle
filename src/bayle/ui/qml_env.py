"""What every Qt Quick engine here shares: the QML folder, the bundled fonts (registered once) and Qt's compiled-QML
cache kept in the run's data folder."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtGui import QFontDatabase

from bayle.platform import data_folder
from bayle.ui import code_editor  # noqa: F401  (registers Roundtable.Code for QML)

UI = Path(__file__).resolve().parent
QML_DIR = UI / "qml"
FONTS_DIR = UI / "assets" / "fonts"

_fonts_loaded: list[str] = []


def load_fonts() -> list[str]:
    """Register the bundled fonts with Qt (once); the families they add."""
    if not _fonts_loaded:
        for ttf in sorted(FONTS_DIR.glob("*.ttf")):
            font_id = QFontDatabase.addApplicationFont(str(ttf))
            _fonts_loaded.extend(QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else [])
    return sorted(set(_fonts_loaded))


def use_qml_cache_folder() -> Path | None:
    """Keep Qt's compiled-QML cache in this run's data folder (cache/qmlcache). Left alone, Qt names the folder after
    the program (%LOCALAPPDATA%/<name>/cache), which for the packaged build is the real data folder's name: a
    self-test or a test build in a temporary data folder would write beside the user's data. With no data folder set
    (a test without one), the disk cache is off for the run."""
    try:
        folder = data_folder.data_root() / "cache" / "qmlcache"
    except RuntimeError:
        os.environ["QML_DISABLE_DISK_CACHE"] = "1"
        return None
    os.environ["QML_DISK_CACHE_PATH"] = str(folder)
    return folder
