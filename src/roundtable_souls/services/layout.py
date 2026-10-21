"""Thin service wrappers for the Settings > Locations layout actions: where profiles live and what the folders are
called. The work is in mods.layout / mods.migrate (relocate, rename_layout; both journaled and undoable); here they
run as logged jobs that leave an Activity Undo. Also the read-only facts the confirms show (counts, size, free space)."""

from __future__ import annotations

import importlib
import os
import shutil
from pathlib import Path

from roundtable_souls.mods import library, move_in
from roundtable_souls.platform import logging as run_logging


def _fn(name: str):
    """relocate / rename_layout live in mods.layout or mods.migrate, whichever the layout work put them in."""
    for mod in ("roundtable_souls.mods.layout", "roundtable_souls.mods.migrate"):
        try:
            found = getattr(importlib.import_module(mod), name, None)
        except ImportError:
            continue
        if found is not None:
            return found
    raise RuntimeError(f"mods.layout.{name} is missing")


def _record(out) -> None:
    undo = out.get("undo") if isinstance(out, dict) else None
    if undo:
        run_logging.set_undo(undo)


def relocate(loc, new_root, progress=None, cancel=None) -> dict:
    """Move the profiles and mods to a new profiles folder, as a logged job with an undo record."""
    run_logging.start_log(f"launcher: move profiles and mods to {new_root}", loc.game.key)
    out = _fn("relocate")(loc, Path(new_root), progress=progress or run_logging.log, cancel=cancel)
    _record(out)
    return out


def rename_layout(loc, **names) -> dict:
    """Rename the game folder pattern and the packages / DLL / shared folders (None = unchanged)."""
    run_logging.start_log("launcher: rename layout folders", loc.game.key)
    out = _fn("rename_layout")(loc, **names)
    _record(out)
    return out


def profiles_facts(loc) -> tuple[int, int]:
    """(profiles, bytes) under the current game's folder: what a move of the profiles folder carries."""
    home = loc.me3_profiles_dir()
    if home is None:
        return 0, 0
    root = library.game_root(home, loc.game.key)
    count = size = 0
    for here, _dirs, files in os.walk(root):
        for f in files:
            if library.is_user_profile(Path(f)):
                count += 1
            try:
                size += os.path.getsize(os.path.join(here, f))
            except OSError:
                pass
    return count, size


def free_bytes(path: Path) -> int | None:
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def plain_profiles(loc) -> list[Path]:
    """The current game's me3 profiles outside Bayle's folder that Move into Bayle's folder accepts."""
    home = loc.me3_profiles_dir()
    if home is None or not Path(home).is_dir():
        return []
    found = []
    for d in [Path(home), *(x for x in sorted(Path(home).iterdir()) if x.is_dir())]:
        for f in sorted(d.glob("*.me3")):
            if library.is_user_profile(f) and move_in.outside(f, loc) and move_in.plan(f, loc).ok:
                found.append(f)
    return found


def move_all(loc, profiles: list[Path]) -> int:
    """Move each profile into Bayle's folder (services.mods.move_into_launcher_folder) and leave ONE Undo that
    takes them all back, the last moved first. Returns how many moved."""
    from roundtable_souls.services import mods as mod_service
    from roundtable_souls.services.shared_mods import chain

    undos = []
    for p in profiles:
        try:
            undos.append(mod_service.move_into_launcher_folder(loc, p)["undo"])
        except Exception as e:  # one refused profile must not stop the rest
            run_logging.log(f"warning: {p.stem} was not moved: {e}")
    if undos:
        run_logging.set_undo(chain(f"{len(undos)} profiles", *undos))
    return len(undos)
