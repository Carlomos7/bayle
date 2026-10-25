"""Steam as a program: whether it runs and is signed in, its libraries, and its shortcuts."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.integrations.steam import (
        steam,
        steam_shortcuts,
    )

__all__ = [
    "steam",
    "steam_shortcuts",
]
