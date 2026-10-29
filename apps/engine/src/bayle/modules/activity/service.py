"""The Activity application interface: what the jobs index says (every job, its log and the other programs' output
kept with it, the failures since Activity was last looked at) and taking a job back, with the same rules for every
client. It returns records, structured logs and OperationError codes, never wording: the Qt page words them
(ui/pages/activity/presenter.py), the HTTP layer hands them on. The records come from jobs.jsonl and the activity log
it is handed (the Engine's), never the runtime's slot."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from bayle.adapters.filesystem import trash
from bayle.adapters.system import logging as run_logging
from bayle.adapters.system import sandbox
from bayle.errors import Cancelled, OperationError
from bayle.modules.games.locate import Locations
from bayle.modules.mods import kinds
from bayle.modules.mods import models as mod_models
from bayle.modules.mods import undo as mod_undo
from bayle.modules.saves import service as _saves_service  # noqa: F401  registers the save-restore Undo
from bayle.modules.settings.service import load_settings, save_settings
from bayle.work.jobs import JobManager
from bayle.work.runner import run_job_result

FAILED = ("failed", "interrupted")


@dataclass(frozen=True)
class JobLog:
    """A job's own log (entries: time, level, source, text) or an attachment (text), as read."""

    entries: tuple[dict, ...] = ()
    text: str = ""
    attachment: bool = False
    cut: bool = False  # only the end of a long file was read
    missing: bool = False  # the file is gone


class ActivityService:
    """Activity for one engine: jobs is its JobManager (the writing job's gates), store its activity log (None: the
    records are in jobs.jsonl only), locations the game an undo acts on. The reads at the top are the seam a test
    replaces; the rules below them are not."""

    def __init__(
        self, jobs: JobManager, store: run_logging.JobStore | None, locations: Callable[[], Locations]
    ) -> None:
        self._jobs, self._store, self._locations = jobs, store, locations

    # ---- reads
    def jobs(self) -> list[dict]:
        """Every job, newest first; one that can be taken back also names its button (undo_label: Restore, Roll back...)."""
        return [
            {**r, "undo_label": mod_undo.label(r["undo"])} if r.get("undo") else r
            for r in run_logging.read_jobs_from(self._store)
        ]

    def undo_available(self, undo: dict) -> bool:
        return mod_undo.available(undo)

    def in_trash(self, path: object) -> bool:
        return trash.exists(path)  # type: ignore[arg-type]

    def read_log(self, name: str) -> dict:
        return run_logging.read_job_log(name)

    def read_attachment(self, name: str) -> dict:
        return run_logging.read_attachment(name)

    def log_file(self, name: str) -> Path | None:
        path = run_logging.job_file(name)
        return path if path is not None and path.is_file() else None

    def seen_at(self) -> float:
        return float(load_settings().activity_seen or 0.0)

    # ---- one job
    def record(self, job_id: str) -> dict | None:
        """The job's record now, None when it is no longer listed."""
        return next((r for r in self.jobs() if str(r.get("id")) == job_id), None)

    def log(self, job_id: str, source: str = "") -> JobLog:
        """The job's own log, or the attachment named source (another program's output kept with it)."""
        main = (self.record(job_id) or {}).get("log") or ""
        source = source or main
        if source == main:
            got = self.read_log(source)
            return JobLog(entries=tuple(got["entries"]), cut=bool(got.get("cut")), missing=bool(got["missing"]))
        got = self.read_attachment(source)
        return JobLog(text=got["text"], attachment=True, cut=bool(got.get("cut")), missing=bool(got["missing"]))

    def log_path(self, job_id: str, source: str = "") -> Path | None:
        """The file behind the job's log (or the attachment source), for Open file; None when it is gone."""
        return self.log_file(source or (self.record(job_id) or {}).get("log") or "")

    # ---- what is new
    def unseen(self) -> int:
        """Failed or interrupted jobs since Activity was last looked at."""
        return len(run_logging.unseen_failures(self.seen_at(), self.jobs()))

    def mark_seen(self) -> float:
        """Activity was looked at: failures so far are no longer new. Returns the time written."""
        now = time.time()
        save_settings(activity_seen=now)
        return now

    # ---- taking a job back
    def check_undo(self, job_id: str) -> dict:
        """The job's record when it can be taken back now. Raises OperationError: not_found (no longer listed), busy
        (a writing job runs), gone (what it needs is gone), game_running (a rebuild's files are in use)."""
        rec = self.record(job_id)
        if rec is None:
            raise OperationError("not_found", "That job is no longer listed.", {"job_id": job_id})
        undo = rec.get("undo") or {}
        if self._jobs.busy:
            raise OperationError("busy", "Another operation is running.", {"job_id": job_id})
        if not self.undo_available(undo):
            if kept := sandbox.refused_in(undo):  # Bayle Dev: not gone, out of bounds
                raise OperationError(
                    "sandboxed", f"Bayle Dev keeps out of your real folders: {kept}", {"job_id": job_id}
                )
            raise OperationError("gone", "It cannot be taken back any more.", {"job_id": job_id})
        if undo.get("type") == "rebuild" and self._jobs.game_running:
            raise OperationError("game_running", "The game is running.", {"job_id": job_id})
        return rec

    def undo(self, job_id: str, expect: dict, title: str = "") -> str:
        """Take the job back as a writing job of its own; returns the job id (its result: {"said": what was done}).
        expect: the undo record the client confirmed. Raises what check_undo raises, stale when the record changed
        since the client read it, and the job manager's Busy (another writing job, the game running)."""
        rec = self.check_undo(job_id)
        u = dict(rec.get("undo") or {})
        if u != expect:
            raise OperationError("stale", "Things changed since you were asked. Ask again.", {"job_id": job_id})
        name = "the rebuild" if u.get("type") == "rebuild" else u.get("name") or "it"
        loc, title = self._locations(), title or log_title(u, name)
        store = self._store
        return self._jobs.start(lambda _ctx: {"said": run_undo(u, job_id, name, loc, title, store)}, title=title)


def log_title(u: dict, name: str) -> str:
    """The name the undo's own log and jobs-index record carry."""
    kind = u.get("type")
    if kind == "rebuild":
        return f"launcher: {'redo' if u.get('redo') else 'undo'} the rebuild"
    if kind in kinds.OPERATIONS or kind in kinds.OVERHAUL:
        return f"launcher: {mod_undo.label(u).lower()} {name}"
    if kind in ("rename", "profile-rename"):
        return f"launcher: undo the rename of {name}"
    if kind == "profile-duplicate":
        return f"launcher: undo the copy {name}"
    if kind == "profile-move-in":
        return f"launcher: undo the move of {name}"
    if kind in ("folder-rename", "folder-split"):
        return f"launcher: undo the folder change of {name}"
    if kind == "dll-folders":
        return f"launcher: undo the DLL folders in {name}"
    if kind in ("layout-relocate", "layout-rename"):
        return f"launcher: undo the change to the profiles folders ({name})"
    return f"launcher: restore {name}"


def run_undo(u: dict, job_id: str, name: str, loc: Locations, title: str, store: run_logging.JobStore | None) -> str:
    """Take a job back as a logged job of its own (its log and index record as before) and record that it was.
    Returns what was done, in words. Raises OperationError when it could not be, Cancelled when it was stopped."""

    def job(_launch, loc: Locations) -> str:
        run_logging.start_log(log_title(u, name), loc.game.key)
        try:
            said = mod_undo.run(u, run_logging.log, loc=loc)
        except (mod_models.UndoError, OSError) as e:
            raise OperationError("undo_failed", str(e)) from e
        if job_id:
            run_logging.mark_undone(job_id, store)
        if u.get("type") == "rebuild":  # the same swap, the other way
            run_logging.set_undo({**u, "redo": not u.get("redo")})
        run_logging.log(f"done: {said}")
        return said

    done = run_job_result(job, None, loc, title)
    if done.state == "done":
        return done.result
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError.from_info(done.error)
