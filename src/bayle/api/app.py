"""The app factory. Auth is an app-level dependency, so a router added later cannot forget it."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from bayle import __version__
from bayle.api.deps import require_token
from bayle.api.models import CONTRACT_VERSION, Health, Problem
from bayle.api.settings import ApiSettings
from bayle.services.errors import OperationError

_STATUS = {"busy": 409, "not_found": 404, "cancelled": 409}


async def _operation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, OperationError)
    problem = Problem(code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        problem.model_dump(), status_code=_STATUS.get(exc.code, 400), media_type="application/problem+json"
    )


def _unique_id(route) -> str:
    return route.name


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    settings = settings or ApiSettings()  # type: ignore[call-arg]  # fails fast when the token is missing

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
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

    app.include_router(v1)
    # state is also set here so tests and the offline export work without running the lifespan
    app.state.settings = settings
    return app
