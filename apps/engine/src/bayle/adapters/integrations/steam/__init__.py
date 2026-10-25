"""Steam: whether it runs and is signed in, where it keeps games, and its shortcuts."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.integrations.steam import (
        steam,
        steam_paths,
        steam_shortcuts,
    )

__all__ = [
    "steam",
    "steam_paths",
    "steam_shortcuts",
]
