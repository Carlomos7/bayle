"""Jobs and the event stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent

from bayle.api.deps import JobsDep
from bayle.api.models import ApiEvent, ErrorData, Job, ProgressData
from bayle.services.errors import OperationError
from bayle.session import JobSnapshot, Subscription

MAX_SUBSCRIBERS = 3

router = APIRouter()


def _job(s: JobSnapshot) -> Job:
    return Job(
        id=s.id,
        title=s.title,
        state=s.state,  # type: ignore[arg-type]
        progress=ProgressData(**s.progress) if s.progress else None,
        result=s.result,
        error=ErrorData(code=s.error.code, message=s.error.message, details=s.error.details) if s.error else None,
        undo=s.undo,
    )


def _snapshot(jobs: JobsDep, job_id: str) -> JobSnapshot:
    snap = jobs.get(job_id)
    if snap is None:
        raise OperationError("not_found", f"No job {job_id}.")
    return snap


@router.get("/jobs/{job_id}")
async def get_job(jobs: JobsDep, job_id: str) -> Job:
    return _job(_snapshot(jobs, job_id))


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(jobs: JobsDep, job_id: str) -> Job:
    """Ask the job to stop (it ends with a `cancelled` event). Idempotent: a job that is over just reports its state."""
    _snapshot(jobs, job_id)
    jobs.cancel(job_id)
    return _job(_snapshot(jobs, job_id))


async def _subscription(
    request: Request, jobs: JobsDep, last_event_id: Annotated[int | None, Header()] = None
) -> AsyncIterator[tuple[Subscription, asyncio.Event]]:
    if jobs.bus.subscribers >= MAX_SUBSCRIBERS:
        raise OperationError("too_many_subscribers", f"At most {MAX_SUBSCRIBERS} event streams at a time.")
    loop, wake = asyncio.get_running_loop(), asyncio.Event()
    sub = jobs.bus.subscribe(last_event_id, notify=lambda: loop.call_soon_threadsafe(wake.set))
    try:
        yield sub, wake
    finally:
        sub.close()  # idempotent; the stream's own finally covers a generator that did start


@router.get("/events", response_class=EventSourceResponse)
async def events(
    stream: Annotated[tuple[Subscription, asyncio.Event], Depends(_subscription)],
) -> AsyncIterable[ApiEvent]:
    """Ordered job events. `id` is the seq, `event` the type. Reconnect with Last-Event-ID to continue."""
    sub, wake = stream
    try:
        while not sub.closed:
            wake.clear()  # before draining: a publish after the drain sets it again
            while (e := sub.get(0)) is not None:
                yield ServerSentEvent(  # pyright: ignore[reportReturnType]
                    data={"seq": e.seq, "job_id": e.job_id, "type": e.type, "data": e.data},
                    id=str(e.seq),
                    event=e.type,
                )
            await wake.wait()
    finally:
        sub.close()
