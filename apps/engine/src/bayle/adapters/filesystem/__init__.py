"""Filesystem primitives every feature writes through: atomic and durable writes, settled reads, file locks, the recycle
bin, hashing, and the journaled build/operation folders (build)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.filesystem import (
        build,
        filelock,
        files,
        hashing,
        trash,
        tree_hash,
    )

__all__ = [
    "build",
    "filelock",
    "files",
    "hashing",
    "trash",
    "tree_hash",
]
