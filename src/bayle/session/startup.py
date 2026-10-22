"""The start-up steps the window used to do itself and reads used to do on the side (G14): finish interrupted
installs, adopt older save folders, report unreported game runs. Existing services, only gathered here."""

from __future__ import annotations

from pathlib import Path

from bayle.game.locate import Locations
from bayle.services import mods as mod_service
from bayle.services import run_health, saves_page
from bayle.session.operations import StartupStep


def recovery_steps(loc: Locations, profile: Path | None = None) -> list[StartupStep]:
    """Order: reported runs first (they read settings only), then the profile's interrupted install, then saves."""

    steps = [StartupStep("run_health", run_health.recover_all)]
    if profile is not None:
        steps.append(StartupStep("interrupted_installs", lambda: mod_service.recover_interrupted(profile, timeout=0.5)))
    steps.append(StartupStep("legacy_save_folders", lambda: saves_page.adopt_legacy_folders(loc)))
    return steps
