"""The Library as the Mods page uses it: sharing a profile's game-file mods, linking other profiles, separate copies,
updates and removing unused versions. Each leaves the Activity undo record (mods.undo); the work is mods.shared_mods'."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.mods import shared_mods
from roundtable_souls.platform import logging as run_logging

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

Error = shared_mods.LibraryError


def _record(kind: str, out: dict) -> dict:
    out["undo"] = {"type": kind, "profile": out["profile"], "name": out.get("name", ""), "operation": out["operation"]}
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
