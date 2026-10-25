"""Other programs as programs: Steam (whether it runs and is signed in, its libraries, its shortcuts) and me3 (its
version, its info, the latest release)."""

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
