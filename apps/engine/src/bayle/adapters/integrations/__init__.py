"""Other programs the launcher works with: Steam (steam) and me3 (me3)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.integrations import (
        me3,
        steam,
    )

__all__ = [
    "me3",
    "steam",
]
