"""Activity over HTTP: the jobs, a job's log and file, the unseen count, "seen", and Undo, each handed straight to the
engine's ActivityService (modules.activity.service). No wording here; the client words what it gets.

The shape every feature router follows: GET /v1/<feature> is the page's facts; POST /v1/<feature>/<op> takes the
op's params as its body and returns its result (a long write returns {"job_id"}, its end comes on /v1/events)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import NoParams, Params, Result
from bayle.modules.activity.service import ActivityService

router = APIRouter(prefix="/activity", tags=["activity"])
Activity = Annotated[ActivityService, Depends(service("activity"))]


class JobRef(Params):
    job_id: str


class LogParams(JobRef):
    source: str = ""  # an attachment's name; "" is the job's own log


class TakeBack(JobRef):
    expect: dict[str, Any]  # the undo record the client confirmed (refused as stale when it changed)


class ActivityJobs(Result):
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


@router.get("", name="activity")
def page(a: Activity, _q: Annotated[NoParams, Query()]) -> ActivityJobs:
    return ActivityJobs(jobs=a.jobs(), unseen=a.unseen())


@router.post("/log", name="activity_log")
def log(a: Activity, p: LogParams) -> LogView:
    got = a.log(p.job_id, p.source)
    return LogView(
        entries=list(got.entries), text=got.text, attachment=got.attachment, cut=got.cut, missing=got.missing
    )


@router.post("/log_file", name="activity_log_file")
def log_file(a: Activity, p: LogParams) -> LogFile:
    path = a.log_path(p.job_id, p.source)
    return LogFile(path=None if path is None else str(path))


@router.post("/unseen", name="activity_unseen")
def unseen(a: Activity) -> Unseen:
    return Unseen(count=a.unseen())


@router.post("/mark_seen", name="activity_mark_seen")
def mark_seen(a: Activity) -> Seen:
    return Seen(at=a.mark_seen())


@router.post("/undo", name="activity_undo")
def undo(a: Activity, p: TakeBack) -> Started:
    """Start taking a job back (its result: {"said": ...}); refusals are OperationError codes
    (modules.activity.service)."""
    return Started(job_id=a.undo(p.job_id, p.expect))
