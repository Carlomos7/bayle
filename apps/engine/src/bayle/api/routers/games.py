"""The games the launcher knows and which one is current, handed straight to the engine's LaunchService
(modules.launch.service). No wording here; the client words what it gets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import NoParams, Params, Result
from bayle.modules.launch.service import LaunchService

router = APIRouter(prefix="/games", tags=["games"])
Launch = Annotated[LaunchService, Depends(service("launch"))]


class GameItem(Result):
    key: str  # me3's name for the game, also the settings key
    name: str
    ready: bool  # fully supported (the others show a placeholder)
    installed: str | None  # the game's folder, None when it is not on this PC
    current: bool
    profile: str | None  # the setup Play last used for it (a profile's `source`)
    last_run_build: str | None  # the exe's build stamp the last Play saw


class GamesPage(Result):
    games: list[GameItem]


class SelectGameParams(Params):
    key: str  # a game's key


@router.get("", name="games")
def games(s: Launch, _q: Annotated[NoParams, Query()]) -> GamesPage:
    return GamesPage(games=[GameItem(**vars(g)) for g in s.games()])


@router.post("/select", name="games_select")
def select(s: Launch, p: SelectGameParams) -> GamesPage:
    """Make the game current (and the one the next start opens on). Errors: unknown_game, busy."""
    return GamesPage(games=[GameItem(**vars(g)) for g in s.select_game(p.key)])
