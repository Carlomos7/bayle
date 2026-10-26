"""The contract between the rebuild workflows (mods.rebuild) and the concrete rebuild tools (adapters.overhauls.backends):
a Recipe describes how to run one tool and read what it did; a Tool is what the workflows call. A tool's concrete parts
(finding it, running its command) live in the backends and never import a workflow; what an engine build needs from the
workflow side is handed in as an EngineHost. The workflows reach the backends and the launcher's own build engine only
through the functions at the bottom, which call whatever the runtime bound (bayle.runtime.bootstrap.bind_ports).

A Tool offers: label, package, own_folders(), merges(), sources(), input_reasons(), report_time(), problem(),
approval_key(), legacy_approval_key(), describe() and run(log).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations


# What the launcher's own build keeps beside its output and which files it takes for licence notices (pure rules).
WORK = ".roundtable-build"  # beside the output: the previous build and its restore.json
NOTICE_NAMES = re.compile(r"(?i)^(licen[cs]e|notice|copying|third[-_ ]?party[-_ ]?notices?)\b")
NOTICE_FOLDERS = {"licenses", "licences"}


def local_path(path: str | Path, profile: Path, game_dir: Path | None = None) -> Path:
    """A path a tool wrote down, on this PC. Its list may have been written on another PC or user account, so a
    path that is not here is looked for below this profile's folder (by the part after the profile folder's name)
    and below the game folder (by the part after Game). Otherwise it is returned as written."""
    p = Path(str(path).replace("\\", "/"))
    if p.exists():
        return p
    parts = [x.lower() for x in p.parts]
    here = Path(profile).parent
    name = here.name.lower()
    if name in parts:
        at = len(parts) - 1 - parts[::-1].index(name)
        return here.joinpath(*p.parts[at + 1 :])
    if game_dir is not None and "game" in parts:
        at = len(parts) - 1 - parts[::-1].index("game")
        return Path(game_dir).joinpath(*p.parts[at + 1 :])
    return p


class BackendError(RuntimeError):
    pass


@dataclass
class Recipe:
    """How to run one rebuild tool and read what it did."""

    label: str
    package: dict  # the layer it writes into (see merge.layers)
    profile: Path
    command: list[str]
    cwd: Path
    sources_file: Path
    merges: set[str] = field(default_factory=set)  # relative to the package, lower-case
    own: list[Path] = field(default_factory=list)  # its own folders: sources there are not packages
    approval: str = ""  # changes when the tool changes, so a new version is asked about again
    problem: str | None = None  # why it cannot run on this PC now
    timeout: int = 1800
    engine: object = None  # the launcher builds it from a recipe instead (adapters.overhauls.engine): called with log


class Tool(Protocol):
    """A rebuild tool as mods.rebuild sees it."""

    label: str
    package: dict

    def own_folders(self) -> list[Path]: ...

    def merges(self) -> set[str]: ...

    def sources(self) -> list[dict] | None: ...

    def input_reasons(self) -> list[str]: ...

    def report_time(self) -> float: ...

    def problem(self) -> str | None: ...

    def approval_key(self) -> str: ...

    def legacy_approval_key(self) -> str: ...

    def describe(self) -> str: ...

    def run(self, log) -> None: ...


@dataclass(frozen=True)
class EngineHost:
    """What the launcher's own build (adapters.overhauls.engine) needs from the workflow side, handed in by whoever
    starts it: the journaled operation it swaps a build in under (start, commit) and the way folders are compared."""

    start: Callable[[Path, str], Any]
    commit: Callable[[Any], None]
    same_folder: Callable[[Path, Path], bool]


# ----------------------------------------------------------------------------- what the runtime binds
# Unbound until bayle.runtime.bootstrap.bind_ports() points them at adapters.overhauls.backends and .engine.
_BACKENDS: Any = None
_ENGINE: Any = None


def _bound(slot: Any, what: str) -> Any:
    if slot is None:
        raise RuntimeError(f"The {what} is not bound: call bayle.runtime.bootstrap.bind_ports() first.")
    return slot


def detect(profile: Path, packs: list[dict], *, loc: Locations, host: EngineHost) -> Tool | None:
    return _bound(_BACKENDS, "tool backends").detect(profile, packs, loc=loc, host=host)


def detect_for(
    profile: Path, layer: dict, rebuild_file: Path | None = None, *, loc: Locations, host: EngineHost
) -> Tool | None:
    return _bound(_BACKENDS, "tool backends").detect_for(profile, layer, rebuild_file, loc=loc, host=host)


def combine() -> Any:
    """The launcher's own Combine (its find, shared_files, history_root and constants), for the workflows that look
    for it or read its files."""
    return _bound(_BACKENDS, "tool backends").combine()


def match(setup: Path | None, among: list[dict] | None = None) -> tuple[dict | None, str | None, str | None]:
    return _bound(_ENGINE, "launcher build engine").match(setup, among)


def build(*args: Any, **kwargs: Any) -> dict:
    return _bound(_ENGINE, "launcher build engine").build(*args, **kwargs)
