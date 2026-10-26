"""Activity: the jobs index as the Activity page reads it, and undo."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules.activity import (
        service,
    )

__all__ = [
    "service",
]
