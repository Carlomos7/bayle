"""Overhaul configs: one TOML file per overhaul mod (data/overhauls/*.toml, or the local folder) saying how to
recognise it and how the launcher builds it, as a Pydantic model.

An overhaul is a mod that must load after the others and ships merged copies of game files other mods also change
(a mod that rebuilds merged files). Its config has two parts:

    recognise   how the launcher knows it is there: its own folder beside the me3 profile (or in the game folder),
                its installer's manifest in that folder, the profile entries that mean a setup includes it, and the
                text that marks its profile entries (an offline launch can switch those off)
    builds      what the launcher can build itself, one per edition: how to recognise that edition's download and
                which versions it was written for, and the steps that build its output from the packages before it
                (the steps mods.engine runs, none of them a program of the mod's; docs/Overhaul configs.md); where
                its download's files go in the launcher's layout (sources by role, runtime; overhauls.sources);
                and, optionally, what installing that edition does to the me3 profile (install;
                overhauls.install_plan works out the changes, nothing here writes a profile)

The shipped configs are in data/overhauls; a file in the local folder (overhauls/ in the launcher's data folder) with
the same id replaces the shipped one, and one with a new id adds an overhaul. A file that does not read or does not
fit the model is left out, and problems() says why.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from pydantic_core import ErrorDetails

from roundtable_souls.resources import DATA_DIR

SHIPPED_DIR = DATA_DIR / "overhauls"
RECIPE_VERSION = 2  # the step format mods.engine reads (1: the former data/recipes JSON, with the mod's tool)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# ----------------------------------------------------------------------------- recognising it
class Recognise(_Strict):
    folder: str  # its own folder, beside the me3 profile (or in the game folder: an edition that installs there)
    manifest: str  # its installer's manifest in that folder; a Play setup started from such a file includes it
    mod_ids: list[str] = Field(default_factory=list)  # profile entries (lower-case ids) meaning a setup includes it
    profile_marks: list[str] = Field(default_factory=list)  # text in a profile entry that marks it as this overhaul's
    # What its own installer leaves beside the profile besides its folder (its setup copy, say): offered for removal,
    # with their sizes, when its setup is removed. Never written by the launcher.
    installer_folders: list[str] = Field(default_factory=list)
    # Its installer's backups of the profiles it changed: the only copy from before it; offered last and separately.
    installer_backups: str | None = None


# ----------------------------------------------------------------------------- recognising a download
class JsonEquals(_Strict):
    file: str
    key: str
    equals: str | int | bool


class VersionKey(_Strict):
    file: str
    key: str


class Match(_Strict):
    files: list[str] = Field(default_factory=list)  # must all be in the download
    json_: list[JsonEquals] = Field(default_factory=list, alias="json")  # values its JSON files must have
    version: VersionKey | None = None  # where the download says its version
    versions: list[str] = Field(default_factory=list)  # the versions this build was written for (empty: any)


class Output(_Strict):
    mod: str = "mod"  # the package's folder name inside the output
    report: str = "merge-report.txt"
    manifest: str = "overhaul.json"


# ----------------------------------------------------------------------------- steps
class Each(_Strict):
    folders_in: str | None = None  # the step runs once per folder in here ({each})
    game: Literal["languages"] | None = None  # or once per entry of this list of the game's data (game/config.py)
    except_: list[str] = Field(default_factory=list, alias="except")

    @model_validator(mode="after")
    def _one_source(self) -> Each:
        if (self.folders_in is None) == (self.game is None):
            raise ValueError("each names either folders_in or game")
        return self


class CopyTree(_Strict):
    do: Literal["copy_tree"]
    from_: str = Field(alias="from")
    to: str


class Copy(_Strict):
    do: Literal["copy"]
    from_: str = Field(alias="from")
    to: str


class KeepConfig(_Strict):
    do: Literal["config"]
    from_: str = Field(alias="from")  # the download's default
    to: str  # the player's file: kept, with only the keys a newer default adds


class Params(_Strict):
    do: Literal["params"]
    file: str
    patch: str
    each: Each | None = None


class Merge(_Strict):
    do: Literal["merge"]
    file: str
    patch: str
    each: Each | None = None


class AddText(_Strict):
    do: Literal["text"]
    file: str
    table: str
    texts: dict[str, str]  # {each} folder (or "*") -> the mod's strings, a JSON object of text ID to string
    each: Each | None = None


class Hook(_Strict):
    """A mod's script fragment added to the entry script (overhauls.hooks): the packages' own script folder copied
    in load order, then the fragment appended to the entry file (the last package's copy, else the download's base).
    Several hooks for one entry are appended in the order of the steps, each wrapping the one before."""

    do: Literal["hook"]
    folder: str  # the script folder, for example action/script
    entry: str  # the entry script in it, for example c0000.hks
    base: str  # the download's copy of the entry script, used when no package ships one
    base_until: str | None = None  # the base is cut before this text (the mod's own hook already in it)
    fragment: str  # the download's file appended
    markers: list[str] = Field(default_factory=list)  # text meaning a script already contains the fragment
    refuse_text: str | None = None  # the refusal then
    # functions the mod's own DLL gives the script ("ExampleNative", or a prefix "Example*"): its calls of them are not
    # reported as undefined (overhauls.hks_check); only a mod's own config names them
    natives: list[str] = Field(default_factory=list)


class Remove(_Strict):
    do: Literal["remove"]
    glob: str


Step = Annotated[
    CopyTree | Copy | KeepConfig | Params | Merge | AddText | Hook | Remove,
    Field(discriminator="do"),
]


# ----------------------------------------------------------------------------- installing it into a profile
class Requirement(_Strict):
    """Another mod the overhaul needs in the profile, present and switched on: a DLL (native, its file name) or a
    package (its id). The build is refused without it; an install switches it on when it is there but off and
    enable_if_off allows it, else adds the first of candidates that exists, else stops."""

    native: str | None = None  # a DLL's file name
    package: str | None = None  # a package's id
    label: str | None = None  # how messages name it ("Seamless Co-op"); else its file name or id
    enable_if_off: bool = False  # an install may switch it on (pointed at the copy found) when it is off
    # Where an install looks for a copy when the profile has none switched on, in order; {profile_dir} and
    # {game_dir} are filled in.
    candidates: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_kind(self) -> Requirement:
        if (self.native is None) == (self.package is None):
            raise ValueError("a requirement names either native or package")
        return self

    @property
    def kind(self) -> Literal["native", "package"]:
        return "native" if self.native is not None else "package"

    @property
    def name(self) -> str:
        return self.native if self.native is not None else str(self.package)

    def shown(self) -> str:
        """How messages name it: "Seamless Co-op (ersc.dll)", or just its name without a label."""
        return f"{self.label} ({self.name})" if self.label else self.name


class Initializer(_Strict):
    function: str  # the DLL's function me3 calls after loading it


class InstallNative(_Strict):
    """A DLL entry the install adds, with its load settings exactly as the overhaul's installer writes them."""

    file: str  # in the overhaul's own folder
    load_early: bool | None = None
    initializer: Initializer | None = None
    after_enabled_natives: bool = False  # load_after every enabled DLL already in the profile, each optional


class InstallPackage(_Strict):
    id: str
    folder: str = "mod"  # in the overhaul's own folder
    after_enabled_packages: bool = False  # load_after every enabled package already in the profile, each optional


class SetInitializer(_Strict):
    """An initializer the install gives other mods' DLLs that have none (a companion mod the overhaul knows)."""

    name_prefix: str  # DLL file names starting with this, case aside
    function: str


class Install(_Strict):
    """What installing one edition does to the me3 profile it is installed into (its own folder beside it)."""

    profile_settings: dict[str, str | int | bool] = Field(default_factory=dict)  # top-level keys set
    owned_package_ids: list[str] = Field(default_factory=list)  # earlier installs' entries, removed first
    owned_dlls: list[str] = Field(default_factory=list)  # DLL file names (lower-case), removed first
    set_initializers: list[SetInitializer] = Field(default_factory=list)
    natives: list[InstallNative] = Field(default_factory=list)  # added after the profile's own, in this order
    package: InstallPackage | None = None  # added after the profile's own
    required_files: list[str] = Field(default_factory=list)  # in its folder, after a build (its check)
    required_folders: list[str] = Field(default_factory=list)  # in its folder, not empty


class Build(_Strict):
    """One edition the launcher builds itself."""

    id: str  # written into the build's manifest (as "recipe") and its build key
    match: Match
    output: Output
    steps: list[Step]
    requires: list[Requirement] = Field(default_factory=list)  # other mods it needs, present and switched on
    install: Install | None = None  # what installing it does to the profile; None: the launcher does not install it
    # The download in the launcher's layout (overhauls.sources): path pattern -> "<role>/<path>" for what its builds
    # read, path pattern -> path in its own folder for what it runs with; "" leaves a file out.
    sources: dict[str, str] = Field(default_factory=dict)
    runtime: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _layout(self) -> Build:
        from roundtable_souls.overhauls import sources

        found = sources.problems(self.sources, roles=True) + sources.problems(self.runtime, roles=False)
        if found:
            raise ValueError("; ".join(found))
        return self


# ----------------------------------------------------------------------------- the basic level
class BasicNative(_Strict):
    """One of the mod's DLLs, as the Overhaul setup form sets it."""

    file: str  # its path in the mod's folder
    load_early: bool = False
    initializer: str | None = None  # the function me3 calls after loading it
    after_others: bool = True  # loads after every other enabled DLL in the profile


def _inside(path: str) -> str:
    """The path when it is relative and stays inside its folder (no .., drive letter or leading slash)."""
    p = path.replace("\\", "/")
    if not p or p.startswith("/") or ":" in p or ".." in p.split("/"):
        raise ValueError(f"{path!r} must be a path inside the mod's folder (no .., drive letter or leading slash)")
    return path


class BasicText(_Strict):
    """Strings of a JSON file (text ID to string) set in a table of a message binder, merged on top of the packages
    before it: becomes a "text" step."""

    file: str  # the binder's game path; {each} is every text language of the game
    table: str = ""  # the table in it (any case), for example EventTextForTalk.fmg; "" until the form's choice
    texts: dict[str, str]  # language folder (or "*" for the rest) -> the JSON file in the mod's folder

    @field_validator("file")
    @classmethod
    def _file_inside(cls, v: str) -> str:
        return _inside(v)

    @field_validator("texts")
    @classmethod
    def _texts_inside(cls, v: dict[str, str]) -> dict[str, str]:
        for name in v.values():
            _inside(name)
        return v


class Basic(_Strict):
    """What the Overhaul setup form sets (overhauls.basic derives the rest of the config from it and the mod's
    files). The config's recognise and builds are written beside it; it loads last whatever is set here."""

    version: str | None = None  # the label shown (from the archive's name or the form); nothing depends on it
    natives: list[BasicNative] = Field(default_factory=list)
    keep: list[str] = Field(default_factory=list)  # settings files the player keeps on updates
    not_merged: list[str] = Field(default_factory=list)  # binders used whole instead of merged
    # Files outside the game folders meant for a game path: file in the mod's folder -> the game path it is merged
    # at (copied there when it is in not_merged or is not a binder).
    place: dict[str, str] = Field(default_factory=dict)
    texts: list[BasicText] = Field(default_factory=list)  # text lists set in the game's message binders
    skip: list[str] = Field(default_factory=list)  # files or folders of the download left out
    # What the Files table of the form sets for a file where it differs from what the setup does by itself:
    # merge | whole | keep | copy | leave | place:<game path>. It wins over keep, not_merged, place and skip above,
    # which the form no longer writes (an older file, or a proposal, may still have them).
    files: dict[str, str] = Field(default_factory=dict)


# ----------------------------------------------------------------------------- the config
class OverhaulConfig(_Strict):
    overhaul: Literal[1]  # the version of this format
    id: str
    label: str
    short_label: str  # where space is short (the Play page's summary)
    game: str  # the game's key (data/games, game.catalog)
    recognise: Recognise
    builds: list[Build] = Field(default_factory=list)
    # Editions its installer knows that the launcher does not install, and why (edition -> reason).
    install_unsupported: dict[str, str] = Field(default_factory=dict)
    # The Overhaul setup form's values, for a config made with it (None: written by hand, or a shipped one).
    basic: Basic | None = None

    def recipe(self, build: Build) -> dict:
        """One build in the shape mods.engine reads (the former data/recipes JSON). Only what the file sets is
        included, so a build's key stays the same for the same file."""
        steps = [s.model_dump(by_alias=True, exclude_unset=True) for s in build.steps]
        out = {
            "recipe": RECIPE_VERSION,
            "id": build.id,
            "label": self.label,
            "match": build.match.model_dump(by_alias=True, exclude_unset=True),
            "output": build.output.model_dump(by_alias=True, exclude_unset=True),
            "steps": steps,
        }
        if build.requires:
            out["requires"] = [r.model_dump(exclude_unset=True) for r in build.requires]
        return out


def recipe_sha256(recipe: dict) -> str:
    """What a build records of its overhaul's config: a sha256 of the build as mods.engine reads it (OverhaulConfig.
    recipe), so a change to what the build does makes it out of date, and a comment or an install setting does not."""
    return hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ----------------------------------------------------------------------------- loading
_problems: list[str] = []
_origins: dict[str, Path] = {}  # config id -> the file the last load() took it from


def local_dir() -> Path | None:
    """The local folder (overhauls/ in the launcher's data folder), or None before the data folder is set."""
    from roundtable_souls.platform import data_folder

    try:
        return data_folder.data_root() / "overhauls"
    except RuntimeError:
        return None


def read(path: Path) -> OverhaulConfig:
    """One config file. Raises ValueError (tomllib's and Pydantic's errors are ValueErrors) or OSError."""
    return OverhaulConfig.model_validate(tomllib.loads(Path(path).read_text(encoding="utf-8")))


def load(game: str | None = None) -> list[OverhaulConfig]:
    """Every usable config, shipped then local (a local one replaces the shipped one with its id), for one game when
    given. Files that do not read or fit are left out; problems() lists them."""
    found: dict[str, OverhaulConfig] = {}
    _problems.clear()
    _origins.clear()
    for folder in (SHIPPED_DIR, local_dir()):
        if folder is None or not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.toml")):
            try:
                cfg = read(f)
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(x) for x in first["loc"])
                _problems.append(f"{f}: {where}: {first['msg']}" + _moved(first))
                continue
            except (OSError, ValueError) as e:
                _problems.append(f"{f}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
                continue
            found[cfg.id] = cfg
            _origins[cfg.id] = f
    return [c for c in found.values() if game is None or c.game == game]


# Keys an earlier version of the format had, and where they went (said when a file still uses one).
_MOVED = {
    "seamless": "since 3.20 a required mod is listed in the build's requires",
    "script_append": 'since 3.20 a script fragment is added with do = "hook" (append is fragment, refuse is markers)',
}


def _moved(error: ErrorDetails) -> str:
    hits = [str(x) for x in error["loc"]] + [str(error.get("input"))]
    for key, why in _MOVED.items():
        if any(h == key for h in hits) or f"'{key}'" in error.get("msg", ""):
            return f" ({key}: {why})"
    return ""


def origin(config_id: str) -> Path | None:
    """The file the last load() took the config with this id from."""
    return _origins.get(config_id)


def verified(config_id: str) -> bool:
    """A shipped config not replaced by a local one ("verified"); a local one is the player's ("your config, not
    verified")."""
    found = _origins.get(config_id)
    return found is not None and found.parent == SHIPPED_DIR


def problems() -> list[str]:
    """Why config files were left out by the last load()."""
    return list(_problems)


def schema() -> dict:
    return OverhaulConfig.model_json_schema(by_alias=True)


def schema_path() -> Path:
    return DATA_DIR / "schemas" / "overhaul.schema.json"


def write_schema() -> Path:
    """Regenerate data/schemas/overhaul.schema.json from the model (tests check they match)."""
    path = schema_path()
    path.write_text(json.dumps(schema(), indent=1) + "\n", encoding="utf-8", newline="\n")
    return path
