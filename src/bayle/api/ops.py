"""The routes every page shares, generated from the session's registry: nothing here names a page.

GET  /v1/pages/{page}   a page's snapshot (its filters are query parameters)
POST /v1/ops/{name}     run an operation: a read or command answers with its result, a job with 202 and the job id,
                        a plan with the question to show (or a refusal)
POST /v1/plans/{id}     answer a plan; it runs once and answers with the id of the job it started

Each page and operation gets its own path, so the OpenAPI document carries its own filters, params and result.
No `from __future__ import annotations` here: the annotations are built from the registry's models at def time.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from bayle.api.deps import SessionDep
from bayle.api.models import JobStarted, PlanAnswer, PlanExecuted, PlanOffer
from bayle.session import NoParams, OperationSpec, PageSpec, Session
from bayle.views.common import Refusal, prompt_dict


def _page_route(router: APIRouter, spec: PageSpec) -> None:
    def endpoint(session: SessionDep, scope: Annotated[spec.scope, Query()]) -> Any:  # pyright: ignore[reportInvalidTypeForm]
        return session.snapshot(spec.key, **scope.model_dump())

    router.add_api_route(
        f"/pages/{spec.key}",
        endpoint,
        methods=["GET"],
        name=f"page_{spec.key}",
        tags=["pages"],
        response_model=spec.view if spec.view is not Any else None,
    )


def _op_route(router: APIRouter, spec: OperationSpec) -> None:
    def respond(got: Any) -> Any:
        if spec.kind == "job":
            return JobStarted(job_id=got)
        if spec.kind == "plan":
            if isinstance(got, Refusal):
                return PlanOffer(prompt=prompt_dict(got))
            return PlanOffer(plan_id=got.id, prompt=prompt_dict(got.words))
        return got

    if spec.params is NoParams:

        def endpoint(session: SessionDep) -> Any:  # pyright: ignore[reportRedeclaration]
            return respond(session.run(spec.name))

    else:

        def endpoint(session: SessionDep, body: spec.params) -> Any:  # type: ignore[misc]
            return respond(session.run(spec.name, body))

    model = {"job": JobStarted, "plan": PlanOffer}.get(spec.kind, spec.result)
    router.add_api_route(
        f"/ops/{spec.name}",
        endpoint,
        methods=["POST"],
        name=f"op_{spec.name.replace('.', '_')}",
        tags=[spec.page],
        response_model=model,
        status_code=202 if spec.kind == "job" else 200,
        summary=f"{spec.name} ({spec.kind}{', writes' if spec.writes else ''})",
    )


def session_router(session: Session) -> APIRouter:
    router = APIRouter()
    for page in session.ops.page_specs():
        _page_route(router, page)
    for spec in session.ops.specs():
        _op_route(router, spec)

    @router.post("/plans/{plan_id}", tags=["plans"])
    def answer_plan(session: SessionDep, plan_id: str, body: PlanAnswer) -> PlanExecuted:
        """Answer a plan the client was offered: runs it once. Errors: unknown_plan, plan_expired, plan_stale."""
        return PlanExecuted(job_id=session.answer(plan_id, body.model_dump()))

    return router
