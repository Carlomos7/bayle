"""What each persisted kind of operation and undo record does, looked up by its string.

The strings are stored (an operation's journal says `kind`, an Activity record says `type`), so they never change. A
module that owns a kind registers it at the bottom of its own file; operations.recover and undo.run find the handler
here instead of importing every owner. ensure_loaded() imports the owners once (mods/handlers.py) on first use, so a
caller needs nothing but this module.

recover  finishers: an interrupted operation of this kind whose launcher records were not updated yet.
undo     available(record) and run(record, log, loc) of an Activity undo record's type.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.adapters.filesystem import build

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

LIBRARY = ("library-share", "library-use", "library-separate", "library-update", "library-clean")  # mods.shared_mods
OPERATIONS = ("install", "update", "rollback")
# An overhaul's install or update with the launcher, and its removal (mods.overhaul_install): the operation's folder
# says what to take back; the removal's folders come back from the Recycle Bin.
OVERHAUL = ("overhaul-install", "overhaul-update", "overhaul-remove", "overhaul-turn-off", "overhaul-reapply")


@dataclass(frozen=True)
class Finisher:
    finish: Callable[[build.Operation], object]
    said: str  # what recovery reports once the records are brought up to date


@dataclass(frozen=True)
class UndoKind:
    available: Callable[[dict], bool]
    run: Callable[[dict, Callable[[str], None], Locations], str]
    gone: Callable[[dict], str] | None = None  # the sentence when it can't be taken back; None: run() decides


FINISHERS: dict[str, Finisher] = {}
STAGE_CLEANERS: list[Callable[[Path], None]] = []  # what an interrupted change staged in a game folder: copies only
UNDO: dict[str, UndoKind] = {}


def register_finisher(kinds: tuple[str, ...], finish: Callable[[build.Operation], object], said: str) -> None:
    for kind in kinds:
        FINISHERS[kind] = Finisher(finish, said)


def register_undo(
    types: tuple[str, ...],
    available: Callable[[dict], bool],
    run: Callable[[dict, Callable[[str], None], Locations], str],
    gone: Callable[[dict], str] | None = None,
) -> None:
    for t in types:
        UNDO[t] = UndoKind(available, run, gone)


def fixed(text: str) -> Callable[[dict], str]:
    return lambda undo: text


def named(default: str) -> Callable[[dict], str]:
    """'<name> can no longer be taken back.', the record's own name or this default."""
    return lambda undo: f"{undo.get('name') or default} can no longer be taken back."


def operation_active(undo: dict) -> bool:
    """The operation's folder is still there to take back."""
    return bool(undo.get("operation")) and build._state(Path(str(undo["operation"]))) == build.ACTIVE


def operation_active_with_profile(undo: dict) -> bool:
    """...and so is the profile it changed, when it names one."""
    return operation_active(undo) and (not undo.get("profile") or Path(undo["profile"]).is_file())


_loaded = False


def ensure_loaded() -> None:
    """Make sure every owner has registered its kinds (importing a module registers its own)."""
    global _loaded
    if not _loaded:
        from bayle.modules.mods import handlers  # noqa: F401  (imported for the registrations)

        _loaded = True
