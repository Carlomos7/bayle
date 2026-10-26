"""The app-data version marker (<data>/data-version.json). Today's format is the baseline, version 1: a folder
without the marker gets it and nothing else changes. A marker newer than this build, or one that can't be read, is
refused with nothing touched. Versioned steps come with the first stable release (the step runner is in git history,
commit 14ba4ef9)."""

from __future__ import annotations

import datetime
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from bayle.adapters.filesystem import files
from bayle.adapters.persistence import db as storage_db
from bayle.adapters.system import logging as run_logging

MARKER = "data-version.json"
CURRENT_VERSION = 1


class MigrationError(storage_db.MigrationFailed):
    """The data folder was refused; .code says why, the message says what to do."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def write_json(path: Path, obj: Any) -> None:
    """Write through adapters.filesystem.files.durable_write: a temp file in the same folder, fsynced, renamed into
    place, the folder fsynced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # os.linesep keeps the bytes the old text-mode write gave (CRLF on Windows); json escapes newlines in values.
    files.durable_write(path, json.dumps(obj, indent=1).replace("\n", os.linesep))


def _read_version(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        version = json.loads(path.read_text(encoding="utf-8"))["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("no version number")
        return version
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise MigrationError(
            "corrupt-marker",
            f"{path} can't be read ({e}). Bayle left your data alone. To repair it, restore {MARKER} from a "
            f"backup, or delete it to start from today's format (version 1).",
        ) from e


def migrate(
    data: Path,
    app_version: str,
    *,
    recover_journals: Callable[[], list[str]] = lambda: [],
    open_db: Callable[[], Any] | None = None,
) -> Any:
    """Check the marker, resolve the unfinished operations, stamp version 1 on a folder without a marker, return
    open_db()'s result (None without it). Raises MigrationError when the marker is newer or unreadable."""
    version = _read_version(data / MARKER)
    if version is not None and version > CURRENT_VERSION:
        raise MigrationError(
            "newer",
            f"This data was written by a newer Bayle (data version {version}, this build knows {CURRENT_VERSION}). "
            "Bayle left it alone: install the newer version again.",
        )
    for line in recover_journals():
        run_logging.log(f"recovery: {line}")
    if version is None:
        now = datetime.datetime.now(datetime.UTC).isoformat()
        write_json(data / MARKER, {"version": CURRENT_VERSION, "app": app_version, "at": now})
    return open_db() if open_db else None
