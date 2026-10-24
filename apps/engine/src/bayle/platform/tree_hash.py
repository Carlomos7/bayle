"""Tree hashing and read-only folder handling for the Library's versions."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from pathlib import Path

from bayle.platform import cpu

ID_LENGTH = 16


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def files(folder: Path) -> list[tuple[str, Path]]:
    out = []
    for dirpath, _dirs, names in os.walk(folder):
        for n in names:
            p = Path(dirpath) / n
            out.append((p.relative_to(folder).as_posix(), p))
    return sorted(out)


def tree_hash(folder: Path) -> tuple[str, int]:
    """(version id, size in bytes) of a folder's files: the same files give the same id wherever they are. Hashed in
    a worker process when the window has them (the hashing of a big mod would hold the window's GIL)."""
    version, total = cpu.run_cpu(f"{__name__}:tree_hash_job", {"folder": str(folder)}).result()
    return version, total


def tree_hash_job(folder: str) -> list:
    """The task behind tree_hash (runs in a worker process): [version id, size in bytes]."""
    h, total = hashlib.sha256(), 0
    for rel, p in files(Path(folder)):
        size = p.stat().st_size
        total += size
        h.update(f"{rel}\0{size}\0{_digest(p)}\n".encode())
    return [h.hexdigest()[:ID_LENGTH], total]


def chmod_tree(folder: Path, *, write: bool) -> None:
    for _rel, p in files(folder):
        try:
            mode = p.stat().st_mode
            p.chmod(
                mode | stat.S_IWRITE
                if write
                else (mode | stat.S_IREAD) & ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
            )
        except OSError:
            pass


def delete_tree(folder: Path) -> None:
    """A folder gone, read-only files included."""
    if folder.exists():
        chmod_tree(folder, write=True)
        shutil.rmtree(folder, ignore_errors=True)
