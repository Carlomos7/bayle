"""saves over HTTP: each route hands its call to the engine's feature interface (see routers/activity.py for the shape). Filled as session/ops/saves moves here."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/saves", tags=["saves"])
