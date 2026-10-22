"""Operations: the named, typed things a client can ask the backend to do, and the Session that runs them.

An operation is a function registered with @operation(name, params=P, result=R, kind=..., writes=...). The registry is
data a client layer can walk (specs()) to build routes and clients; nothing here knows HTTP or Qt.

kind: "read" runs inline and returns its result; "job" runs on the JobManager (writes go through its busy gate, and
the model's JSON form becomes the job result) and returns the job id; "plan" runs inline and returns the plan the
client must confirm (executing it is Session.answer, served by the PlanStore of session.plans).
A read never writes: reads that used to recover or adopt things at start-up are Session.startup() steps instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from bayle.services.errors import OperationError
from bayle.session.jobs import JobContext, JobManager

Kind = Literal["read", "job", "plan"]
_KINDS = ("read", "job", "plan")


class Params(BaseModel):
    """Base of an operation's request model: unknown fields are refused, values are not changed after validation."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class Result(BaseModel):
    """Base of an operation's result model (JSON-clean fields only)."""

    model_config = ConfigDict(frozen=True)


class NoParams(Params):
    pass


@dataclass(frozen=True)
class Call:
    """What an operation is handed beside its params: the session, and the job context when it runs as a job."""

    session: Session
    job: JobContext | None = None


@dataclass(frozen=True)
class OperationSpec:
    name: str
    fn: Callable[[Call, Any], Any]
    params: type[Params]
    result: type[BaseModel]
    kind: Kind
    writes: bool

    @property
    def page(self) -> str:
        """The part of the name before the first dot ("saves.restore" -> "saves"): a client groups routes by it."""
        return self.name.split(".", 1)[0]


class OperationRegistry:
    def __init__(self) -> None:
        self._ops: dict[str, OperationSpec] = {}
        self._pages: dict[str, Callable[..., Any]] = {}

    def operation(
        self,
        name: str,
        *,
        params: type[Params] = NoParams,
        result: type[BaseModel],
        kind: Kind = "read",
        writes: bool = False,
    ) -> Callable[[Callable[[Call, Any], Any]], Callable[[Call, Any], Any]]:
        """Register fn(call, params) -> result. A duplicate name, an unknown kind, or a read that writes raises
        ValueError at once (a wiring mistake, not a runtime condition)."""
        if kind not in _KINDS:
            raise ValueError(f"operation {name}: unknown kind {kind!r}")
        if writes and kind != "job":
            raise ValueError(f"operation {name}: only a job may write (a {kind} must not)")

        def register(fn: Callable[[Call, Any], Any]) -> Callable[[Call, Any], Any]:
            if name in self._ops:
                raise ValueError(f"operation {name} is already registered")
            self._ops[name] = OperationSpec(name, fn, params, result, kind, writes)
            return fn

        return register

    def page(self, key: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register fn(session, **scope) -> view as the snapshot of page key."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            if key in self._pages:
                raise ValueError(f"page {key} is already registered")
            self._pages[key] = fn
            return fn

        return register

    def get(self, name: str) -> OperationSpec:
        try:
            return self._ops[name]
        except KeyError:
            raise OperationError("unknown_operation", f"No operation named {name}.", {"name": name}) from None

    def specs(self) -> list[OperationSpec]:
        return sorted(self._ops.values(), key=lambda s: s.name)

    def pages(self) -> list[str]:
        return sorted(self._pages)

    def snapshot_fn(self, key: str) -> Callable[..., Any]:
        try:
            return self._pages[key]
        except KeyError:
            raise OperationError("unknown_page", f"No page named {key}.", {"page": key}) from None


registry = OperationRegistry()  # the program's registry; tests build their own
operation = registry.operation


class PlanAnswers(Protocol):
    """What Session.answer needs from the plan store (session.plans.PlanStore implements it)."""

    def answer(self, token: str, answers: Mapping[str, Any]) -> Any: ...


@dataclass(frozen=True)
class StartupStep:
    """One start-up action: name, and fn() -> what it did (a list of lines, or None)."""

    name: str
    fn: Callable[[], Any]


@dataclass(frozen=True)
class StepReport:
    name: str
    ok: bool
    done: Any = None
    error: str = ""


def _invalid(name: str, e: ValidationError) -> OperationError:
    errors = [{"loc": [str(p) for p in x["loc"]], "msg": x["msg"], "type": x["type"]} for x in e.errors()]
    return OperationError("invalid_params", f"The request for {name} is not valid.", {"errors": errors})


class Session:
    def __init__(
        self,
        jobs: JobManager,
        *,
        ops: OperationRegistry | None = None,
        plans: PlanAnswers | None = None,
        startup_steps: list[StartupStep] | None = None,
    ):
        self.jobs, self.ops, self.plans = jobs, ops or registry, plans
        self._startup_steps = list(startup_steps or [])

    def snapshot(self, page: str, **scope: Any) -> Any:
        """A page's view model. Reads only."""
        return self.ops.snapshot_fn(page)(self, **scope)

    def run(self, name: str, params: Params | Mapping[str, Any] | None = None) -> Any:
        """Run operation name. A read or plan returns its validated result model; a job returns its job id (the
        result arrives on the bus and in jobs.get). Raises OperationError: unknown_operation, invalid_params, busy."""
        spec = self.ops.get(name)
        try:
            raw = params.model_dump() if isinstance(params, BaseModel) else (params or {})
            p = spec.params.model_validate(raw)
        except ValidationError as e:
            raise _invalid(name, e) from None
        if spec.kind != "job":
            return spec.result.model_validate(spec.fn(Call(self), p))

        def work(ctx: JobContext) -> Any:
            return spec.result.model_validate(spec.fn(Call(self, ctx), p)).model_dump(mode="json")

        return self.jobs.start(work, title=name, writes=spec.writes)

    def answer(self, token: str, answers: Mapping[str, Any]) -> Any:
        """Answer a plan the client was handed; the plan store decides what runs."""
        if self.plans is None:
            raise OperationError("no_plans", "This session takes no plan answers.")
        return self.plans.answer(token, answers)

    def startup(self) -> list[StepReport]:
        """Run the start-up steps in order, once the process is set up and before clients read. A failing step is
        reported and logged, never stops the next."""
        reports = []
        for step in self._startup_steps:
            try:
                reports.append(StepReport(step.name, True, step.fn()))
            except Exception as e:
                logging.getLogger("bayle.session").exception("startup step %s failed", step.name)
                reports.append(StepReport(step.name, False, error=str(e)))
        return reports
