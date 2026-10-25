"""The game on this machine: finding it, its saves and me3 (discovery, paths, steam_paths, me3_paths), playing it
(session: Steam started, the launch through me3, waiting for the exit, leftover shells cleared), its packed archives
(archives), its Oodle library (oodle), its executable's version (exe) and what the launcher knows about how it reads
what it is given (knowledge)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.games import (
        archives,
        discovery,
        exe,
        knowledge,
        me3_paths,
        oodle,
        paths,
        session,
        steam_paths,
    )

__all__ = [
    "archives",
    "discovery",
    "exe",
    "knowledge",
    "me3_paths",
    "oodle",
    "paths",
    "session",
    "steam_paths",
]
