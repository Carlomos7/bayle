"""me3 as a program: its version and info, and the latest release (me3_info)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.integrations.me3 import (
        me3_info,
    )

__all__ = [
    "me3_info",
]
