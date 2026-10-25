"""Overhaul mods: their configs (resources/overhauls/*.toml and the player's own), as OverhaulConfig. One description
of each overhaul, used to recognise it (Play-page detection, the offline launch's strip), to build it
(adapters.overhauls.engine) and to place its download in the launcher's layout (sources). Reading and writing the
config files is adapters.overhauls.recipes and writer."""

from bayle.modules.overhauls import requirements, sources
from bayle.modules.overhauls.config import (
    RECIPE_VERSION,
    Basic,
    BasicNative,
    Build,
    OverhaulConfig,
    Recognise,
    Requirement,
    recipe_sha256,
    schema,
)

__all__ = [
    "RECIPE_VERSION",
    "Basic",
    "BasicNative",
    "Build",
    "OverhaulConfig",
    "Recognise",
    "Requirement",
    "recipe_sha256",
    "requirements",
    "schema",
    "sources",
]
