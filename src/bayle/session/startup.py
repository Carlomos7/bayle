"""The start-up steps the window used to do itself and reads used to do on the side (G14): finish interrupted
installs, adopt older save folders, report unreported game runs. Existing services, only gathered here."""

from __future__ import annotations

from pathlib import Path

from bayle.game.locate import Locations
from bayle.saves import backups as save_backups
from bayle.services import mods as mod_service
from bayle.services import run_health
from bayle.session.operations import StartupStep


def recovery_steps(loc: Locations, profile: Path | None = None) -> list[StartupStep]:
    """Order: reported runs first (they read settings only), then the profile's interrupted install, then saves."""

    def adopt() -> list[str]:
        folders = sorted({p.parent for p in loc.save_files()})
        for d in folders:
            save_backups.adopt_legacy_save_folders(d, loc.game, again=True)
        return [str(d) for d in folders]

    steps = [StartupStep("run_health", run_health.recover_all)]
    if profile is not None:
        steps.append(StartupStep("interrupted_installs", lambda: mod_service.recover_interrupted(profile, timeout=0.5)))
    steps.append(StartupStep("legacy_save_folders", adopt))
    return steps
