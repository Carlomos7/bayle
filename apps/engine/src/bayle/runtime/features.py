"""The engine's feature interfaces for one client, built in one place: the window's Shell and the HTTP backend both
take them from here, so a feature added to the engine reaches every client with the same jobs and the same game."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bayle.adapters.system import logging as run_logging
from bayle.modules.activity.service import ActivityService
from bayle.modules.games import catalog
from bayle.modules.games.locate import Locations
from bayle.modules.launch.service import LaunchService
from bayle.modules.mods.mod_configs import ModConfigsService
from bayle.modules.mods.mod_install import ModInstallService
from bayle.modules.mods.mods_page import ModsService
from bayle.modules.mods.profile_transfer import ProfileTransferService
from bayle.modules.mods.shared_mods_page import ModLibraryService
from bayle.modules.saves.saves_page import SavesService
from bayle.modules.settings.service import SettingsService
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
    launch: LaunchService

    def services(self) -> dict[str, Any]:
        """By name, for the session's thin HTTP operations (session.service(name))."""
        return dict(vars(self))


def build(
    jobs: JobManager,
    activity_log: run_logging.JobStore | None,
    locations: Callable[[], Locations | None],
    select_game: Callable[[catalog.Game], Locations] | None = None,
) -> Features:
    """locations: the client's current game (None: none selected). select_game: how a client switches it."""
    return Features(
        activity=ActivityService(jobs, activity_log, locations),
        settings=SettingsService(jobs, locations),
        saves=SavesService(jobs, locations),
        profile_transfer=ProfileTransferService(jobs, locations),
        mod_configs=ModConfigsService(jobs, locations),
        mods=ModsService(jobs, locations),
        mod_install=ModInstallService(jobs, locations),
        mod_library=ModLibraryService(jobs, locations),
        launch=LaunchService(jobs, locations, select_game),
    )
