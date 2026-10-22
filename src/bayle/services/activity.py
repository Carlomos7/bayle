"""What the Activity page reads from disk and the one job it runs (taking a job back), without Qt. The presenter
(views.activity) is told these facts instead of reading them; the session's activity operations call this."""

from __future__ import annotations

import time
from pathlib import Path

from bayle.game.locate import Locations
from bayle.mods import undo as mod_undo
from bayle.platform import logging as run_logging
from bayle.platform import trash
from bayle.services import saves as _saves_service  # noqa: F401  registers the save-restore Undo
from bayle.services.errors import Cancelled, OperationError
from bayle.services.jobs import run_job_result
from bayle.services.settings import load_settings, save_settings


class ActivityService:
    """The views.activity.ActivityFacts, read from the jobs index, the job logs and the trash."""

    def jobs(self) -> list[dict]:
        return run_logging.read_jobs()

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

    def unseen(self) -> int:
        """Failed or interrupted jobs since Activity was last looked at."""
        return len(run_logging.unseen_failures(float(load_settings().activity_seen or 0.0)))

    def mark_seen(self) -> float:
        """Activity was looked at: failures so far are no longer new. Returns the time written."""
        now = time.time()
        save_settings(activity_seen=now)
        return now


def log_title(u: dict, name: str) -> str:
    """The name the undo's own log and jobs-index record carry."""
    kind = u.get("type")
    if kind == "rebuild":
        return f"launcher: {'redo' if u.get('redo') else 'undo'} the rebuild"
    if kind in mod_undo.OPERATIONS or kind in mod_undo.OVERHAUL:
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


def undo(u: dict, job_id: str, name: str, loc: Locations, title: str) -> str:
    """Take a job back as a logged job of its own (its log and index record as before) and record that it was.
    Returns what was done, in words. Raises OperationError when it could not be, Cancelled when it was stopped."""

    def job(_launch, loc: Locations) -> str:
        run_logging.start_log(log_title(u, name), loc.game.key)
        try:
            said = mod_undo.run(u, run_logging.log, loc=loc)
        except (mod_undo.UndoError, OSError) as e:
            raise OperationError("undo_failed", str(e)) from e
        if job_id:
            run_logging.mark_undone(job_id)
        if u.get("type") == "rebuild":  # the same swap, the other way
            run_logging.set_undo({**u, "redo": not u.get("redo")})
        run_logging.log(f"done: {said}")
        return said

    done = run_job_result(job, None, loc, title)
    if done.state == "done":
        return done.result
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError(done.error.code if done.error else "failed", done.error.message if done.error else "Failed.")
