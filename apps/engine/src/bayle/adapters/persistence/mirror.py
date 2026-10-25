"""The database's copy of record files that protect other files (backup notes and keep flags, the save library's
library.json, a profile's versions.json): a derived index, not the truth (spec 8.8, stage 3).

While the update watchdog can restore a build that only reads and writes those files, the files stay authoritative
and keep their exact formats. A write is: the file first (atomically, by its own writer), then record() here, which
stores the SHA-256 of the file's bytes and its text in its own transaction. A failure here is logged once and
ignored; the file already holds the truth. A row that disagrees with its file (an interrupted database write, or an
older build that changed the file) is simply repaired from the file by the next record() or sync(): the file wins.

The one exception is the keep flag, which errs toward safety: keep_doubt() is true when the row says keep while the
file's bytes are not what the row was made from, and protection then keeps the backup (and the row is left alone, so
the doubt stays until the new build sets the flag itself). An uncertain keep flag must prevent pruning.

PROTECTIVE_SCHEMA is the version of this behaviour a release supports; the end of the compatibility window is checked
against it for every executable the watchdog can restore (nothing ends it yet: the files are still always written).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete

from bayle.adapters.persistence.db import Database
from bayle.adapters.persistence.models import RecordMirrorRow, utc_now
from bayle.modules.saves.ports import BACKUP_NOTE

PROTECTIVE_SCHEMA = 1


def key_of(path: Path | str) -> str:
    return os.path.normcase(str(path))


def fingerprint(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Mirror:
    def __init__(self, db: Database, log: Callable[[str], None] = lambda line: None):
        self.db = db
        self.log = log
        self._warned = False

    def _failed(self, e: Exception) -> None:
        if not self._warned:
            self._warned = True
            self.log(f"warning: the record index in the database failed ({e}); the files are what counts")

    def record(self, kind: str, path: Path) -> None:
        """The file at path was just written: mirror it (a missing file removes its row). Never raises."""
        try:
            try:
                data = Path(path).read_bytes()
            except FileNotFoundError:
                return self.forget(kind, path)
            with self.db.unit_of_work() as s:
                s.merge(
                    RecordMirrorRow(
                        kind=kind,
                        key=key_of(path),
                        fingerprint=fingerprint(data),
                        payload=data.decode("utf-8", "replace"),
                        updated_at=utc_now(),
                    )
                )
        except Exception as e:
            self._failed(e)

    sync = record  # repairing a row from its file is the same act

    def forget(self, kind: str, path: Path) -> None:
        try:
            with self.db.unit_of_work() as s:
                s.execute(
                    delete(RecordMirrorRow).where(RecordMirrorRow.kind == kind, RecordMirrorRow.key == key_of(path))
                )
        except Exception as e:
            self._failed(e)

    def row(self, kind: str, path: Path) -> RecordMirrorRow | None:
        with self.db.unit_of_work() as s:
            row = s.get(RecordMirrorRow, (kind, key_of(path)))
            if row is not None:
                s.expunge(row)
            return row

    def keep_doubt(self, path: Path) -> bool:
        """The row of a backup's note says keep, and the note's bytes are not what it was made from (or are gone or
        unreadable now): the keep flag is uncertain, so the backup must not be pruned. False on any failure here
        (the file's own answer then stands) and when the row says nothing about keeping."""
        try:
            row = self.row(BACKUP_NOTE, path)
            if row is None:
                return False
            try:
                kept = json.loads(row.payload).get("keep") is True
            except ValueError, AttributeError:
                return True  # a row that can't be read may have said keep
            if not kept:
                return False
            try:
                same = fingerprint(Path(path).read_bytes()) == row.fingerprint
            except OSError:
                return True
            return not same
        except Exception as e:
            self._failed(e)
            return False
