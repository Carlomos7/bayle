from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bayle.api.settings import ApiSettings
from bayle.errors import OperationError
from bayle.session import Session
from bayle.work.jobs import JobManager

_bearer = HTTPBearer(auto_error=False)  # stateless scheme; auto_error=False makes a missing header a 401, not 403


def get_settings(request: Request) -> ApiSettings:
    return request.app.state.settings


SettingsDep = Annotated[ApiSettings, Depends(get_settings)]


def require_token(
    settings: SettingsDep, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> None:
    # bytes: compare_digest raises TypeError on non-ASCII str
    if cred is None or not hmac.compare_digest(cred.credentials.encode(), settings.token.encode()):
        raise HTTPException(401, "Missing or wrong token.", headers={"WWW-Authenticate": "Bearer"})


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs


JobsDep = Annotated[JobManager, Depends(get_jobs)]


def service(name: str) -> Callable[[Request], Any]:
    """A dependency handing a route the engine's feature interface `name` (services.features): one per feature
    router. Raises not_available when the app was built without it."""

    def get(request: Request) -> Any:
        found = request.app.state.services.get(name)
        if found is None:
            raise OperationError("not_available", f"This server has no {name} feature.", {"feature": name})
        return found

    return get


def get_session(request: Request) -> Session:
    return request.app.state.session


SessionDep = Annotated[Session, Depends(get_session)]
