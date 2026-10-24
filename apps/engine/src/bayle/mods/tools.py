"""The contract between the rebuild workflows (mods.rebuild) and the concrete rebuild tools (mods.backends): a Recipe
describes how to run one tool and read what it did; a Tool is what the workflows call. A tool's concrete parts (finding
it, running its command) live in mods.backends and never import a workflow; what an engine build needs from the
workflow side is handed in as an EngineHost.

A Tool offers: label, package, own_folders(), merges(), sources(), input_reasons(), report_time(), problem(),
approval_key(), legacy_approval_key(), describe() and run(log).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


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
    engine: object = None  # the launcher builds it from a recipe instead (mods.engine): called with log


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
    """What the launcher's own build (mods.engine) needs from the workflow side, handed in by whoever starts it: the
    journaled operation it swaps a build in under (start, commit) and the way folders are compared."""

    start: Callable[[Path, str], Any]
    commit: Callable[[Any], None]
    same_folder: Callable[[Path, Path], bool]
