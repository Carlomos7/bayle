"""The installed game: which games the launcher knows (catalog), its configuration from data/games (config), its
own packed archives (archives), its Oodle library (oodle), its executable's version (exe) and what the launcher knows
about how it reads what it is given (knowledge)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.game import (
        archives,
        catalog,
        config,
        exe,
        knowledge,
        oodle,
    )

__all__ = [
    "archives",
    "catalog",
    "config",
    "exe",
    "knowledge",
    "oodle",
]
