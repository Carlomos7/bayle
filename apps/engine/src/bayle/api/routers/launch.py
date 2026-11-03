"""Profiles and Play over HTTP: the current game's profiles and the one Play remembers, a new empty profile, the
check before Play, and Play itself as a job that asks mid-way (a prompt event, answered on POST /v1/prompts/{id};
Stop is POST /v1/jobs/{id}/cancel), all handed to the engine's LaunchService (modules.launch.service). A profile is
identified by its `source`: its .me3 path, or an installer's manifest. No wording here; the client words what it
gets."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import JobStarted, NoParams, Params, Result
from bayle.modules.launch import play as play_service
from bayle.modules.launch.service import LaunchService

router = APIRouter(prefix="/launch", tags=["launch"])
Launch = Annotated[LaunchService, Depends(service("launch"))]
Mode = Literal["profile", "offline", "vanilla"]  # online with the profile | offline with it | the game without me3


class LaunchProblem(Result):
    code: str  # profile_missing | wrong_game | me3_missing | me3_not_installed | game_exe_missing | ...
    path: str = ""
    detail: str = ""


def _problems(found: tuple[play_service.Problem, ...]) -> list[LaunchProblem]:
    return [LaunchProblem(code=p.code, path=p.path, detail=p.detail) for p in found]


class LaunchProfile(Result):
    profile: str  # the .me3 path
    kind: str  # me3 | manifest
    source: str  # what set_profile and play take
    name: str
    active: bool
    problems: list[LaunchProblem]  # why Play would refuse it


class LaunchProfiles(Result):
    profiles: list[LaunchProfile]


class SetProfileParams(Params):
    source: str  # a profile's `source`; "" forgets the remembered one


class CreateProfileParams(Params):
    name: str


class ProfileCreated(Result):
    profile: str  # the new .me3 path


class LaunchCheckParams(Params):
    mode: Mode
    source: str = ""  # not used by vanilla


class LaunchChecked(Result):
    problems: list[LaunchProblem]  # stop Play
    warnings: list[LaunchProblem]  # leave a mod out but do not stop it
    game_running: bool
    busy: bool  # a writing job runs
    installed: bool


class LaunchPlayParams(LaunchCheckParams):
    allow_without_backup: bool = False  # a failed backup before Play does not stop it


@router.get("/profiles", name="launch_profiles")
def profiles(s: Launch, _q: Annotated[NoParams, Query()]) -> LaunchProfiles:
    return LaunchProfiles(
        profiles=[LaunchProfile(**{**vars(p), "problems": _problems(p.problems)}) for p in s.profiles()]
    )


@router.post("/set_profile", name="launch_set_profile")
def set_profile(s: Launch, p: SetProfileParams) -> LaunchProfiles:
    """Remember the profile Play uses next for the current game. Error: not_found."""
    s.set_active(p.source)
    return profiles(s, NoParams())


@router.post("/create_profile", name="launch_create_profile")
def create_profile(s: Launch, p: CreateProfileParams) -> ProfileCreated:
    """An empty profile for the current game in me3's folder. Errors: invalid_value, create_failed, busy."""
    return ProfileCreated(profile=str(s.create_profile(p.name)))


@router.post("/check", name="launch_check")
def check(s: Launch, p: LaunchCheckParams) -> LaunchChecked:
    """What would stop Play now, read fresh from the disk. Error: not_found."""
    got = s.check(p.mode, p.source)
    return LaunchChecked(
        problems=_problems(got.problems),
        warnings=_problems(got.warnings),
        game_running=got.game_running,
        busy=got.busy,
        installed=got.installed,
    )


@router.post("/play", name="launch_play")
def play(s: Launch, p: LaunchPlayParams) -> JobStarted:
    """Start Play as a job; its result is {"mode"} (offline when the player chose it at the online question). Prompts
    (question codes backup_failed, stale_blocked, stale_rebuild, rebuild_failed, online_risk, offline_confirm) go
    out as prompt events; the answer key `cancel` ends the job as cancelled. Errors: not_found, cannot_launch
    (details.reason game_unsupported | not_installed | game_running | problems), busy."""
    return JobStarted(job_id=s.play(p.mode, p.source, p.allow_without_backup))
