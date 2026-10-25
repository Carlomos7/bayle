"""Building overhauls: reading and writing their configs (recipes, writer), the basic engine (basic), script hooks
(hooks), the Lua and HKS checks, the recipe engine (engine) and its tool backends."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.overhauls import (
        backends,
        basic,
        engine,
        hks_check,
        hooks,
        lua_check,
        recipes,
        writer,
    )

__all__ = [
    "backends",
    "basic",
    "engine",
    "hks_check",
    "hooks",
    "lua_check",
    "recipes",
    "writer",
]
