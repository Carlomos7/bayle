from __future__ import annotations

from typing import Any

from pydantic import BaseModel

CONTRACT_VERSION = "1"  # major of the /v1 contract; additive changes only within it


class Health(BaseModel):
    app_version: str
    contract_version: str
    ready: bool = True


class Problem(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}
