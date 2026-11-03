"""Settings over HTTP: the page's facts, one change of a setting, the folder buttons, the folder-name check, and the
three layout changes and the clean-up (each a check, then a start with what the client confirmed), each handed straight
to the engine's SettingsService (modules.settings.service). No wording here; the client words what it gets."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from bayle.api.deps import service
from bayle.api.models import JobStarted, NoParams, Params, Result
from bayle.modules.settings.service import SettingSpec, SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])
Settings = Annotated[SettingsService, Depends(service("settings"))]


class SettingsPage(Result):
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


class SettingChanged(Result):
    key: str
    value: bool | int | str  # as saved (a number is brought into its range, a location is trimmed)
    stored_as: str  # the key in the settings file (the repair switch has one per game)
    follow: str  # none | settings | appearance | updates: what the window does next
    kind: str


class SettingsFolderParams(Params):
    kind: str  # me3 | game | profiles | saves | backups | settings


class FolderPath(Result):
    path: str | None  # None when the folder is not on this PC


class LayoutNames(Params):
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


class LayoutRenameParams(LayoutNames):
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


class SettingsProfiles(Result):
    names: list[str]


class MoveAllParams(Params):
    expect: list[str]  # the profile names the client confirmed


@router.get("", name="settings")
def page(s: Settings, _q: Annotated[NoParams, Query()]) -> SettingsPage:
    got = s.page()
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


class SettingsDefaults(Result):
    settings: dict[str, Any]  # every key of the settings file with its default value


@router.get("/defaults", name="settings_defaults")
def defaults(s: Settings, _q: Annotated[NoParams, Query()]) -> SettingsDefaults:
    """The value each setting has in a fresh settings file (for Reset)."""
    return SettingsDefaults(settings=s.defaults())


class Me3Version(Result):
    version: str | None  # None: me3 is not installed or cannot be asked


@router.get("/me3", name="settings_me3")
def me3(s: Settings, _q: Annotated[NoParams, Query()]) -> Me3Version:
    return Me3Version(version=s.me3_version())


@router.post("/set", name="settings_set")
def set_setting(s: Settings, p: SetParams) -> SettingChanged:
    got = s.set(p.key, p.value)
    return SettingChanged(key=got.key, value=got.value, stored_as=got.stored_as, follow=got.follow, kind=got.kind)


@router.post("/folder", name="settings_folder")
def folder(s: Settings, p: SettingsFolderParams) -> FolderPath:
    found = s.folder(p.kind)
    return FolderPath(path=None if found is None else str(found))


@router.post("/layout_check", name="settings_layout_check")
def layout_check(s: Settings, p: LayoutNames) -> LayoutCheck:
    got = s.check_names(p.given())
    return LayoutCheck(errors=got.errors, preview=got.preview)


@router.post("/check_rename", name="settings_check_rename")
def check_rename(s: Settings, p: LayoutNames) -> RenameChanges:
    return RenameChanges(changes=s.check_rename(p.given()))


@router.post("/rename_layout", name="settings_rename_layout")
def rename_layout(s: Settings, p: LayoutRenameParams) -> JobStarted:
    return JobStarted(job_id=s.rename(p.given(), p.expect))


@router.post("/check_relocate", name="settings_check_relocate")
def check_relocate(s: Settings, p: FolderParam) -> RelocateFacts:
    got = s.check_relocate(p.folder)
    return RelocateFacts(folder=got.folder, profiles=got.profiles, size=got.size, free=got.free)


@router.post("/relocate", name="settings_relocate")
def relocate(s: Settings, p: RelocateParams) -> JobStarted:
    return JobStarted(job_id=s.relocate(p.folder, p.expect_root))


@router.post("/check_move_all", name="settings_check_move_all")
def check_move_all(s: Settings) -> SettingsProfiles:
    return SettingsProfiles(names=s.check_move_all())


@router.post("/move_all", name="settings_move_all")
def move_all(s: Settings, p: MoveAllParams) -> JobStarted:
    return JobStarted(job_id=s.move_all(p.expect))


@router.post("/clear_leftovers", name="settings_clear_leftovers")
def clear_leftovers(s: Settings) -> JobStarted:
    return JobStarted(job_id=s.clear_leftovers())
