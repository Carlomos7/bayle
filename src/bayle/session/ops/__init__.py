"""The operations the program registers on the default registry, one module per page. Importing this package
registers them all (the API and the window session do)."""

from bayle.session.ops import (
    mod_configs,
    mods,
    mods_entries,
    mods_install,
    mods_library,
    mods_overhaul,
    mods_profile,
    profile_transfer,
    saves,
    settings,
    shell,
)

__all__ = [
    "mod_configs",
    "mods",
    "mods_entries",
    "mods_install",
    "mods_library",
    "mods_overhaul",
    "mods_profile",
    "profile_transfer",
    "saves",
    "settings",
    "shell",
]
