"""Filesystem primitives every feature writes through: atomic and durable writes, settled reads, file locks, the recycle
bin, hashing, the journaled build/operation folders (build), and the launcher's own data folder (data_folder)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.filesystem import (
        build,
        data_folder,
        filelock,
        files,
        hashing,
        trash,
        tree_hash,
    )

__all__ = [
    "build",
    "data_folder",
    "filelock",
    "files",
    "hashing",
    "trash",
    "tree_hash",
]
