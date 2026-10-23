"""The Activity page's operations: its snapshot, a job's log, copy and file, the unseen count, "seen", and Undo."""

from __future__ import annotations

import dataclasses
import datetime

from pydantic import BaseModel

from bayle.errors import OperationError
from bayle.platform.text import tr
from bayle.services.activity import ActivityService
from bayle.services.activity import undo as undo_job
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry
from bayle.views.activity import ActivityPresenter, ActivityState, LogText, Refusal
from bayle.work.prompts import Proposal


class ActivityScope(Params):
    game: str = ""
    group: str = ""
    failed_only: bool = False


class JobRef(Params):
    job_id: str


class LogParams(JobRef):
    source: str = ""  # an attachment's name; "" is the job's own log
    detail: bool = False


class CopyParams(LogParams):
    for_support: bool = False  # user name and Steam IDs masked


class LogRow(BaseModel):
    time: str
    level: str
    text: str


class LogView(Result):
    rows: list[LogRow]
    plain: str
    note: str = ""
    missing: bool = False


class CopyText(Result):
    text: str


class LogFile(Result):
    path: str | None  # None when the file is gone


class Unseen(Result):
    count: int


class Seen(Result):
    at: float


class UndoResult(Result):
    said: str


def _facts(session: Session) -> ActivityService:
    return session.service("activity", ActivityService)


def _presenter(session: Session) -> ActivityPresenter:
    return ActivityPresenter(_facts(session), session.service("clock", lambda: datetime.datetime.now))


def _view(log: LogText) -> LogView:
    return LogView(
        rows=[LogRow(time=t, level=lvl, text=x) for t, lvl, x in log.rows],
        plain=log.plain,
        note=log.note,
        missing=log.missing,
    )


@registry.page("activity", scope=ActivityScope, view=ActivityState)
def snapshot(session: Session, game: str = "", group: str = "", failed_only: bool = False) -> ActivityState:
    state = _presenter(session).refresh(game, group, failed_only)
    return dataclasses.replace(state, unseen=_facts(session).unseen())


@operation("activity.log", params=LogParams, result=LogView)
def log(call: Call, p: LogParams) -> LogView:
    return _view(_presenter(call.session).log(p.job_id, p.source, p.detail))


@operation("activity.copy", params=CopyParams, result=CopyText)
def copy(call: Call, p: CopyParams) -> CopyText:
    pres = _presenter(call.session)
    return CopyText(text=pres.copy_text(pres.log(p.job_id, p.source, p.detail), p.for_support))


@operation("activity.log_file", params=LogParams, result=LogFile)
def log_file(call: Call, p: LogParams) -> LogFile:
    pres = _presenter(call.session)
    rec = pres.record(p.job_id) or {}
    path = pres.log_path(p.source or rec.get("log") or "")
    return LogFile(path=None if path is None else str(path))


@operation("activity.unseen", result=Unseen)
def unseen(call: Call, p: NoParams) -> Unseen:
    return Unseen(count=_facts(call.session).unseen())


@operation("activity.mark_seen", result=Seen, kind="command", writes=True)
def mark_seen(call: Call, p: NoParams) -> Seen:
    return Seen(at=_facts(call.session).mark_seen())


@operation("activity.undo", params=JobRef, result=UndoResult, kind="plan", writes=True)
def undo(call: Call, p: JobRef) -> Proposal | Refusal:
    """Offer to take a job back; answering the plan starts the undo as a job (a writing one) whose result is UndoResult."""
    session = call.session
    pres = _presenter(session)
    rec = pres.record(p.job_id)
    if rec is None:
        raise OperationError("not_found", tr("That job is no longer listed."), {"job_id": p.job_id})
    plan = pres.undo_plan(rec, busy=session.jobs.busy, game_running=session.jobs.game_running)
    if isinstance(plan, Refusal):
        return plan

    def run(_answer) -> str:
        loc = session.locations()
        return session.start(
            lambda _ctx: UndoResult(said=undo_job(plan.undo, plan.job_id, plan.name, loc, plan.progress)),
            title=plan.progress,
        )

    return Proposal(plan.confirm, run, stale=lambda: (pres.record(p.job_id) or {}).get("undo"))
