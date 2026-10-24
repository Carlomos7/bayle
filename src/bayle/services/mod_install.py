"""Installing mods into a profile and setting up overhauls: the engine interface the Mods page's install dialog, Take
over and the overhaul menu call. The work itself lives in services.mods and services.profile_mods."""

from __future__ import annotations

from collections.abc import Callable

from bayle.game.locate import Locations
from bayle.work.jobs import JobManager


class ModInstallService:
    """Mod installs and overhaul setup for one engine: jobs is its JobManager, locations the current game's Locations (None: no game selected).
    Returns data and OperationError codes, never wording: the Qt page words them."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations
