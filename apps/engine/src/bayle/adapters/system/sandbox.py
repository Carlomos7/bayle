"""The guard a development build (Bayle Dev) runs under. The desktop shell points LOCALAPPDATA and APPDATA at a
sandbox, but paths written down earlier (settings, Activity's undo records, backup notes, all copied from a real
install) can still name the player's real folders. BAYLE_PROTECT lists those real folders: nothing in them is opened,
listed or changed, except this run's own data folder, program and temp folder inside them. Nothing outside the
allowed folders is written at all. BAYLE_SANDBOX_ALLOW (os.pathsep-separated) adds folders a test needs, such as
another drive for a profiles move.

Python's audit hooks see every file the engine itself opens, lists or changes; a child process (an archive tool, me3)
is not seen, and neither is a Windows call made through ctypes (the Recycle Bin)."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

PROTECT_ENV = "BAYLE_PROTECT"
ALLOW_ENV = "BAYLE_SANDBOX_ALLOW"
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# event -> (which arguments are paths, whether it changes them); "open" is judged by its mode and flags
_EVENTS = {
    "os.listdir": ((0,), False),
    "os.scandir": ((0,), False),
    "glob.glob": ((0,), False),
    "os.remove": ((0,), True),
    "os.rmdir": ((0,), True),
    "os.mkdir": ((0,), True),
    "os.chmod": ((0,), True),
    "os.utime": ((0,), True),
    "os.truncate": ((0,), True),
    "os.rename": ((0, 1), True),
    "os.symlink": ((0, 1), True),
    "os.link": ((0, 1), True),
    "shutil.copyfile": ((1,), True),
    "shutil.copytree": ((1,), True),
    "shutil.move": ((0, 1), True),
    "shutil.rmtree": ((0,), True),
}


class SandboxRefused(PermissionError):
    pass


_refuses: Callable[[object, bool], bool] | None = None  # set by guard(): whether a path is out of bounds


def refused_in(record: object) -> str | None:
    """The first absolute path in record (a dict, list or string, as an undo record holds them) that the guard keeps
    out, or None (always None without a guard). A refused read looks like a missing file to whoever asked, so a caller
    that is about to say "it is gone" asks here first and can say why instead."""
    if _refuses is None:
        return None
    if isinstance(record, dict):
        record = list(record.values())
    if isinstance(record, list):
        return next((p for p in (refused_in(v) for v in record) if p), None)
    if isinstance(record, str) and os.path.isabs(record) and _refuses(record, False):
        return record
    return None


def _norm(path: object) -> str | None:
    if path is None or isinstance(path, int):
        return None  # a file descriptor: it was checked when it was opened
    try:
        text = os.fsdecode(path)  # type: ignore[arg-type]
    except TypeError:
        return None
    return os.path.normcase(os.path.abspath(text.removeprefix("\\\\?\\")))


def _under(p: str, roots: Iterable[str]) -> bool:
    return any(p == r or p.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def guard(protect: Iterable[str | Path], allowed: Iterable[str | Path], readable: Iterable[str | Path] = ()) -> None:
    """Refuse, for the rest of the process, what this module's docstring says; readable folders are read, never
    changed, even inside a protected one. Cannot be undone."""

    def norm(paths: Iterable[str | Path]) -> list[str]:
        return [n for n in (_norm(p) for p in paths if str(p).strip()) if n]

    protect_n, allowed_n, readable_n = norm(protect), norm(allowed), norm(readable)

    def refuses(path: object, writes: bool) -> bool:
        p = _norm(path)
        if p is None or _under(p, allowed_n):
            return False
        if not writes and (_under(p, readable_n) or not _under(p, protect_n)):
            return False
        return not (p.startswith("\\\\.\\pipe\\") or "__pycache__" in p)

    def check(path: object, writes: bool) -> None:
        if not refuses(path, writes):
            return
        raise SandboxRefused(f"Bayle Dev keeps out of your real folders: {os.fsdecode(path)}")  # type: ignore[arg-type]

    def hook(event: str, args: tuple) -> None:
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None))[:3]
            writes = any(c in (mode or "") for c in "wax+") or bool(isinstance(flags, int) and flags & _WRITE_FLAGS)
            check(path, writes)
        elif event in _EVENTS:
            where, writes = _EVENTS[event]
            for i in where:
                if i < len(args):
                    check(args[i], writes)

    global _refuses
    _refuses = refuses
    sys.addaudithook(hook)


def guard_from_env(data: Path, program: Path) -> bool:
    """guard() when the desktop shell asked for it (BAYLE_PROTECT set). The data folder and the temp folder are allowed;
    the program and Python's own folders are read only. Returns whether it is on."""
    protect = [p for p in os.environ.get(PROTECT_ENV, "").split(os.pathsep) if p.strip()]
    if not protect:
        return False
    extra = [p for p in os.environ.get(ALLOW_ENV, "").split(os.pathsep) if p.strip()]
    python = [sys.prefix, sys.base_prefix, sys.exec_prefix, *(p for p in sys.path if p and os.path.isdir(p))]
    guard(protect, [data, tempfile.gettempdir(), *extra], [program, *python])
    return True
