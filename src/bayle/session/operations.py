"""Operations: the named, typed things a client can ask the backend to do, and the Session that runs them.

An operation is a function registered with @operation(name, params=P, result=R, kind=..., writes=...). The registry is
data a client layer can walk (specs()) to build routes and clients; nothing here knows HTTP or Qt.

kind: "read" runs inline and returns its result; "command" runs inline, may write, and returns its result (a small
change that is done when the call returns: a setting, "seen"); "job" runs on the JobManager (writes go through its busy
gate, and the model's JSON form becomes the job result) and returns the job id; "plan" runs inline and returns the plan
the client must confirm, or a Refusal (the operation returns a work.prompts.Proposal; its result model describes what
the job the plan starts will produce, and writes says that job writes; executing it is Session.answer, served by the PlanStore of work.prompts).
A read never writes: reads that used to recover or adopt things at start-up are Session.startup() steps instead.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from bayle.errors import OperationError
from bayle.game.locate import Locations
from bayle.work.jobs import JobContext, JobManager
from bayle.work.prompts import Plan, PlanStore, Proposal, Refusal

Kind = Literal["read", "command", "job", "plan"]
_KINDS = ("read", "command", "job", "plan")


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
class PageSpec:
    key: str
    fn: Callable[..., Any]
    scope: type[Params]  # the filters a snapshot takes (validated before fn sees them)
    view: Any  # the type fn returns (a dataclass or model), for the API's schema


@dataclass(frozen=True)
class OperationSpec:
    name: str
    fn: Callable[[Call, Any], Any]
    params: type[Params]
    result: type[BaseModel]
    kind: Kind
    writes: bool
    title: str | Callable[[Any], str] = (
        ""  # a job's title (top bar, Activity): fixed, or from its params; default: the name
    )
    check: Callable[[Call, Any], None] | None = None  # a job's refusals, raised before it starts (not as a failed job)
    quiet: bool = False  # the client words the job's end itself

    @property
    def page(self) -> str:
        """The part of the name before the first dot ("saves.restore" -> "saves"): a client groups routes by it."""
        return self.name.split(".", 1)[0]


class OperationRegistry:
    def __init__(self) -> None:
        self._ops: dict[str, OperationSpec] = {}
        self._pages: dict[str, PageSpec] = {}

    def operation(
        self,
        name: str,
        *,
        params: type[Params] = NoParams,
        result: type[BaseModel],
        kind: Kind = "read",
        writes: bool = False,
        title: str | Callable[[Any], str] = "",
        check: Callable[[Call, Any], None] | None = None,
        quiet: bool = False,
    ) -> Callable[[Callable[[Call, Any], Any]], Callable[[Call, Any], Any]]:
        """Register fn(call, params) -> result. title(params) names a job for the client (default: name). check and
        quiet apply to a job: check(call, params) raises an OperationError to refuse before anything starts, quiet
        means the client words the job's end itself. A duplicate name, an unknown kind, or a read that writes raises
        ValueError at once (a wiring mistake, not a runtime condition)."""
        if kind not in _KINDS:
            raise ValueError(f"operation {name}: unknown kind {kind!r}")
        if writes and kind == "read":
            raise ValueError(f"operation {name}: a read must not write")

        def register(fn: Callable[[Call, Any], Any]) -> Callable[[Call, Any], Any]:
            if name in self._ops:
                raise ValueError(f"operation {name} is already registered")
            self._ops[name] = OperationSpec(name, fn, params, result, kind, writes, title, check, quiet)
            return fn

        return register

    def page(
        self, key: str, *, scope: type[Params] = NoParams, view: Any = Any
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register fn(session, **scope) -> view as the snapshot of page key. scope: the model of its filters."""

        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            if key in self._pages:
                raise ValueError(f"page {key} is already registered")
            self._pages[key] = PageSpec(key, fn, scope, view)
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

    def page_specs(self) -> list[PageSpec]:
        return [self._pages[k] for k in self.pages()]

    def page_spec(self, key: str) -> PageSpec:
        try:
            return self._pages[key]
        except KeyError:
            raise OperationError("unknown_page", f"No page named {key}.", {"page": key}) from None


registry = OperationRegistry()  # the program's registry; tests build their own
operation = registry.operation


class PlanAnswers(Protocol):
    """What Session.answer needs from the plan store (work.prompts.PlanStore implements it)."""

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
        locations: Callable[[], Locations] | None = None,
        services: Mapping[str, Any] | None = None,
    ):
        """locations: the current game's Locations, for operations that act on one. services: named collaborators
        operations look up with service(name, default) - a test hands a fake, the program gets the default."""
        self.jobs, self.ops, self.plans = jobs, ops or registry, plans
        self._startup_steps = list(startup_steps or [])
        self._locations = locations
        self._services = dict(services or {})

    @property
    def services(self) -> dict[str, Any]:
        return self._services

    def service(self, name: str, default: Callable[[], Any]) -> Any:
        """The collaborator registered as name, else a default one (made once)."""
        if name not in self._services:
            self._services[name] = default()
        return self._services[name]

    def locations(self) -> Locations:
        if self._locations is None:
            raise OperationError("no_game", "No game is selected.")
        return self._locations()

    def snapshot(self, page: str, **scope: Any) -> Any:
        """A page's view model. Reads only."""
        spec = self.ops.page_spec(page)
        try:
            scope = spec.scope.model_validate(scope).model_dump()
        except ValidationError as e:
            raise _invalid(page, e) from None
        return spec.fn(self, **scope)

    def start(self, work: Callable[[JobContext], Any], *, title: str, writes: bool = True, quiet: bool = False) -> str:
        """Start work(ctx) as a job; its return value (a model or JSON-clean data) is the job's result."""

        def dump(ctx: JobContext) -> Any:
            got = work(ctx)
            return got.model_dump(mode="json") if isinstance(got, BaseModel) else got

        return self.jobs.start(dump, title=title, writes=writes, quiet=quiet)

    def run(self, name: str, params: Params | Mapping[str, Any] | None = None) -> Any:
        """Run operation name. A read or command returns its validated result model; a job returns its job id (the
        result arrives on the bus and in jobs.get); a plan returns the Plan to show (it has the id to answer) or a
        Refusal. Raises OperationError: unknown_operation, invalid_params, busy, no_plans."""
        spec = self.ops.get(name)
        try:
            raw = params.model_dump() if isinstance(params, BaseModel) else (params or {})
            p = spec.params.model_validate(raw)
        except ValidationError as e:
            raise _invalid(name, e) from None
        if spec.kind == "plan":
            return self._offer(spec.fn(Call(self), p))
        if spec.kind != "job":
            return spec.result.model_validate(spec.fn(Call(self), p))
        if spec.check is not None:
            spec.check(Call(self), p)
        return self.start(
            lambda ctx: spec.result.model_validate(spec.fn(Call(self, ctx), p)),
            title=(spec.title(p) if callable(spec.title) else spec.title) or name,
            writes=spec.writes,
            quiet=spec.quiet,
        )

    def _offer(self, got: Proposal | Refusal) -> Plan | Refusal:
        if isinstance(got, Refusal):
            return got
        if not isinstance(self.plans, PlanStore):
            raise OperationError("no_plans", "This session takes no plans.")
        return self.plans.add(got.words, got.run, got.stale, got.destructive)

    def answer(self, token: str, answers: Mapping[str, Any]) -> Any:
        """Answer a plan the client was handed; the plan store decides what runs."""
        if self.plans is None:
            raise OperationError("no_plans", "This session takes no plan answers.")
        return self.plans.answer(token, answers)

    def answer_prompt(self, prompt_id: str, key: str) -> None:
        """Answer a question a running job (or the Launch flow) asked on the bus. Raises unknown_prompt when nobody
        waits for it any more."""
        if not self.jobs.prompts.answer(prompt_id, key):
            raise OperationError("unknown_prompt", "That question is no longer open.", {"prompt_id": prompt_id})

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
