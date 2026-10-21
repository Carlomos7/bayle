"""Adopting a setup into the library, as the Mods page uses it: find the setups, preview, adopt (a logged job with an
undo record), stop offering one. The work is mods.adopt's."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.config.settings import change_settings, load_settings
from roundtable_souls.mods import adopt as library_adopt
from roundtable_souls.platform import logging as run_logging

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations


def find_setups(loc: Locations) -> list[library_adopt.ExistingSetup]:
    """Every setup of the game that is not in the library yet (mods.adopt.setups)."""
    return library_adopt.setups(loc)


def setup_of(loc: Locations, profile: Path) -> tuple[library_adopt.ExistingSetup | None, bool]:
    """(the setup holding this profile, whether it is offered): None when the profile is in the library already."""
    here = os.path.normcase(os.path.abspath(profile))
    gone = {os.path.normcase(p) for p in load_settings().adopt_dismissed}
    for s in find_setups(loc):
        if any(os.path.normcase(os.path.abspath(p)) == here for p in s.profiles):
            return s, os.path.normcase(str(s.folder)) not in gone
    return None, False


def dismiss(setup: library_adopt.ExistingSetup) -> None:
    """Stop offering this profile (Adopt into the library... in the menu still works)."""
    change_settings(lambda cur: {"adopt_dismissed": [*cur.adopt_dismissed, str(setup.folder)]})


def preview_adopt(
    setup: library_adopt.ExistingSetup, *, loc: Locations, move_unused: tuple[Path, ...] | list[Path] = ()
):
    """What adopting does (mods.adopt.AdoptPreview: lines, refusals, unused folders to choose from)."""
    return library_adopt.preview(setup, loc=loc, move_unused=move_unused)


def adopt(preview: library_adopt.AdoptPreview, *, loc: Locations) -> dict:
    """Adopt as previewed, as one operation, and leave its undo record (Undo adoption)."""
    out = library_adopt.adopt(preview, loc=loc, log=run_logging.log)
    run_logging.set_undo(
        {
            "type": "library-adopt",
            "profile": out["profiles"][0],
            "name": preview.setup.folder.name,
            "operation": out["operation"],
        }
    )
    for note in out["notes"]:
        run_logging.log(f"warning: {note}")
    run_logging.log(f"done: {preview.setup.folder.name} is in the library")
    return out
