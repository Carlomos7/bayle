"""The game on this machine and its own files: finding it and its saves (discovery, paths), its packed archives
(archives), its Oodle library (oodle), its executable's version (exe) and what the launcher knows about how it reads
what it is given (knowledge)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.games import (
        archives,
        discovery,
        exe,
        knowledge,
        oodle,
        paths,
    )

__all__ = [
    "archives",
    "discovery",
    "exe",
    "knowledge",
    "oodle",
    "paths",
]
