"""The Settings operations for the HTTP layer, each handed straight to the session's SettingsService
(services.settings): the page's data, one change of a setting, the folder buttons, the folder-name check, and the three
layout changes and the clean-up, each a check (what would change) and a start (with what the client confirmed).
Temporary: the Qt page calls the service itself, and a future API is built on it the same way. No wording here; the
client words what it gets."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from bayle.errors import OperationError
from bayle.services.settings import SettingSpec, SettingsService
from bayle.session.operations import Call, NoParams, Params, Result, Session, operation, registry


class SettingsPage(BaseModel):
    game: str
    settings: dict[str, Any]
    detected: dict[str, str | None]  # location key -> the path found when it is left blank
    overhaul: str  # the overhaul switch's sentence ("" when the game has none)
    steam_target: str
    steam_options: str
    backups_folder: str
    me3_profiles: str | None
    layout: dict[str, str]  # the saved folder names, by draft field
    specs: list[SettingSpec]


class SetParams(Params):
    key: str  # a key of the page's specs
    value: bool | int | str


class Changed(Result):
    key: str
    value: bool | int | str  # as saved (a number is brought into its range, a location is trimmed)
    stored_as: str  # the key in the settings file (the repair switch has one per game)
    follow: str  # none | settings | appearance | updates: what the window does next
    kind: str


class FolderParams(Params):
    kind: str  # me3 | game | profiles | saves | backups | settings


class FolderPath(Result):
    path: str | None  # None when the folder is not on this PC


class Names(Params):
    """The four folder names; None leaves one as it is."""

    pattern: str | None = None
    packages: str | None = None
    natives: str | None = None
    shared: str | None = None

    def given(self) -> dict[str, str]:
        return {k: v for k in ("pattern", "packages", "natives", "shared") if (v := getattr(self, k)) is not None}


class LayoutCheck(Result):
    errors: dict[str, str]  # draft field -> why that name cannot be used
    preview: str  # the folder the game would get, "" when the pattern is unusable


class RenameChanges(Result):
    changes: dict[str, tuple[str, str]]  # draft field -> (saved name, new name)


class RenameParams(Names):
    expect: dict[str, tuple[str, str]]  # the changes the client confirmed


class FolderParam(Params):
    folder: str


class RelocateFacts(Result):
    folder: str
    profiles: int
    size: int
    free: int | None


class RelocateParams(FolderParam):
    expect_root: str  # the saved profiles folder the client saw ("" for me3's own)


class Profiles(Result):
    names: list[str]


class MoveAllParams(Params):
    expect: list[str]  # the profile names the client confirmed


class SettingsJob(Result):
    job_id: str


def _none() -> SettingsService:
    raise OperationError("no_settings", "This session has no Settings.")


def _settings(session: Session) -> SettingsService:
    return session.service("settings", _none)


@registry.page("settings", view=SettingsPage)
def snapshot(session: Session) -> SettingsPage:
    got = _settings(session).page()
    f = got.facts
    return SettingsPage(
        game=got.game.key,
        settings=f.settings.model_dump(mode="json"),
        detected=f.detected,
        overhaul=f.overhaul,
        steam_target=f.steam_target,
        steam_options=f.steam_options,
        backups_folder=f.backups_folder,
        me3_profiles=f.me3_profiles,
        layout=got.layout,
        specs=list(got.specs.values()),
    )


@operation("settings.set", params=SetParams, result=Changed, kind="command", writes=True)
def set_setting(call: Call, p: SetParams) -> Changed:
    got = _settings(call.session).set(p.key, p.value)
    return Changed(key=got.key, value=got.value, stored_as=got.stored_as, follow=got.follow, kind=got.kind)


@operation("settings.folder", params=FolderParams, result=FolderPath, kind="command", writes=True)
def folder(call: Call, p: FolderParams) -> FolderPath:
    found = _settings(call.session).folder(p.kind)
    return FolderPath(path=None if found is None else str(found))


@operation("settings.layout_check", params=Names, result=LayoutCheck)
def layout_check(call: Call, p: Names) -> LayoutCheck:
    got = _settings(call.session).check_names(p.given())
    return LayoutCheck(errors=got.errors, preview=got.preview)


@operation("settings.check_rename", params=Names, result=RenameChanges)
def check_rename(call: Call, p: Names) -> RenameChanges:
    return RenameChanges(changes=_settings(call.session).check_rename(p.given()))


@operation("settings.rename_layout", params=RenameParams, result=SettingsJob, kind="command", writes=True)
def rename_layout(call: Call, p: RenameParams) -> SettingsJob:
    return SettingsJob(job_id=_settings(call.session).rename(p.given(), p.expect))


@operation("settings.check_relocate", params=FolderParam, result=RelocateFacts)
def check_relocate(call: Call, p: FolderParam) -> RelocateFacts:
    got = _settings(call.session).check_relocate(p.folder)
    return RelocateFacts(folder=got.folder, profiles=got.profiles, size=got.size, free=got.free)


@operation("settings.relocate", params=RelocateParams, result=SettingsJob, kind="command", writes=True)
def relocate(call: Call, p: RelocateParams) -> SettingsJob:
    return SettingsJob(job_id=_settings(call.session).relocate(p.folder, p.expect_root))


@operation("settings.check_move_all", result=Profiles)
def check_move_all(call: Call, p: NoParams) -> Profiles:
    return Profiles(names=_settings(call.session).check_move_all())


@operation("settings.move_all", params=MoveAllParams, result=SettingsJob, kind="command", writes=True)
def move_all(call: Call, p: MoveAllParams) -> SettingsJob:
    return SettingsJob(job_id=_settings(call.session).move_all(p.expect))


@operation("settings.clear_leftovers", result=SettingsJob, kind="command", writes=True)
def clear_leftovers(call: Call, p: NoParams) -> SettingsJob:
    return SettingsJob(job_id=_settings(call.session).clear_leftovers())
