"""Overhaul mods: their configs (data/overhauls/*.toml), read as OverhaulConfig. One description of each overhaul,
used to recognise it (Play-page detection, the offline launch's strip), to build it (mods.engine) and to place its
download in the launcher's layout (sources)."""

from bayle.overhauls import requirements, sources
from bayle.overhauls.config import (
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
