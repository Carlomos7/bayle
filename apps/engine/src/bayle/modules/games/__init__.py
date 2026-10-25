"""The games the launcher knows: which ones (catalog), each one's files from resources/games (config), where a game,
its saves and me3 are once the Settings > Locations overrides apply (locate: the Locations value), and the port that
finds them on this machine (ports; adapters.games implements it)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules.games import (
        catalog,
        config,
        locate,
    )

__all__ = [
    "catalog",
    "config",
    "locate",
]
