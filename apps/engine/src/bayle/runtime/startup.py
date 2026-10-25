"""The start-up steps the window used to do itself and reads used to do on the side (G14): finish interrupted
installs, adopt older save folders, report unreported game runs. Existing services, only gathered here."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.modules.games.locate import Locations
from bayle.modules.launch import run_health
from bayle.modules.mods import service as mod_service
from bayle.modules.saves import saves_page


@dataclass(frozen=True)
class StartupStep:
    """One start-up action: name, and fn() -> what it did (a list of lines, or None)."""

    name: str
    fn: Callable[[], Any]


@dataclass(frozen=True)
class StepReport:
    name: str
    ok: bool
    done: Any = None
    error: str = ""


def run_steps(steps: list[StartupStep]) -> list[StepReport]:
    """Run the start-up steps in order, once the process is set up and before clients read. A failing step is
    reported and logged, never stops the next."""
    reports = []
    for step in steps:
        try:
            reports.append(StepReport(step.name, True, step.fn()))
        except Exception as e:
            logging.getLogger("bayle.runtime").exception("startup step %s failed", step.name)
            reports.append(StepReport(step.name, False, error=str(e)))
    return reports


def recover_profile(profile: Path | None) -> list[str]:
    """Finish an interrupted change in the profile (what it says it did), or nothing when there is no profile."""
    return [] if profile is None else list(mod_service.recover_interrupted(profile, timeout=0.5))


def recovery_steps(
    loc: Callable[[], Locations],
    profile: Callable[[], Path | None] = lambda: None,
    covered: Collection[str] = (),
) -> list[StartupStep]:
    """Order: reported runs first (they read settings only), then the profile's interrupted install, then saves.
    loc and profile are asked when a step runs, so they follow the game and profile in use. covered: the profiles
    (normcased) the start's journal recovery already looked at; the profile in use is skipped when it is one of them,
    and recovered only when it is another (no profile was remembered yet, or the remembered one is gone)."""

    def interrupted() -> list[str]:
        p = profile()
        return [] if p is not None and os.path.normcase(str(p)) in covered else recover_profile(p)

    return [
        StartupStep("run_health", lambda: run_health.recover_all()),
        StartupStep("interrupted_installs", interrupted),
        StartupStep("legacy_save_folders", lambda: saves_page.adopt_legacy_folders(loc())),
    ]
