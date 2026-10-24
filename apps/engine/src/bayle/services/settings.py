"""The launcher settings and install facts the window reads and writes (the file itself: config.settings), and the
rules for changing one: the schema of every setting, what values it takes, where it is stored (per game or global)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from bayle.config.app_paths import FROZEN, data_dir, exe_dir, launch_target
from bayle.config.settings import game_setting
from bayle.config.settings_file import load_settings, save_game_settings, save_settings
from bayle.errors import OperationError
from bayle.game.catalog import ELDEN_RING
from bayle.game.locate import PATH_SETTINGS, Locations, saves_dir_problem
from bayle.platform import data_folder
from bayle.platform.text import tr
from bayle.services import layout as layout_service
from bayle.services import mods as mod_service
from bayle.services import play as play_service
from bayle.work.jobs import JobContext, JobManager
from bayle.work.runner import run_job_value

__all__ = [
    "FROZEN",
    "data_dir",
    "exe_dir",
    "game_setting",
    "launch_target",
    "load_settings",
    "save_game_settings",
    "save_settings",
    "PATH_SETTINGS",
]


def read() -> dict:
    """The settings as plain JSON-able data."""
    return load_settings().model_dump(mode="json")


def update(**changes) -> dict:
    """Save the changed fields and return the settings after."""
    save_settings(**changes)
    return read()


# ----------------------------------------------------------------------------- the schema: what each setting is
KEEP_RANGE = (5, 200)  # backups kept per save file: a number outside it is brought inside
CHOICES: dict[str, tuple[str, ...]] = {
    "theme": ("dark", "tarnished", "light", "system"),
    "effects": ("full", "reduced", "off"),
    "grain": ("off", "subtle", "film"),
    "logo": ("auto", "crimson", "ice", "gold"),
    "log_level": ("normal", "verbose"),
    "launcher_channel": ("stable", "beta"),
}
LOCATIONS: dict[str, tuple[bool, bool]] = {  # location key -> (is a folder, saved per game)
    "me3_path": (False, False),
    "game_exe": (False, True),
    "me3_profile_dir": (True, False),
    "saves_dir": (True, True),
}
APPEARANCE = ("theme", "effects", "grain")


class SettingSpec(BaseModel):
    """One setting a client may change: its kind decides which values are allowed, its scope where it is stored."""

    key: str
    kind: Literal["switch", "choice", "number", "location"]
    scope: Literal["global", "game"] = "global"  # game: the value belongs to the current game
    choices: list[str] = []  # kind choice: the allowed values
    low: int | None = None  # kind number: the range a value is brought into
    high: int | None = None
    is_dir: bool = False  # kind location: a folder, else a file
    follow: Literal["none", "settings", "appearance", "updates"] = "settings"  # what the window does after a save


def schema(switch_keys: tuple[str, ...] = ()) -> dict[str, SettingSpec]:
    """Every setting by key. switch_keys: the on/off settings (the page's switch table owns that list)."""
    out = {k: SettingSpec(key=k, kind="switch") for k in switch_keys}
    for k, allowed in CHOICES.items():
        follow = "appearance" if k in APPEARANCE else "updates" if k == "launcher_channel" else "settings"
        out[k] = SettingSpec(key=k, kind="choice", choices=list(allowed), follow=follow)
    out["backups_keep"] = SettingSpec(
        key="backups_keep", kind="number", low=KEEP_RANGE[0], high=KEEP_RANGE[1], follow="none"
    )
    for k, (is_dir, per_game) in LOCATIONS.items():
        out[k] = SettingSpec(key=k, kind="location", is_dir=is_dir, scope="game" if per_game else "global")
    return out


def location_problem(spec: SettingSpec, value: str, game) -> str:
    """Why value cannot be this location, or "" when it can."""
    if spec.key == "saves_dir":
        return saves_dir_problem(value, game)
    if spec.is_dir:
        return "" if Path(value).is_dir() else tr("That folder does not exist.")
    return "" if Path(value).is_file() else tr("That file does not exist.")


def normalise(spec: SettingSpec, value: Any, game) -> bool | int | str:
    """The value as it is saved. Raises OperationError: invalid_value (wrong type), invalid_choice, path_problem."""
    bad = OperationError("invalid_value", tr("That value does not fit {key}.").format(key=spec.key), {"key": spec.key})
    if spec.kind == "switch":
        if not isinstance(value, bool):
            raise bad
        return value
    if spec.kind == "number":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad
        assert spec.low is not None and spec.high is not None
        return max(spec.low, min(spec.high, value))
    if not isinstance(value, str):
        raise bad
    if spec.kind == "choice":
        if value not in spec.choices:
            raise OperationError(
                "invalid_choice",
                tr("{value} is not one of the choices.").format(value=value),
                {"key": spec.key, "choices": spec.choices},
            )
        return value
    value = value.strip()
    if value and (problem := location_problem(spec, value, game)):
        raise OperationError("path_problem", problem, {"key": spec.key, "value": value})
    return value


def store(spec: SettingSpec, value: bool | int | str, game) -> str:
    """Save one setting where it belongs (this game's or global); returns the key it was saved under."""
    key = play_service.repair_key(game) if spec.key == "play_repair_after" else spec.key
    if spec.scope == "game":
        save_game_settings(game.key, **{key: value})
    else:
        save_settings(**{key: value})
    return key


# ----------------------------------------------------------------------------- what the page reads
@dataclass(frozen=True)
class Facts:
    """What the Settings page reads from the disk and the system, as plain data."""

    settings: Any  # config.settings.LauncherSettings
    detected: dict[str, str | None]  # location key -> the path found when it is left blank
    overhaul: str  # the overhaul switch's sentence ("" when the game has none)
    steam_target: str
    steam_options: str
    backups_folder: str
    me3_profiles: str | None  # me3's own profiles folder, as me3 reports it


def backups_folder() -> Path:
    try:
        return data_folder.data_root() / "saves"
    except RuntimeError:  # the data folder is set when the program starts
        return data_dir() / "saves"


def _detected(key: str, loc) -> str | None:
    try:
        found: Path | None = None
        if key == "me3_path":
            found = loc.me3_exe()
        elif key == "game_exe":
            found = loc.game_dir()
        elif key == "me3_profile_dir":
            found = loc.me3_profiles_dir()
        elif key == "saves_dir":
            found = next(iter(loc.save_roots()), None)
        return str(found) if found else None
    except Exception:
        return None


def facts(game, loc) -> Facts:
    """Read only. loc: the game's Locations, or None when no game is selected."""
    try:
        overhaul = mod_service.overhaul_switch_text(game.key)
    except Exception:
        overhaul = ""
    try:
        target, options = play_service.play_command(game)
    except Exception:
        target, options = "", ""
    return Facts(
        load_settings(),
        {k: (_detected(k, loc) if loc is not None else None) for k in LOCATIONS},
        overhaul,
        target,
        options,
        str(backups_folder()),
        _detected("me3_profile_dir", loc) if loc is not None else None,
    )


def folder(kind: str, loc, make: bool = False) -> Path | None:
    """The folder an "Open ... folder" button means, or None when it is not on this PC. make: create the backups
    folder first. Raises OperationError unknown_folder."""
    found: Any = None
    try:
        if kind == "me3" and loc is not None:
            exe = loc.me3_exe()
            found = Path(exe).parent if exe else None
        elif kind == "game" and loc is not None:
            found = loc.game_dir()
        elif kind == "profiles" and loc is not None:
            found = loc.me3_profiles_dir()
        elif kind == "saves" and loc is not None:
            found = next((r for r in loc.save_roots() if r.is_dir()), None)
        elif kind == "backups":
            found = backups_folder()
            if make:
                found.mkdir(parents=True, exist_ok=True)
        elif kind == "settings":
            found = data_dir()
        elif kind not in ("me3", "game", "profiles", "saves"):
            raise OperationError(
                "unknown_folder", tr("There is no folder called {kind}.").format(kind=kind), {"kind": kind}
            )
    except OperationError:
        raise
    except Exception:
        return None
    return Path(found) if found is not None and Path(found).exists() else None


# ----------------------------------------------------------------------------- the Settings application interface
# the on/off settings, in the order the page shows them (their words are the Qt page's)
SWITCH_KEYS = (
    "play_update_merge",
    "overhaul_install",
    "play_boot_boost",
    "play_show_logos",
    "play_diagnostics",
    "play_backup_before",
    "play_clear_before",
    "play_repair_after",
    "play_clear_after",
    "warn_dead_shells",
    "check_launcher_updates",
    "check_me3_updates",
    "offline_strip_overhaul",
    "offline_start_steam",
    "offline_skip_confirm",
)
# draft field -> the settings key of each folder name
LAYOUT_FIELDS = {
    "pattern": "game_folder_pattern",
    "packages": "packages_folder",
    "natives": "natives_folder",
    "shared": "shared_folder",
}


def layout_saved(s) -> dict[str, str]:
    """The four folder names as saved, by draft field."""
    return {field: str(getattr(s, key)) for field, key in LAYOUT_FIELDS.items()}


def name_problems(draft: dict[str, str]) -> dict[str, str]:
    """Draft field -> why that folder name cannot be used (an untranslated sentence the client words)."""
    from bayle.config import settings as cs

    found = cs.layout_problems(**{k: draft[k] for k in LAYOUT_FIELDS if k in draft})
    return {f: found[k] for f, k in LAYOUT_FIELDS.items() if k in found}


def game_preview(pattern: str, game_key: str) -> str:
    """The folder a game would get from pattern ("b-eldenring"); "" when the pattern is unusable."""
    return pattern.replace("{game}", game_key) if pattern.count("{game}") == 1 else ""


@dataclass(frozen=True)
class SettingsFacts:
    """The Settings page's data: what the disk and the system say, the game it is for, and the rules."""

    facts: Facts
    game: Any  # game.catalog.Game
    layout: dict[str, str]  # the saved folder names, by draft field
    specs: dict[str, SettingSpec]


@dataclass(frozen=True)
class Changed:
    key: str
    value: bool | int | str  # as saved (a number brought into its range, a location trimmed)
    stored_as: str  # the key in the settings file (the repair switch has one per game)
    follow: str  # none | settings | appearance | updates: what the window does next
    kind: str  # the setting's kind (switch, choice, number, location)


@dataclass(frozen=True)
class NameCheck:
    errors: dict[str, str]  # draft field -> why it cannot be used
    preview: str  # the game folder the pattern gives, "" when it is unusable


@dataclass(frozen=True)
class RelocateFacts:
    folder: str
    profiles: int
    size: int  # bytes to move
    free: int | None  # free bytes where they go, None when unknown


class SettingsService:
    """Settings for one engine: jobs is its JobManager (the writing job's gates; every layout change and the clean-up
    run on it), locations the current game's Locations (None: no game selected). Returns data and OperationError
    codes, never wording: the Qt page words them (ui/pages/settings/presenter.py). The settings file itself is
    config.settings under the process's data folder."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations

    def _where(self) -> tuple[Any, Locations | None]:
        try:
            loc = self._locations()
        except OperationError:
            loc = None
        return (loc.game if loc is not None else ELDEN_RING), loc

    def _loc(self) -> Locations:
        loc = self._where()[1]
        if loc is None:
            raise OperationError("no_game", "No game is selected.")
        return loc

    def _free(self) -> None:
        """Raises busy / game_running when a layout change could not start now."""
        if self._jobs.busy:
            raise OperationError("busy", "Another job is running.")
        if self._jobs.game_running:
            raise OperationError("game_running", "The game is running.")

    # ---- reads
    def page(self) -> SettingsFacts:
        game, loc = self._where()
        got = facts(game, loc)
        return SettingsFacts(got, game, layout_saved(got.settings), schema(SWITCH_KEYS))

    def folder(self, kind: str) -> Path | None:
        """The folder behind an "Open ... folder" button (asking for the backups folder creates it). Raises
        unknown_folder."""
        return folder(kind, self._where()[1], make=True)

    def check_names(self, draft: dict[str, str]) -> NameCheck:
        game, _loc = self._where()
        return NameCheck(name_problems(draft), game_preview(draft.get("pattern", ""), game.key))

    # ---- one setting
    def set(self, key: str, value: bool | int | str) -> Changed:
        """Save one setting. Raises unknown_setting, invalid_value, invalid_choice, path_problem."""
        spec = schema(SWITCH_KEYS).get(key)
        if spec is None:
            raise OperationError("unknown_setting", f"There is no setting called {key}.", {"key": key})
        game, _loc = self._where()
        saved = normalise(spec, value, game)
        return Changed(key, saved, store(spec, saved, game), spec.follow, spec.kind)

    # ---- the layout changes: check (what would change), then start it as a job with what the client confirmed
    def check_rename(self, names: dict[str, str]) -> dict[str, tuple[str, str]]:
        """Draft field -> (saved name, new name) for each that changes. Raises invalid_names (details.errors),
        nothing_to_change, busy, game_running."""
        saved = layout_saved(load_settings())
        if errors := name_problems({**saved, **names}):
            raise OperationError("invalid_names", next(iter(errors.values())), {"errors": errors})
        changes = {k: (saved[k], v) for k, v in names.items() if v != saved[k]}
        if not changes:
            raise OperationError("nothing_to_change", "The names are the ones in use already.")
        self._free()
        return changes

    def rename(self, names: dict[str, str], expect: dict[str, tuple[str, str]], title: str = "") -> str:
        """Rename the folders as a writing job; returns its id. expect: the changes the client confirmed (stale when
        they changed since)."""
        changes = self.check_rename(names)
        if {k: tuple(v) for k, v in expect.items()} != changes:
            raise OperationError("stale", "Things changed since you were asked. Ask again.")
        new = {k: names[k] for k in changes}

        def work(_ctx: JobContext, loc: Locations) -> int:
            layout_service.rename_layout(loc, **new)
            return 0

        return self._layout_job(work, title or "Renaming folders...")

    def check_relocate(self, new_folder: str) -> RelocateFacts:
        """What moving the profiles folder to new_folder means. Raises invalid_params, busy, game_running."""
        if not new_folder.strip():
            raise OperationError("invalid_params", "Pick a folder.")
        self._free()
        count, size = layout_service.profiles_facts(self._loc())
        return RelocateFacts(new_folder, count, size, layout_service.free_bytes(Path(new_folder)))

    def relocate(self, new_folder: str, expect_root: str, title: str = "") -> str:
        """Move every profile and mod to new_folder as a writing job (cancelling it stops the move with nothing
        changed); returns its id. expect_root: the profiles folder the client saw (stale when it changed)."""
        self.check_relocate(new_folder)
        if str(load_settings().profiles_root or "") != expect_root:
            raise OperationError("stale", "Things changed since you were asked. Ask again.")
        new = Path(new_folder)

        def work(ctx: JobContext, loc: Locations) -> int:
            layout_service.relocate(loc, new, cancel=ctx.cancelled)
            return 0

        return self._layout_job(work, title or "Moving profiles and mods...")

    def check_move_all(self) -> list[str]:
        """The names of this game's me3 profiles outside Bayle's folder. Raises busy, game_running, nothing_to_move."""
        self._free()
        found = layout_service.plain_profiles(self._loc())
        if not found:
            raise OperationError("nothing_to_move", "No profiles are outside Bayle's folder.")
        return [f.stem for f in found]

    def move_all(self, expect: list[str], title: str = "") -> str:
        """Move those profiles in as a writing job (its result: {"count": n}); returns its id. expect: the names the
        client confirmed (stale when the list changed)."""
        if self.check_move_all() != list(expect):
            raise OperationError("stale", "Things changed since you were asked. Ask again.")
        found = layout_service.plain_profiles(self._loc())
        return self._layout_job(lambda _ctx, loc: layout_service.move_all(loc, found), title or "Moving profiles...")

    def _layout_job(self, work: Callable[[JobContext, Locations], int], title: str) -> str:
        """work(ctx, loc) as a logged job of its own inside a writing manager job (its log and Undo as before)."""
        loc = self._loc()

        def job(ctx: JobContext) -> dict:
            return {"count": run_job_value(lambda _l, loc: work(ctx, loc), loc, title)}

        return self._jobs.start(job, title=title)

    # ---- the game's leftover copies
    def clear_leftovers(self, title: str = "") -> str:
        """Close the hidden copies of the game left running, as a job; returns its id. Allowed while the game runs
        (that is when it is needed), not beside another writing job. Raises busy."""
        if self._jobs.busy:
            raise OperationError("busy", "Wait for the current job.")
        loc, title = self._loc(), title or "Clearing leftover processes..."

        def job(_ctx: JobContext) -> dict:
            run_job_value(play_service.job_clear, loc, title)
            return {}

        return self._jobs.start(job, title=title, writes=False)
