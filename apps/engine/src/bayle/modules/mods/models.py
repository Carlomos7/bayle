"""The install plan's shape (what plan_mod_install found in a source and what install_mod would do with it, validated
before the window sees it), and the types the mods modules share: their errors and a load order dependency. They
live here, below every mods module, so none has to import another one just to name them."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModEntry(BaseModel):
    """One [[packages]] or [[natives]] block a plan would add."""

    kind: Literal["package", "native"]
    path: str
    id: str | None = None


class ModPlan(BaseModel):
    """What `plan_mod_install` found in a source and what `install_mod` would do with it."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    kind: Literal["package", "native", "me3", "profile", "unknown"]  # me3: only a profile, refused
    name: str
    root: Path
    staging: Path | None = None
    array_form: bool
    dest: Path | None = None
    entries: list[ModEntry] = Field(default_factory=list)
    exists: bool = False
    in_place: bool = False
    already_listed: list[str] = Field(default_factory=list)
    error: str | None = None


class ModError(Exception):
    """A profile or entry that can't be read or changed as asked (the message is for the player)."""


class EngineError(RuntimeError):
    """The overhaul engine could not build or remove a change (adapters.overhauls.engine); the output in place is
    unchanged."""


class UndoError(RuntimeError):
    """A job that can't be taken back any more (see mods.undo)."""


@dataclass(frozen=True)
class Dependent:
    """One load_after / load_before entry: the id it names, and whether me3 may go on without it."""

    id: str
    optional: bool


def dependents(raw) -> list[Dependent]:
    """load_after / load_before as me3 reads them: {id, optional}. An entry without optional, or a bare name, is
    taken as required (me3 itself does not read such a profile)."""
    out = []
    for d in raw or []:
        if isinstance(d, dict) and d.get("id"):
            out.append(Dependent(str(d["id"]), d.get("optional") is True))
        elif isinstance(d, str):
            out.append(Dependent(d, False))
    return out
