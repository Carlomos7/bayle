"""profile_transfer over HTTP: each route hands its call to the engine's feature interface (see routers/activity.py for the shape). Filled as session/ops/profile_transfer moves here."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/profile_transfer", tags=["profile_transfer"])
