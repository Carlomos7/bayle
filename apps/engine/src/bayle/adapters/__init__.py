"""Concrete infrastructure: file formats (formats), filesystem primitives (filesystem), the database and the settings
file (persistence), the game on this machine (games), save files (saves), merging (merging), overhaul builds
(overhauls), archives (archives), Steam and me3 (integrations) and this machine (system). Adapters may use the
features' models and ports, never their workflows."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters import (
        archives,
        filesystem,
        formats,
        games,
        integrations,
        merging,
        overhauls,
        persistence,
        saves,
        system,
    )

__all__ = [
    "archives",
    "filesystem",
    "formats",
    "games",
    "integrations",
    "merging",
    "overhauls",
    "persistence",
    "saves",
    "system",
]
