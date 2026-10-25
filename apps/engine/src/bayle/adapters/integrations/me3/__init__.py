"""me3: finding it and its version (me3_info, me3_paths) and the play session's steps through it (session)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.integrations.me3 import (
        me3_info,
        me3_paths,
        session,
    )

__all__ = [
    "me3_info",
    "me3_paths",
    "session",
]
