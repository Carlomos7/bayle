"""The start-up steps the window used to do itself and reads used to do on the side (G14): finish interrupted
installs, adopt older save folders, report unreported game runs. Existing services, only gathered here."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bayle.game.locate import Locations
from bayle.saves import backups as save_backups
from bayle.services import mods as mod_service
from bayle.services import run_health
from bayle.session.operations import StartupStep


def recover_profile(profile: Path | None) -> list[str]:
    """Finish an interrupted change in the profile (what it says it did), or nothing when there is no profile."""
    return [] if profile is None else list(mod_service.recover_interrupted(profile, timeout=0.5))


def recovery_steps(
    loc: Callable[[], Locations], profile: Callable[[], Path | None] = lambda: None
) -> list[StartupStep]:
    """Order: reported runs first (they read settings only), then the profile's interrupted install, then saves.
    loc and profile are asked when a step runs, so they follow the game and profile in use."""

    def adopt() -> list[str]:
        here = loc()
        folders = sorted({p.parent for p in here.save_files()})
        for d in folders:
            save_backups.adopt_legacy_save_folders(d, here.game, again=True)
        return [str(d) for d in folders]

    return [
        StartupStep("run_health", lambda: run_health.recover_all()),
        StartupStep("interrupted_installs", lambda: recover_profile(profile())),
        StartupStep("legacy_save_folders", adopt),
    ]
