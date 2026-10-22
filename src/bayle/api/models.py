from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1"  # major of the /v1 contract; additive changes only within it


class Health(BaseModel):
    app_version: str
    contract_version: str
    ready: bool = True


class Problem(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


# ---- events: the envelope of every SSE message is {seq, job_id, type, data}; `type` picks the data shape.
# Declared here so the OpenAPI snapshot (and the generated client) carry the union. Push types (no job_id) tell a client
# what changed outside any job: game.state, invalidated (re-read these pages), notice (say this), navigate.
class _Envelope(BaseModel):
    seq: int
    job_id: str | None = None


class ErrorData(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class StartedData(BaseModel):
    title: str


class ProgressData(BaseModel):
    done: float | None = None
    total: float | None = None
    label: str = ""


class LogData(BaseModel):
    text: str
    level: str


class FinishedData(BaseModel):
    result: Any = None
    undo: dict[str, Any] | None = None


class FailedData(BaseModel):
    error: ErrorData
    unexpected: bool = False


class ResyncData(BaseModel):
    requested: int  # the Last-Event-ID the client sent
    oldest: int  # the oldest seq still buffered
    seq: int  # the newest seq


class GameStateData(BaseModel):
    game: str  # the game in use
    running: bool
    steam_problem: bool = False  # Steam runs but is not signed in
    dead_shells: int = 0  # leftover game processes


class InvalidatedData(BaseModel):
    what: list[str]  # shell | pages | updates | game: read those again (GET /v1/pages/...)


class NoticeData(BaseModel):
    text: str
    error: bool = False
    details: bool = False  # the job log has more


class NavigateData(BaseModel):
    page: str


class StartedEvent(_Envelope):
    type: Literal["started"] = "started"
    data: StartedData


class ProgressEvent(_Envelope):
    type: Literal["progress"] = "progress"
    data: ProgressData


class LogEvent(_Envelope):
    type: Literal["log"] = "log"
    data: LogData


class PromptEvent(_Envelope):
    type: Literal["prompt"] = "prompt"
    data: dict[str, Any]


class FinishedEvent(_Envelope):
    type: Literal["finished"] = "finished"
    data: FinishedData


class FailedEvent(_Envelope):
    type: Literal["failed"] = "failed"
    data: FailedData


class CancelledEvent(_Envelope):
    type: Literal["cancelled"] = "cancelled"
    data: FailedData


class ResyncEvent(_Envelope):
    type: Literal["resync"] = "resync"  # refetch your state (GET /v1/jobs/{id}...), then continue from this seq
    data: ResyncData


class GameStateEvent(_Envelope):
    type: Literal["game.state"] = "game.state"
    data: GameStateData


class InvalidatedEvent(_Envelope):
    type: Literal["invalidated"] = "invalidated"
    data: InvalidatedData


class NoticeEvent(_Envelope):
    type: Literal["notice"] = "notice"
    data: NoticeData


class NavigateEvent(_Envelope):
    type: Literal["navigate"] = "navigate"
    data: NavigateData


ApiEvent = Annotated[
    StartedEvent
    | ProgressEvent
    | LogEvent
    | PromptEvent
    | FinishedEvent
    | FailedEvent
    | CancelledEvent
    | ResyncEvent
    | GameStateEvent
    | InvalidatedEvent
    | NoticeEvent
    | NavigateEvent,
    Field(discriminator="type"),
]


class Job(BaseModel):
    id: str
    title: str
    state: Literal["running", "done", "failed", "cancelled"]
    progress: ProgressData | None = None
    result: Any = None
    error: ErrorData | None = None
    undo: dict[str, Any] | None = None


# ---- the generic routes (api/ops.py): what an operation of each kind answers with
class JobStarted(BaseModel):
    job_id: str  # follow it on /v1/events or GET /v1/jobs/{job_id}


class PlanOffer(BaseModel):
    """A plan operation's answer: a question to show (prompt: kind confirm | pick | choose, plus its words) and the
    plan_id to answer on POST /v1/plans/{plan_id}; or, with plan_id null, a refusal (kind refusal: title and body)."""

    plan_id: str | None = None
    prompt: dict[str, Any]


class PlanAnswer(BaseModel):
    ok: bool = True  # false = cancelled: nothing runs
    option: bool = False
    choice: str = ""
    ticked: list[int] = []


class PlanExecuted(BaseModel):
    job_id: str | None = None  # the job the plan started (null when cancelled)


class PromptAnswer(BaseModel):
    choice: str  # the key of one of the prompt's choices


class PromptAnswered(BaseModel):
    ok: bool = True
