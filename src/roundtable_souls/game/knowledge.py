"""What the launcher knows about how the game reads what it is given, beyond the file formats: data the game-model
session derived from the game (tools/roundtable-dev/rea-eldenring/game-model in the owner's workspace), shipped in
data/games.

<game>-exe-lists.json: lists that live in the game's executable, keyed by its FileVersion (game.exe): the command IDs
its character scripts (HKS env/act) and talk scripts (ESD) can use, its event instructions (EMEVD) and the functions it
gives character scripts. exe_lists() picks the installed build's lists; an unknown version gets the newest, said to be
possibly out of date, and a known version with another SHA-256 is used but called unverified.

<game>-binders.json: per binder kind (partsbnd, anibnd, ...) how the game finds an inner file: by its ID, by its name,
or both agree (binder_identity).

Lists that the game's own files carry (the parameter table names, the shared character scripts' functions) are not
here: they are read from the installed game when a check runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from roundtable_souls.game import exe as game_exe
from roundtable_souls.resources import DATA_DIR

GAMES_DIR = DATA_DIR / "games"
Identity = Literal["id", "name", "both"]


class ExeVersionLists(BaseModel):
    model_config = ConfigDict(extra="forbid")
    game: str  # the game's own version name ("1.17.1")
    exe_sha256: str
    derived: str  # when (a date)
    sources: dict[str, str]  # list name -> where in the exe it comes from
    hks_env_ids: list[int]
    hks_act_ids: list[int]
    hks_act_ids_tolerated: list[int]  # act IDs the game's own script calls without a case (no-ops): not reported
    hks_natives: list[str]  # global functions the exe gives character scripts
    talk_command_ids: list[int]  # bank 1 (and bank 5's) command indices
    talk_function_ids: list[int]
    emevd_instructions: dict[str, list[int]]  # bank -> instruction IDs
    emevd_labels: dict[str, list[int]]  # bank -> label IDs the interpreter handles itself


class ExeLists(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = ""
    versions: dict[str, ExeVersionLists]  # FileVersion -> lists


class Omission(BaseModel):
    """How the build report calls inner files of this kind that a mod's copy lacks, and what that does in game."""

    model_config = ConfigDict(extra="forbid")
    one: str
    many: str
    effect: str = ""


class BinderKind(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: Identity
    omission: Omission | None = None


class BinderKinds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = ""
    kinds: dict[str, BinderKind]


@cache
def _exe_lists(game: str) -> ExeLists:
    return ExeLists.model_validate(json.loads((GAMES_DIR / f"{game}-exe-lists.json").read_text(encoding="utf-8")))


@cache
def binder_kinds(game: str = "eldenring") -> BinderKinds:
    return BinderKinds.model_validate(json.loads((GAMES_DIR / f"{game}-binders.json").read_text(encoding="utf-8")))


def _version_key(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        return (0,)


@dataclass(frozen=True)
class Lists:
    """The exe-derived lists a check uses, and how sure they are for the installed build."""

    lists: ExeVersionLists
    version: str  # the FileVersion they were derived from
    caveat: str = ""  # "" when they are the installed exe's own; else said beside every finding that uses them


def exe_lists(exe: Path | str | None, game: str = "eldenring") -> Lists:
    """The lists for the game exe at `exe` (None or unreadable: the newest known, with a caveat)."""
    known = _exe_lists(game).versions
    newest = max(known, key=_version_key)
    version = game_exe.file_version(exe) if exe is not None else None
    if version is None:
        return Lists(known[newest], newest, f"the game's version could not be read; lists of {known[newest].game} used")
    if version not in known:
        return Lists(
            known[newest],
            newest,
            f"the game ({version}) is newer or other than the launcher knows; lists of {known[newest].game} used, "
            "so this may be out of date",
        )
    lists = known[version]
    sha = game_exe.sha256(exe) if exe is not None else None
    if sha is not None and sha != lists.exe_sha256:
        return Lists(lists, version, f"an unverified build of {lists.game} (its exe differs from the one checked)")
    return Lists(lists, version)


def binder_identity(kind: str, game: str = "eldenring") -> Identity | None:
    """How the game finds the inner files of a binder kind ("partsbnd"): "id", "name", "both" (they agree), or None
    when the kind is not in the table."""
    found = binder_kinds(game).kinds.get(kind.lower())
    return found.identity if found else None


def binder_omission(kind: str, game: str = "eldenring") -> Omission | None:
    found = binder_kinds(game).kinds.get(kind.lower())
    return found.omission if found else None


def binder_kind(name: str) -> str:
    """A binder's kind from its file name: the last extension before .dcx ("bd_m_1000.partsbnd.dcx" -> "partsbnd")."""
    low = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    low = low.removesuffix(".dcx")
    return low.rsplit(".", 1)[-1] if "." in low else ""
