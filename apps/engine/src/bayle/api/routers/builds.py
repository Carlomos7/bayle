"""builds over HTTP: the Merge page's facts for one profile, read from the last build's record and the profile's merge
health (see modules/mods/builds.py). GET /v1/builds is the report; POST /v1/builds/preview what a rebuild needs now
(it writes nothing); POST /v1/builds/dropped/{id}/accept keeps a left-out change as accepted. The rebuild itself is
mods_rebuild. Mods are the profile's entry indexes; no wording here, the client words what it gets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import Params, Result
from bayle.modules.mods.builds import BuildFacts, BuildPreview, BuildsService

router = APIRouter(prefix="/builds", tags=["builds"])
Builds = Annotated[BuildsService, Depends(service("builds"))]


class ProfileRef(Params):
    profile: str  # the .me3 path


class Accepted(Result):
    id: str


@router.get("", name="builds")
def report(b: Builds, profile: Annotated[str, Query()]) -> BuildFacts:
    """Errors: not_found, no_game."""
    return b.report(profile)


@router.post("/preview", name="builds_preview")
def preview(b: Builds, p: ProfileRef) -> BuildPreview:
    """Errors: not_found, no_game."""
    return b.preview(p.profile)


@router.post("/dropped/{dropped_id}/accept", name="builds_accept_dropped")
def accept_dropped(b: Builds, dropped_id: str, p: ProfileRef) -> Accepted:
    """Errors: not_found (the profile, or the change is not left out now), profile_write_failed."""
    b.accept_dropped(p.profile, dropped_id)
    return Accepted(id=dropped_id)
