"""The engine's features: their models, rules and workflows, one package per feature. A feature reaches stateful
infrastructure (the database, the settings file, other programs) through the ports the runtime binds; it calls file
formats and the filesystem primitives (adapters/formats, adapters/filesystem) directly."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules import (
        activity,
        coop,
        games,
        launch,
        mods,
        overhauls,
        saves,
        settings,
    )

__all__ = [
    "activity",
    "coop",
    "games",
    "launch",
    "mods",
    "overhauls",
    "saves",
    "settings",
]
