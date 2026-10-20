"""Renaming and duplicating a profile, as the Mods page uses them: the name check while typing, the rename or copy
(each leaves the undo record Activity offers) and taking it back. The work is mods.profile_rename's."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.mods import profile_rename as renamer
from roundtable_souls.mods import undo as mod_undo
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import profile_mods

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

Error = renamer.ProfileRenameError


def refusal(setup, busy: bool, *, loc: Locations) -> str | None:
    """Why the setup's profile can't be renamed or copied now (one of profile_mods' DELETE_* codes: no profile, run by
    an installer, a job running), or None."""
    return profile_mods.delete_refusal(setup, busy, loc=loc)


def name_problem(profile: Path, name: str) -> str | None:
    """Why `name` can't be the profile's new name, in plain words, or None (reads the profile's folder only)."""
    return renamer.name_problem(profile, name)


def rename(profile: Path, name: str, *, loc: Locations) -> dict:
    """Rename as one operation. Returns {operation, profile (the new path), name, new, notes, undo}. Raises Error with
    the reasons when it can't be done; nothing is changed then."""
    plan = renamer.preview(profile, name, loc=loc)
    out = renamer.apply(plan, loc=loc, log=run_logging.log)
    out["undo"] = {"type": renamer.KIND, "profile": out["profile"], "name": out["name"], "operation": out["operation"]}
    run_logging.set_undo(out["undo"])
    for note in out["notes"]:
        run_logging.log(f"warning: {note}")
    return out


def duplicate(profile: Path, *, loc: Locations) -> dict:
    """Copy the .me3 as "<name> copy" (unique). Returns {operation, profile (the copy), name, undo}."""
    out = renamer.duplicate(profile, loc=loc, log=run_logging.log)
    out["undo"] = {
        "type": "profile-duplicate",
        "profile": out["profile"],
        "name": out["name"],
        "operation": out["operation"],
    }
    run_logging.set_undo(out["undo"])
    return out


def undo(record: dict, *, loc: Locations) -> str:
    """Take back what rename or duplicate returned (mods.undo.run). Raises mods.undo.UndoError."""
    return mod_undo.run(record, run_logging.log, loc=loc)
