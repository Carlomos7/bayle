from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from bayle.api.settings import ApiSettings

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
