"""The Library as the Mods page uses it: sharing a profile's game-file mods, linking other profiles, separate copies,
updates and removing unused versions. Each leaves the Activity undo record (mods.undo); the work is mods.shared_mods'."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.mods import shared_mods
from bayle.platform import logging as run_logging

if TYPE_CHECKING:
    from bayle.game.locate import Locations

Error = shared_mods.LibraryError


def undo_of(kind: str, out: dict) -> dict:
    """The Activity undo record of one Library change (what share, use_in, ... returned)."""
    return {"type": kind, "profile": out["profile"], "name": out.get("name", ""), "operation": out["operation"]}


def chain(name: str, *undos: dict) -> dict:
    """One Activity undo for several changes a job made, given in the order they were made: Undo takes the last one
    back first, and is offered only while every one still can be."""
    return {"type": "multi", "name": name, "profile": undos[0].get("profile", ""), "undos": list(reversed(undos))}


def _record(kind: str, out: dict) -> dict:
    out["undo"] = undo_of(kind, out)
    run_logging.set_undo(out["undo"])
    return out


def share(profile: Path, indexes: list[int], *, loc: Locations) -> dict:
    """Share these Separate packages. Raises Error (nothing changed) when it can't be done."""
    return _record("library-share", shared_mods.share(profile, indexes, loc=loc))


def use_in(mod_id: str, version: str, targets: dict[Path, bool], *, loc: Locations) -> dict:
    """Link profiles to a version; targets: profile -> replace its own Separate copy."""
    return _record("library-use", shared_mods.use_in(mod_id, version, targets, loc=loc))


def separate(profile: Path, indexes: list[int], *, loc: Locations) -> dict:
    return _record("library-separate", shared_mods.separate(profile, indexes, loc=loc))


def update(profile: Path, index: int, source: Path, *, everywhere: bool, loc: Locations, label: str = "") -> dict:
    return _record(
        "library-update", shared_mods.update(profile, index, source, everywhere=everywhere, loc=loc, label=label)
    )


def unused(loc: Locations) -> tuple[list[tuple[shared_mods.SharedMod, shared_mods.Version]], str | None]:
    """(versions no profile uses, why nobody can tell or None): for the confirm."""
    return shared_mods.unused(loc)


def remove_unused(*, loc: Locations) -> dict:
    out = shared_mods.remove_unused(loc=loc)
    if out["undoable"]:
        _record("library-clean", out)
    return out


def shared_ref(profile: Path, entry: dict, *, loc: Locations) -> tuple[str, str] | None:
    """(mod id, version id) when a profile entry is Shared, else None."""
    home = loc.me3_profiles_dir()
    if home is None or not entry.get("path"):
        return None
    root = shared_mods.library.library_root(home, loc.game.key)
    return shared_mods.link_target(Path(profile), root, entry["path"])


def version_size(mod_id: str, version: str, *, loc: Locations) -> int:
    rec = shared_mods.read_mod(shared_mods.root_of(loc), mod_id)
    found = rec.version(version) if rec else None
    return found.size if found else 0


def display_name(mod_id: str, *, loc: Locations) -> str:
    rec = shared_mods.read_mod(shared_mods.root_of(loc), mod_id)
    return rec.name if rec else mod_id


def candidates(profile: Path, mod_id: str, *, loc: Locations) -> list[shared_mods.Candidate]:
    return shared_mods.candidates(loc, profile, mod_id)


def listing(loc: Locations) -> list[shared_mods.ModInfo]:
    return shared_mods.listing(loc)


_scanned: dict[str, tuple[tuple, tuple[int, int]]] = {}  # per game: (profile files' stamp, result)
_scan_lock = threading.Lock()


def _stamp(loc: Locations) -> tuple:
    home = loc.me3_profiles_dir()
    if home is None:
        return ()
    try:
        found = shared_mods.profiles_in(shared_mods.library.profiles_root(home, loc.game.key))
        return tuple((str(p), p.stat().st_mtime_ns) for p in found)
    except OSError:
        return ()


def duplicates(loc: Locations) -> tuple[int, int]:
    """(mods in several profiles as Separate copies, bytes they waste) for the Mods page's hint; (0, 0) when it can't
    be worked out. Scanned again only when a profile file changed (an install, remove or share rewrites one), so a
    page refresh costs a few stats."""
    with _scan_lock:
        stamp = _stamp(loc)
        hit = _scanned.get(loc.game.key)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            twins = shared_mods.duplicates(loc)
        except OSError:
            return 0, 0
        out = len({t.name.lower() for t in twins}), shared_mods.duplicate_total(twins)
        _scanned[loc.game.key] = stamp, out
        return out


def separate_copies(profile: Path, *, loc: Locations) -> list[shared_mods.Copy]:
    return shared_mods.separate_copies(loc, only=Path(profile))
