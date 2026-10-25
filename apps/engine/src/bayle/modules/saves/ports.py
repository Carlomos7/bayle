"""What the saves feature needs from the database's record index (storage.mirror implements it): a derived copy of
the record files that protect other files. Unbound (None: storage is off), the files alone work: record and forget
do nothing and keep_doubt is False. The runtime binds the index (bayle.runtime.bootstrap)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

BACKUP_NOTE, LIBRARY, HISTORY = "backup-note", "library", "history"


class RecordIndex(Protocol):
    def record(self, kind: str, path: Path) -> None: ...

    def forget(self, kind: str, path: Path) -> None: ...

    def keep_doubt(self, path: Path) -> bool: ...


_CURRENT: RecordIndex | None = None  # bound by bayle.runtime.bootstrap only


def record(kind: str, path: Path) -> None:
    if _CURRENT is not None:
        _CURRENT.record(kind, path)


def forget(kind: str, path: Path) -> None:
    if _CURRENT is not None:
        _CURRENT.forget(kind, path)


def keep_doubt(path: Path) -> bool:
    return _CURRENT is not None and _CURRENT.keep_doubt(path)
