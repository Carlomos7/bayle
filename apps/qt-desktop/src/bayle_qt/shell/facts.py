"""What the top bar and the Launch gate depend on, as facts and codes with no words (the window words them: ui/launcher
/topbar.py). One frozen `Facts` snapshot read by the shell; `blocked` says why a launch mode cannot start, as a code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bayle.config.settings import LauncherSettings, game_setting
from bayle.game import catalog as games
from bayle.services.play import Problem

PROFILE, OFFLINE, VANILLA = "profile", "offline", "vanilla"
MODES = (PROFILE, OFFLINE, VANILLA)


@dataclass(frozen=True)
class Facts:
    """Everything the top bar depends on, read once by the shell."""

    game: games.Game
    installed: bool = True  # the game's folder or exe is known
    profile_count: int = 0
    problems: tuple[Problem, ...] = ()  # the current profile's, from LaunchProfile.problems()
    checking: bool = False  # the disk checks are taking a while
    warnings: tuple[Problem, ...] = ()  # LaunchProfile.warnings(): Launch still works, a mod is left out
    busy: bool = False
    job_label: str = ""  # the running job's title or newest progress line (a job record, not window wording)
    step: str = ""  # the Launch flow's step code before its job runs (launch.STEPS)
    job_kind: str = ""  # "" | "launch" | "update" | "other"
    game_running: bool = False
    steam_bad: bool = False  # Steam runs but is not signed in (for long enough to say so)
    dead_shells: int = 0
    warn_dead_shells: bool = True
    coop_unsaved: bool = False  # Seamless settings edited and not saved: they apply on launch
    me3_update: str = ""  # the newer me3 version, or "" (said once a session)
    failed_job: str = ""  # a job that failed and was not looked at yet
    mode: str = PROFILE


@dataclass(frozen=True)
class Block:
    """Why a launch cannot start. code: busy | running | not_ready | not_installed | no_profile | problem. The rest are
    the facts the words need (problem: the Problem's code, its path and its English text)."""

    code: str
    game: str = ""
    problem: str = ""
    path: str = ""
    text: str = ""


def blocked(facts: Facts, mode: str) -> Block | None:
    """Why `mode` cannot launch now; None when it can (the job and the running game are states of their own)."""
    g = facts.game
    if not g.ready:
        return Block("not_ready", g.name)
    if not facts.installed:
        return Block("not_installed", g.name)
    if mode == VANILLA:
        return None
    if facts.profile_count == 0:
        return Block("no_profile", g.name)
    if facts.problems:
        p = facts.problems[0]
        return Block("problem", g.name, p.code, str(p.path), str(p))
    return None


def mode_of(settings: LauncherSettings, game: games.Game) -> str:
    """The Launch mode remembered for the game; Profile when none (or an unknown word)."""
    value = game_setting(settings, game.key, "launch_mode")
    return value if value in MODES else PROFILE


def profile_labels(launch_profiles) -> list[str]:
    """One label per setup, as the profile list names them (a file name; the folder too when two share a name)."""
    labels = [s.label for s in launch_profiles]
    return [
        f"{label}  ·  {Path(s.source).parent.name}" if labels.count(label) > 1 else label
        for s, label in zip(launch_profiles, labels)
    ]
