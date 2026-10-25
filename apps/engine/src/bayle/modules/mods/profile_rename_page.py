"""Renaming and duplicating a profile, as the Mods page uses them: the name check while typing, the rename or copy
(each leaves the undo record Activity offers) and taking it back. The work is mods.profile_rename's."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from bayle.adapters.system import logging as run_logging
from bayle.modules.mods import folder_check, folder_split, profile_mods, shared_mods
from bayle.modules.mods import profile_rename as renamer
from bayle.modules.mods import shared_mods_page as shared_service
from bayle.modules.mods import undo as mod_undo

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

Error = renamer.ProfileRenameError
FolderError = folder_check.FolderError


def refusal(launch, busy: bool, *, loc: Locations) -> str | None:
    """Why the profile can't be renamed or copied now (one of profile_mods' DELETE_* codes: no profile, run by
    an installer, a job running), or None."""
    return profile_mods.delete_refusal(launch, busy, loc=loc)


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


def duplicate(profile: Path, *, loc: Locations, share: bool = False) -> dict:
    """Copy the .me3 as "<name> copy" (unique). Returns {operation, profile (the copy), name, undo}. share: the
    original's Separate game-file mods are shared first, so the copy links to them instead of copying their files (the
    sharing and the copy are one job, so its Undo takes back both)."""
    shared = shared_mods.share_everything(profile, loc=loc) if share else None
    out = renamer.duplicate(profile, loc=loc, log=run_logging.log)
    out["undo"] = {
        "type": "profile-duplicate",
        "profile": out["profile"],
        "name": out["name"],
        "operation": out["operation"],
    }
    if shared is not None:  # one Undo takes back the copy, then the sharing
        out["undo"] = shared_service.chain(out["name"], shared_service.undo_of("library-share", shared), out["undo"])
    run_logging.set_undo(out["undo"])
    return out


def rename_folder(profile: Path, *, loc: Locations) -> dict:
    """Rename the profile's folder to the profile's name (mods.folder_check). Raises folder_check.FolderError."""
    out = folder_check.rename_folder(profile, loc, run_logging.log)
    out["undo"] = {
        "type": folder_check.KIND,
        "profile": out["profile"],
        "name": out["name"],
        "operation": out["operation"],
    }
    run_logging.set_undo(out["undo"])
    return out


def rename_folder_refusal(profile: Path, *, loc: Locations) -> str | None:
    return folder_check.rename_refusal(profile, loc)


def split_preview(profile: Path, *, loc: Locations) -> folder_split.SplitPlan:
    return folder_split.preview(profile, loc)


def split_folder(profile: Path, *, loc: Locations) -> dict:
    """Give every profile of the crowded folder its own folder (mods.folder_split). Raises folder_check.FolderError."""
    out = folder_split.split(profile, loc, run_logging.log)
    out["undo"] = {
        "type": folder_split.KIND,
        "profile": out["profile"],
        "name": out["name"],
        "operation": out["operation"],
    }
    run_logging.set_undo(out["undo"])
    for note in out["notes"]:
        run_logging.log(f"warning: {note}")
    return out


def undo(record: dict, *, loc: Locations) -> str:
    """Take back what rename or duplicate returned (mods.undo.run). Raises mods.models.UndoError."""
    return mod_undo.run(record, run_logging.log, loc=loc)
