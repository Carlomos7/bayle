"""Playing: the setups, the play session's sequence, the checks before it (game_checks) and the run's health afterwards
(run_health)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules.launch import (
        game_checks,
        play,
        run_health,
    )

__all__ = [
    "game_checks",
    "play",
    "run_health",
]
