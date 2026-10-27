"""Where this program runs from and where the launcher keeps its data.

Data (settings, logs, backups, the save library, caches) never lives in a folder an update or an uninstall
replaces. Velopack replaces <root>\\current on every update and removes <root> on uninstall, so:

  installed (Velopack setup)   %LOCALAPPDATA%\\RoundtableSouls (Linux: $XDG_DATA_HOME/RoundtableSouls)
  portable (Velopack zip)      <root>\\RoundtableSouls-data, beside Update.exe; the copy and its data move together
  AppImage                     $XDG_DATA_HOME/RoundtableSouls (the program runs from a read-only mount)
  ROUNDTABLE_SOULS_DATA=<dir>  that folder, for any kind of copy
  running from source          the repository folder
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from bayle.adapters.system import identity
from bayle.resources import PACKAGE_DIR

FROZEN = bool(getattr(sys, "frozen", False))
APP_DIR_NAME = identity.get().data_dir_name
LEGACY_APP_DIR_NAMES = ("Roundtable",)
DATA_ENV = "ROUNDTABLE_SOULS_DATA"
BACKEND_DATA_ENV = "BAYLE_DATA"  # the desktop shell's data folder for --backend (decision 0016); required there


def exe_dir() -> Path:
    if FROZEN:
        return Path(sys.executable).resolve().parent
    return PACKAGE_DIR.resolve().parents[3]  # apps/engine/src/bayle -> the repository


def velopack_root() -> Path | None:
    """The Velopack folder (Update.exe, the stub, current\\, packages\\) when this program runs from current\\."""
    if not FROZEN:
        return None
    here = exe_dir()
    if here.name.lower() == "current" and (here.parent / "Update.exe").is_file():
        return here.parent
    return None


def appimage() -> Path | None:
    """The AppImage file this program runs from (Linux), or None."""
    value = os.environ.get("APPIMAGE")
    return Path(value) if FROZEN and value else None


def is_portable() -> bool:
    """A Velopack portable copy (unzipped; Velopack marks it with a .portable file)."""
    root = velopack_root()
    return bool(root and (root / ".portable").is_file())


def is_installed() -> bool:
    """Installed by the Velopack setup (an uninstall entry; updates in place), as opposed to a portable copy."""
    return velopack_root() is not None and not is_portable()


def installed_pack_id() -> str | None:
    """The app ID Velopack installed this program under (current\\sq.version), or None outside a Velopack copy."""
    root = velopack_root()
    if root is None:
        return None
    try:
        text = (root / "current" / "sq.version").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r"<id>\s*([^<\s]+)\s*</id>", text)
    return m.group(1) if m else None


def identity_matches() -> bool:
    """This program belongs to the install it runs in: its built-in app ID is the one Velopack installed it under.
    Anything that acts on an install (moving from the old installer, applying an update) checks this first, so a
    build carrying another identity can never act on someone else's install."""
    if appimage() is not None and velopack_root() is None:
        return True  # an AppImage has no install of its own to mix up
    found = installed_pack_id()
    return found is not None and found == identity.get().pack_id


def launch_target() -> Path:
    """What a shortcut should start: the Velopack stub (its path never changes across updates), the AppImage, or
    the program itself."""
    root = velopack_root()
    if root is not None:
        stub = root / identity.get().stub_name
        if stub.is_file():
            return stub
    return appimage() or Path(sys.executable)


def _writable(folder: Path) -> bool:
    try:
        probe = folder / ".write-test"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def _per_user_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home())
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def backend_data_dir() -> Path:
    """The data folder `--backend` runs on: BAYLE_DATA, which the desktop shell always sets. It is never guessed the
    way data_dir() guesses for the window, because those guesses are the program's own folder (replaced by updates and
    uninstall), the repository, or the Qt app's data folder. ValueError says which rule a value broke."""
    value = os.environ.get(BACKEND_DATA_ENV, "").strip()
    if not value:
        raise ValueError(f"{BACKEND_DATA_ENV} is not set; the desktop app sets it to its data folder")
    folder = Path(value).expanduser().resolve()
    # frozen, the engine sits in a folder of the shell's install (resources), so the install is one level up
    program = exe_dir().parent if FROZEN else exe_dir()
    if folder.is_relative_to(program):
        raise ValueError(f"{BACKEND_DATA_ENV} ({folder}) is inside the program folder {program}")
    qt_data = (_per_user_root() / APP_DIR_NAME).resolve()
    if folder.is_relative_to(qt_data):
        raise ValueError(f"{BACKEND_DATA_ENV} ({folder}) is the Qt app's data folder {qt_data}")
    return folder


def data_dir() -> Path:
    """Where launcher_settings.json, logs, backups and caches live; never inside a folder updates replace."""
    override = os.environ.get(DATA_ENV, "").strip()
    if override:
        folder = Path(override).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    root = velopack_root()
    if root is not None and is_portable():
        folder = root / identity.get().portable_data_name
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    if not FROZEN:
        return exe_dir()  # the repository, when running from source
    if root is None and appimage() is None and _writable(exe_dir()):
        return exe_dir()  # a build run straight from dist\ (not installed, not packaged): beside itself
    base = _per_user_root()
    new = base / APP_DIR_NAME
    if root is not None and new.resolve() == root.resolve():  # never the folder an uninstall removes
        raise RuntimeError(f"The data folder {new} is the install folder; the app ID must differ from it.")
    if not new.exists():
        for legacy in LEGACY_APP_DIR_NAMES:
            old = base / legacy
            if old.is_dir():
                try:
                    old.rename(new)
                    break
                except OSError:
                    pass
    new.mkdir(parents=True, exist_ok=True)
    return new
