"""The Activity operations for the HTTP layer, each handed straight to the session's ActivityService
(services.activity): the jobs, a job's log and file, the unseen count, "seen", and Undo. Temporary: the Qt page calls
the service itself, and a future API is built on it the same way. No wording here; the client words what it gets."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bayle.errors import OperationError
from bayle.services.activity import ActivityService
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry


class JobRef(Params):
    job_id: str


class LogParams(JobRef):
    source: str = ""  # an attachment's name; "" is the job's own log


class TakeBack(JobRef):
    expect: dict[str, Any]  # the undo record the client confirmed (refused as stale when it changed)


class ActivityJobs(BaseModel):
    jobs: list[dict[str, Any]]
    unseen: int


class LogView(Result):
    entries: list[dict[str, Any]]
    text: str
    attachment: bool
    cut: bool
    missing: bool


class LogFile(Result):
    path: str | None  # None when the file is gone


class Unseen(Result):
    count: int


class Seen(Result):
    at: float


class Started(Result):
    job_id: str


def _none() -> ActivityService:
    raise OperationError("no_activity", "This session has no Activity.")


def _activity(session: Session) -> ActivityService:
    return session.service("activity", _none)


@registry.page("activity", view=ActivityJobs)
def snapshot(session: Session) -> ActivityJobs:
    a = _activity(session)
    return ActivityJobs(jobs=a.jobs(), unseen=a.unseen())


@operation("activity.log", params=LogParams, result=LogView)
def log(call: Call, p: LogParams) -> LogView:
    got = _activity(call.session).log(p.job_id, p.source)
    return LogView(
        entries=list(got.entries), text=got.text, attachment=got.attachment, cut=got.cut, missing=got.missing
    )


@operation("activity.log_file", params=LogParams, result=LogFile)
def log_file(call: Call, p: LogParams) -> LogFile:
    path = _activity(call.session).log_path(p.job_id, p.source)
    return LogFile(path=None if path is None else str(path))


@operation("activity.unseen", result=Unseen)
def unseen(call: Call, p: NoParams) -> Unseen:
    return Unseen(count=_activity(call.session).unseen())


@operation("activity.mark_seen", result=Seen, kind="command", writes=True)
def mark_seen(call: Call, p: NoParams) -> Seen:
    return Seen(at=_activity(call.session).mark_seen())


@operation("activity.undo", params=TakeBack, result=Started, kind="command", writes=True)
def undo(call: Call, p: TakeBack) -> Started:
    """Start taking a job back (its result: {"said": ...}); refusals are OperationError codes (services.activity)."""
    return Started(job_id=_activity(call.session).undo(p.job_id, p.expect))
