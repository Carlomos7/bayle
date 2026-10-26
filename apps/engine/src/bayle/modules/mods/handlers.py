"""Every module that owns a persisted operation kind or undo type, imported so each registers it (mods/kinds.py)."""

from bayle.modules.mods import (  # noqa: F401
    dll_folders,
    folder_check,
    folder_split,
    layout,
    migrate,
    move_in,
    operations,
    overhaul_install,
    profile_import,
    profile_rename,
    rebuild,
    rename,
    shared_mods,
)
