"""Unpacking mod archives (zip, 7z, rar) safely."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.archives import (
        extract,
    )

__all__ = [
    "extract",
]
