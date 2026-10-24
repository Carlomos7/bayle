"""The rebuild run log in the database (it was merges.json): the last runs of the merged-mods rebuild per profile.

merges.json stays authoritative while the update watchdog can restore a build that only knows the file (spec 8.8,
stage 3). It keeps its exact format and is written first, atomically; the row follows in its own transaction and
stores the SHA-256 of the file's entry. Readers take the answer from the file; sync() re-reads it and repairs the row
when they disagree (an interrupted database write, or an older build that rewrote the file). Every failure here is
logged once and ignored: the file already holds the truth.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import delete, select

from bayle.storage.db import Database
from bayle.storage.models import ImportState, RebuildRun

SOURCE = "merges.json"
KEEP_PER_PROFILE = 20


def fingerprint(entry: dict) -> str:
    return hashlib.sha256(json.dumps(entry, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _key(profile: str, entry: dict) -> str:
    return f"{profile}|{entry.get('when')}"


class RebuildRuns:
    def __init__(self, db: Database, log: Callable[[str], None] = lambda line: None):
        self.db = db
        self.log = log
        self._warned = False

    def _failed(self, e: Exception) -> None:
        if not self._warned:
            self._warned = True
            self.log(f"warning: the rebuild run log in the database failed ({e}); merges.json is what counts")

    def record(self, profile: str, entry: dict) -> None:
        """Mirror one entry just written to the file (profile: normalised). Never raises."""
        try:
            with self.db.unit_of_work() as s:
                self._put(s, profile, entry)
        except Exception as e:
            self._failed(e)

    def sync(self, profile: str, entry: dict | None) -> None:
        """The file's current entry for a profile is the truth: make its row match. Never raises."""
        if not entry or "when" not in entry:
            return
        try:
            with self.db.unit_of_work() as s:
                self._put_if_different(s, profile, entry)
        except Exception as e:
            self._failed(e)

    def _put_if_different(self, s, profile: str, entry: dict) -> None:
        row = s.scalar(select(RebuildRun).where(RebuildRun.import_key == _key(profile, entry)))
        if row is None or row.fingerprint != fingerprint(entry):
            self._put(s, profile, entry)

    def _put(self, s, profile: str, entry: dict) -> None:
        row = s.scalar(select(RebuildRun).where(RebuildRun.import_key == _key(profile, entry)))
        if row is None:
            row = RebuildRun(import_key=_key(profile, entry), profile=profile)
            s.add(row)
        row.ran_at = datetime.datetime.fromtimestamp(float(entry.get("when") or 0), datetime.UTC)
        row.ok = bool(entry.get("ok"))
        row.message = str(entry.get("message") or "")
        row.fingerprint = fingerprint(entry)
        s.flush()
        old = s.scalars(
            select(RebuildRun.id).where(RebuildRun.profile == profile).order_by(RebuildRun.ran_at.desc())
        ).all()[KEEP_PER_PROFILE:]
        if old:
            s.execute(delete(RebuildRun).where(RebuildRun.id.in_(old)))

    def import_file(self, path: Path) -> bool:
        """Mirror every profile's entry of merges.json (idempotent; an older build rewrites the file whole, so it is
        re-read whenever it is imported). Returns whether the log now matches the file."""
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            data = b"{}"
        try:
            runs = json.loads(data.decode("utf-8"))
        except ValueError as e:
            self.log(f"warning: {path} can't be read ({e}); it is left as it is and not imported")
            return False
        runs = runs if isinstance(runs, dict) else {}
        with self.db.unit_of_work() as s:
            for profile, entry in runs.items():
                if isinstance(entry, dict) and "when" in entry:
                    self._put_if_different(s, str(profile), entry)
            state = s.merge(
                ImportState(source=SOURCE, content_sha256=hashlib.sha256(data).hexdigest(), position=len(data))
            )
            state.verified_at = datetime.datetime.now(datetime.UTC)
        return True
