"""The launcher settings: what the window remembers between runs, and the rules for the layout names in them. The
file they live in is config.settings_file; the folder it is in, config.app_paths."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

# ----------------------------------------------------------------------------- where the launcher's profiles live
# The folder layout (mods.library): <profiles_root>/<game_folder_pattern>/<name>/<name>.me3 with packages/, natives/,
# builds/ and .bayle/; Shared mods in <profiles_root>/<game folder>/<shared_folder>/. Every name is the player's to
# change in Settings; layout_problems() says in plain words why one cannot be used.
DEFAULT_GAME_PATTERN = "b-{game}"
DEFAULT_PACKAGES = "packages"
DEFAULT_NATIVES = "natives"
DEFAULT_SHARED = ".shared"
# Names the launcher keeps for itself inside a game's folder or a profile's folder.
_OWN_NAMES = frozenset({"builds", ".bayle", ".roundtable", ".roundtable-ops", "profiles", "library"})
_FOLDER_ILLEGAL = re.compile(r'[<>:"/\|?*\x00-\x1f]')
_FOLDER_DEVICES = {"con", "prn", "aux", "nul", "conin$", "conout$"} | {
    f"{p}{d}" for p in ("com", "lpt") for d in "123456789"
}


def folder_name_problem(name: object) -> str | None:
    """Why `name` can't be a folder name of the launcher's layout, or None when it is fine."""
    if not isinstance(name, str) or not name.strip():
        return "A folder name can't be empty."
    if name != name.strip() or name in (".", "..") or name.startswith(".."):
        return "A folder name can't have spaces around it or be made of dots."
    if (bad := _FOLDER_ILLEGAL.search(name)) is not None:
        return f"A folder name can't contain {bad.group()!r}."
    if name[-1] in ". ":
        return "A folder name can't end with a dot or a space."
    if name.split(".")[0].rstrip(" ").lower() in _FOLDER_DEVICES:
        return f"{name} is a name Windows keeps for a device."
    if name.lower() in _OWN_NAMES or name.lower().endswith(".me3"):
        return f"{name} is a name the launcher or me3 uses itself."
    return None


def game_folder_problem(pattern: object) -> str | None:
    """Why `pattern` can't name a game's folder ("b-{game}"), or None: it needs {game}, once, and is a safe name once
    a game's key is put in."""
    if not isinstance(pattern, str) or pattern.count("{game}") != 1:
        return "The game folder's name needs {game} in it, once."
    if "{" in (rest := pattern.replace("{game}", "")) or "}" in rest:
        return "The game folder's name can't have other braces."
    return folder_name_problem(pattern.replace("{game}", "eldenring"))


def layout_problems(
    *,
    profiles_root: object = None,
    pattern: object = DEFAULT_GAME_PATTERN,
    packages: object = DEFAULT_PACKAGES,
    natives: object = DEFAULT_NATIVES,
    shared: object = DEFAULT_SHARED,
) -> dict[str, str]:
    """What is wrong with these layout settings: field name -> a plain sentence. Empty when all of them can be used."""
    out: dict[str, str] = {}
    if profiles_root is not None and (
        not isinstance(profiles_root, str) or not profiles_root.strip() or not Path(profiles_root).is_absolute()
    ):
        out["profiles_root"] = "The Profiles folder has to be a full path."
    if (why := game_folder_problem(pattern)) is not None:
        out["game_folder_pattern"] = why
    for field, value in (("packages_folder", packages), ("natives_folder", natives), ("shared_folder", shared)):
        if (why := folder_name_problem(value)) is not None:
            out[field] = why
    names = {"packages_folder": packages, "natives_folder": natives, "shared_folder": shared}
    seen: dict[str, str] = {}
    for field, value in names.items():
        if field in out or not isinstance(value, str):
            continue
        if value.lower() in seen:
            out[field] = f"{value} is already the name of the {seen[value.lower()].split('_')[0]} folder."
        seen[value.lower()] = field
    return out


class LauncherSettings(BaseModel):
    """Everything the window remembers between runs. Unknown keys are kept so older builds' values survive."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Elden Ring's remembered launch profile; other games keep theirs under `games`. The file key stays `setup` so a
    # build restored after an update rollback still finds it.
    profile: str | None = Field(default=None, alias="setup")
    game: str = "eldenring"  # the tab the window opens on
    games: dict[str, dict[str, Any]] = Field(default_factory=dict)  # per-game values for games other than Elden Ring
    theme: Literal["dark", "tarnished", "light", "system"] = "dark"  # the Widgets window: tarnished is dark
    effects: Literal["full", "reduced", "off"] = "full"  # the QML windows' glow, grain and blur
    grain: Literal["off", "subtle", "film"] = "subtle"
    log_level: Literal["normal", "verbose"] = "normal"  # verbose: debug lines in launcher.log, from the next start
    logo: Literal["auto", "crimson", "ice", "gold"] = "auto"
    native_configs: dict[str, list[str]] = Field(default_factory=dict)  # DLL path -> settings files tied to it
    parameter_overlays: dict[str, Any] = Field(default_factory=dict)  # profile -> {package, rebuild} set in Options
    rebuild_approved: list[str] = Field(default_factory=list)  # rebuild tools the user allowed to run
    activity_seen: float = 0.0  # when the Activity page was last looked at: failures after it are counted
    tips_seen: list[str] = Field(default_factory=list)  # the shell's first-run hints already dismissed
    rail_collapsed: bool = False  # the shell's navigation rail folded to icons (the top bar's menu button)
    launch_mode: str | None = None  # Elden Ring's Launch mode ("profile" | "offline" | "vanilla"); others under `games`

    # Leave an overhaul the launcher has a config for off in an offline launch.
    offline_strip_overhaul: bool = False
    offline_start_steam: bool = True
    offline_skip_confirm: bool = False

    play_update_merge: bool = True  # rebuild out-of-date merged mods before Play by itself; off: ask first
    overhaul_install: bool = False  # the Mods page's Overhaul button: install and remove overhauls itself (preview)
    # Co-op page notices about Seamless Co-op left in the game folder, turned off for good: "<game>|<profile>|<kind>"
    coop_relocate_dismissed: list[str] = Field(default_factory=list)
    # Where profiles live (mods.library): <profiles_root>/<game_folder_pattern>/<name>/ with the folder names below.
    # An unusable value is replaced by its default when the file is read (layout_problems says why to the Settings page).
    profiles_root: str | None = None  # None: me3's profiles folder
    game_folder_pattern: str = DEFAULT_GAME_PATTERN
    packages_folder: str = DEFAULT_PACKAGES
    natives_folder: str = DEFAULT_NATIVES
    shared_folder: str = DEFAULT_SHARED
    # Setups the Mods page stopped offering to adopt into the library (S7d): the setup folder's path
    adopt_dismissed: list[str] = Field(default_factory=list)
    # What the last Play of each game saw (services.run_health): game key -> {"exe_build": the exe's build stamp}
    run_state: dict[str, dict[str, Any]] = Field(default_factory=dict)
    play_backup_before: bool = False
    play_repair_after: bool = True  # Nightreign: re-sign the save's sections me3 can leave unsigned
    # Elden Ring: restore the save's regulation copy after me3. The game never reads it back (game model,
    # 2026-10-13); only save editors do, so it is off unless the player turns it on.
    play_repair_after_eldenring: bool = False
    play_clear_before: bool = True
    play_clear_after: bool = True
    warn_dead_shells: bool = True
    play_boot_boost: bool = True
    play_show_logos: bool = False
    play_diagnostics: bool = False
    check_me3_updates: bool = True
    check_launcher_updates: bool = True

    me3_path: str = ""
    game_exe: str = ""
    me3_profile_dir: str = ""
    saves_dir: str = ""  # Elden Ring's save-folder override (blank = detect); other games under `games`
    backups_keep: int = 20  # the newest backups kept per save (5 to 200; saves.backups.keep_newest reads it)

    me3_latest: dict[str, Any] | None = None
    me3_latest_checked: float = 0.0
    me3_info_cache: dict[str, str] = Field(default_factory=dict)
    launcher_latest: dict[str, Any] | None = None  # the newest release GitHub named, for launcher_channel
    launcher_latest_checked: float = 0.0  # when GitHub last answered (a 304 counts)
    launcher_latest_etag: str = ""  # sent back as If-None-Match; a 304 does not count against GitHub's hourly limit
    launcher_update_skipped: str = ""
    launcher_channel: Literal["stable", "beta"] = "stable"  # beta also offers pre-releases
    launcher_check_failures: int = 0  # failed checks in a row; each one doubles the wait before the next
    launcher_next_check: float = 0.0  # no automatic check before this (after failures, or GitHub's limit)
    launcher_check_error: str = ""  # why the last check failed, shown on Settings; empty after a good one
    launcher_advisory: dict[str, Any] | None = None  # the project's minimum-version notice, as last fetched
    launcher_advisory_etag: str = ""
    launcher_advisory_checked: float = 0.0
    update_pending: dict[str, Any] | None = None  # an update handed to the setup or a new exe, until it is confirmed
    update_result: dict[str, Any] | None = None  # how the last update went, shown once on the next start
    # Written only once a build sets them (WRITTEN_WHEN_SET), so a file without them stays without them:
    update_blocked: list[str] = Field(default_factory=list)  # versions that failed to start here and were undone
    inno_migration: dict[str, Any] | None = None  # the move from the Inno Setup install, step by step (updates.inno)

    @classmethod
    def from_raw(cls, raw: Any) -> LauncherSettings:
        """Settings from what the file held: anything but an object gives the defaults, and a value of the wrong
        type (a null, a typo) gives that key's default while every other key is kept."""
        if not isinstance(raw, dict):
            raw = {}
        raw = {k: v for k, v in raw.items() if k not in RETIRED_KEYS}
        try:
            return cls.model_validate(raw)
        except ValidationError as e:
            bad = {err["loc"][0] for err in e.errors() if err["loc"]}
            return cls.model_validate({k: v for k, v in raw.items() if k not in bad})

    @field_validator("logo", mode="before")
    @classmethod
    def _logo_ok(cls, v: Any) -> Any:
        # Older builds saved dark and light; anything else unknown falls back to following the theme.
        return (
            {"dark": "crimson", "light": "ice"}.get(v, v)
            if v in ("dark", "light", "crimson", "ice", "gold")
            else "auto"
        )

    @field_validator("profiles_root", mode="before")
    @classmethod
    def _root_ok(cls, v: Any) -> Any:
        return v if "profiles_root" not in layout_problems(profiles_root=v) else None

    @field_validator("game_folder_pattern", mode="before")
    @classmethod
    def _pattern_ok(cls, v: Any) -> Any:
        return v if game_folder_problem(v) is None else DEFAULT_GAME_PATTERN

    @field_validator("packages_folder", "natives_folder", "shared_folder", mode="before")
    @classmethod
    def _folder_ok(cls, v: Any, info: Any) -> Any:
        default = {"packages_folder": DEFAULT_PACKAGES, "natives_folder": DEFAULT_NATIVES}.get(
            info.field_name, DEFAULT_SHARED
        )
        return v if folder_name_problem(v) is None else default

    def to_file(self) -> dict[str, Any]:
        """What the file holds: every key, unknown ones (an older or newer build's) included, except the keys in
        WRITTEN_WHEN_SET while nothing has set them."""
        out = self.model_dump(by_alias=True)
        for key in WRITTEN_WHEN_SET:
            if key not in self.model_fields_set:
                out.pop(key, None)
        return out


WRITTEN_WHEN_SET = ("update_blocked", "inno_migration")
RETIRED_KEYS = ("build_merges",)  # settings an older build wrote that nothing reads now: dropped on the next save


_FIELD_OF_KEY = {"setup": "profile"}  # a per-game file key whose Python field has another name
GAME_KEYS = ("setup", "game_exe", "saves_dir", "launch_mode")  # values each game keeps for itself


def game_setting(settings: LauncherSettings, game: str, key: str, default: Any = None) -> Any:
    """One per-game value. Elden Ring's live at the top level, where builds before multi-game support kept them, so
    an older build still finds them; every other game keeps its own under `games`."""
    if game == "eldenring":
        value = getattr(settings, _FIELD_OF_KEY.get(key, key), None)
    else:
        value = (settings.games.get(game) or {}).get(key)
    return default if value is None else value
