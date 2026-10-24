"""The engine's feature interfaces for one client, built in one place: the window's Shell and the HTTP backend both
take them from here, so a feature added to the engine reaches every client with the same jobs and the same game."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bayle.game.locate import Locations
from bayle.platform import logging as run_logging
from bayle.services.activity import ActivityService
from bayle.services.mod_configs import ModConfigsService
from bayle.services.mod_install import ModInstallService
from bayle.services.mods_page import ModsService
from bayle.services.profile_transfer import ProfileTransferService
from bayle.services.saves_page import SavesService
from bayle.services.settings import SettingsService
from bayle.services.shared_mods import ModLibraryService
from bayle.work.jobs import JobManager


@dataclass(frozen=True)
class Features:
    activity: ActivityService
    settings: SettingsService
    saves: SavesService
    profile_transfer: ProfileTransferService
    mod_configs: ModConfigsService
    mods: ModsService
    mod_install: ModInstallService
    mod_library: ModLibraryService

    def services(self) -> dict[str, Any]:
        """By name, for the session's thin HTTP operations (session.service(name))."""
        return dict(vars(self))


def build(
    jobs: JobManager, activity_log: run_logging.JobStore | None, locations: Callable[[], Locations | None]
) -> Features:
    """locations: the client's current game (None: none selected)."""
    return Features(
        activity=ActivityService(jobs, activity_log, locations),
        settings=SettingsService(jobs, locations),
        saves=SavesService(jobs, locations),
        profile_transfer=ProfileTransferService(jobs, locations),
        mod_configs=ModConfigsService(jobs, locations),
        mods=ModsService(jobs, locations),
        mod_install=ModInstallService(jobs, locations),
        mod_library=ModLibraryService(jobs, locations),
    )
