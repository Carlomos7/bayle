"""The app factory. Auth is an app-level dependency, so a router added later cannot forget it."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bayle import __version__
from bayle.api import ops, routes
from bayle.api.deps import require_token
from bayle.api.models import CONTRACT_VERSION, Health, Problem
from bayle.api.settings import ApiSettings
from bayle.services.errors import OperationError
from bayle.session import JobManager, PlanStore, Session
from bayle.session import ops as _registered_operations  # noqa: F401  registers the program's operations

_STATUS = {
    "busy": 409,
    "not_found": 404,
    "unknown_operation": 404,
    "unknown_page": 404,
    "unknown_plan": 404,
    "plan_expired": 410,
    "plan_stale": 409,
    "invalid_params": 422,
    "no_game": 409,
    "cancelled": 409,
    "too_many_subscribers": 429,
}


async def _operation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, OperationError)
    problem = Problem(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        problem.model_dump(), status_code=_STATUS.get(exc.code, 400), media_type="application/problem+json"
    )


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """A request FastAPI itself refused (body or query that does not fit the operation's model): same Problem shape."""
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    problem = Problem(code="invalid_params", message="The request is not valid.", details={"errors": errors})
    return JSONResponse(problem.model_dump(), status_code=422, media_type="application/problem+json")


def _unique_id(route) -> str:
    return route.name


def create_app(settings: ApiSettings | None = None, session: Session | None = None) -> FastAPI:
    settings = settings or ApiSettings()  # type: ignore[call-arg]  # fails fast when the token is missing

    # shortcut: no game_running gate yet (needs a selected game's Locations); wire it with the first writing endpoint
    session = session or Session(JobManager(), plans=PlanStore())
    jobs = session.jobs

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.jobs = jobs
        app.state.session = session
        yield

    # The generated /docs and /openapi.json routes sit outside app-level dependencies: off; the spec is exported offline.
    app = FastAPI(
        title="Bayle API",
        version=CONTRACT_VERSION,
        lifespan=lifespan,
        dependencies=[Depends(require_token)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        generate_unique_id_function=_unique_id,
    )
    app.add_exception_handler(OperationError, _operation_error)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    # The last middleware added is the outermost: the host check runs first, then CORS.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    v1 = APIRouter(prefix="/v1")

    @v1.get("/health")
    async def health() -> Health:
        return Health(app_version=__version__, contract_version=CONTRACT_VERSION)

    v1.include_router(routes.router)
    v1.include_router(ops.session_router(session))
    app.include_router(v1)
    # state is also set here so tests and the offline export work without running the lifespan
    app.state.settings = settings
    app.state.jobs = jobs
    app.state.session = session
    return app
