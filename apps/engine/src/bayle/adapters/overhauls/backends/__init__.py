"""Rebuild tools: programs that fold the parameter file (and other shared files) of earlier packages into the package
that must stay last. The launcher only finds, runs and checks them; it never merges files itself.

Every tool is described the same way, as a Recipe: the command to run, the files it combines, where it writes the
list of sources it used (path + sha256 of each input) and which folders are its own. Adapters build a Recipe from the
files next to a package, never from a mod's name:

    declared          a rebuild.json the package (or the user, in Options) provides; see docs/Rebuild tools.md
    launcher_build    the launcher's own build of an overhaul it installed (mods.engine); nothing from a download runs

A CommandTool wraps a Recipe as the Tool contract (mods.tools) asks: label, package, own_folders(), merges(), sources(),
input_reasons(), report_time(), problem(), approval_key(), describe() and run(log).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.modules.mods.models import EngineError
from bayle.modules.mods.tools import BackendError, EngineHost, Recipe, Tool

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations


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


def read_sources(file: Path) -> list[dict] | None:
    """[{path, sha256}] from a JSON file that is either {"sources": [...]} or the list itself; None without one."""
    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    rows = data.get("sources") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return None
    out = [
        {"path": str(s["path"]), "sha256": str(s["sha256"]).lower()}
        for s in rows
        if isinstance(s, dict) and s.get("path") and s.get("sha256")
    ]
    return out or None


def program_fingerprint(program: str, cwd: Path | str = "") -> str:
    """The sha256 of the tool's program file (relative to cwd when not absolute), or "" when it is not a file (a
    command on PATH, an interpreter's name). Cached by path, size and modification time."""
    if not program:
        return ""
    path = Path(program)
    if not path.is_absolute() and cwd:
        path = Path(cwd) / path
    try:
        st = path.stat()
    except OSError:
        return ""
    if not path.is_file():
        return ""
    return _file_sha256(str(path.resolve()), st.st_size, st.st_mtime_ns)


PROGRAM_SUFFIXES = frozenset(
    {".exe", ".com", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".js", ".py", ".pyw", ".sh", ".jar", ".dll", ".lua"}
)  # files a command runs (a program, or a script an interpreter runs), as opposed to the data it is given


def command_fingerprint(command: list[str], cwd: Path | str = "") -> str:
    """The fingerprints of the program and of every element of the command that is a program or script file
    (PROGRAM_SUFFIXES; relative to cwd, or absolute), in order and joined. Data the command is given (the profile,
    the files it merges) is left out: it changes with every rebuild and is not the tool."""
    parts = [p for i, p in enumerate(command) if i == 0 or Path(p).suffix.lower() in PROGRAM_SUFFIXES]
    return "|".join(f for f in (program_fingerprint(part, cwd) for part in parts) if f)


@lru_cache(maxsize=64)
def _file_sha256(path: str, size: int, mtime_ns: int) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class CommandTool:
    """A rebuild tool: a Recipe's command run as a subprocess, or the launcher's own build."""

    def __init__(self, recipe: Recipe):
        self.recipe = recipe
        self.label = recipe.label
        self.package = recipe.package

    def own_folders(self) -> list[Path]:
        """Its own folders, never the profile's folder or one holding it (a rebuild.json kept in Documents, say):
        that would hide every package's files."""
        import os

        def canon(x: Path) -> Path:
            return Path(os.path.normcase(os.path.abspath(x)))

        profile_dir = canon(self.recipe.profile.parent)
        return [p for p in self.recipe.own if p is not None and canon(p) not in (profile_dir, *profile_dir.parents)]

    def merges(self) -> set[str]:
        return set(self.recipe.merges)

    def sources(self) -> list[dict] | None:
        return read_sources(self.recipe.sources_file)

    def input_reasons(self) -> list[str]:
        """Why the launcher's own build is out of date beyond its sources (the game updated, its config changed; see
        mods.engine.input_reasons). Empty for a tool's own run."""
        check = getattr(self.recipe.engine, "reasons", None)
        if check is None:
            return []
        try:
            data = json.loads(self.recipe.sources_file.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return []
        return check(data) if isinstance(data, dict) else []

    def report_time(self) -> float:
        try:
            return self.recipe.sources_file.stat().st_mtime
        except OSError:
            return 0.0

    def problem(self) -> str | None:
        return self.recipe.problem

    def approval_key(self) -> str:
        """What the user's permission is kept under: the recipe's approval text, the program and its folder, and the
        fingerprint of every file the command names (the program, and a script an interpreter runs: python tool.py,
        a .bat, powershell -File x.ps1), so a new version of the tool is asked about again (once per tool version)."""
        r = self.recipe
        program = r.command[0] if r.command else ""
        return hashlib.sha256(
            f"{r.approval}|{program}|{r.cwd}|{command_fingerprint(r.command, r.cwd)}".lower().encode()
        ).hexdigest()

    def legacy_approval_key(self) -> str:
        """The key permissions were kept under before 3.22 (no program fingerprint); read once, then replaced."""
        r = self.recipe
        return hashlib.sha256(f"{r.approval}|{r.command[0] if r.command else ''}|{r.cwd}".lower().encode()).hexdigest()

    def describe(self) -> str:
        """The command as it will run, for the one-time question before a tool runs."""
        if self.recipe.engine is not None:
            return getattr(self.recipe.engine, "describe", "the launcher builds it from its download")
        shown = " ".join(f'"{c}"' if " " in c else c for c in self.recipe.command)
        return f"{shown}\nin {self.recipe.cwd}"

    def run(self, log) -> None:
        from bayle.adapters.system.proc import NO_WINDOW

        r = self.recipe
        if r.problem:
            raise BackendError(r.problem)
        if r.engine is not None:
            try:
                r.engine(log)
            except EngineError as e:
                raise BackendError(str(e)) from e
            return
        log(f"rebuild tool: {self.describe()}")
        tail: list[str] = []
        start = time.time()
        try:
            proc = subprocess.Popen(
                r.command,
                cwd=str(r.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW,
            )
        except OSError as e:
            raise BackendError(f"{self.label} could not start: {e}") from e
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                log(f"  {line}")
                tail = (tail + [line])[-6:]
            if time.time() - start > r.timeout:
                proc.kill()
                raise BackendError(f"{self.label} took longer than {r.timeout // 60} minutes and was stopped.")
        code = proc.wait()
        if code != 0:
            raise BackendError(f"{self.label} stopped (exit {code}): " + (" ".join(tail[-2:]) or "no output"))


def _adapters():
    from bayle.adapters.overhauls.backends import declared, launcher_build

    return (declared, launcher_build)


def detect(profile: Path, packs: list[dict], *, loc: Locations, host: EngineHost) -> Tool | None:
    """The rebuild tool that writes into one of these packages (checked from the last), or None. loc: the game's
    locations (a tool's command names the game and me3); host: what the launcher's own build needs from the workflow."""
    for layer in reversed(packs):
        for kind in _adapters():
            recipe = kind.recipe(Path(profile), layer, loc=loc, host=host)
            if recipe is not None:
                return CommandTool(recipe)
    return None


def detect_for(
    profile: Path, layer: dict, rebuild_file: Path | None = None, *, loc: Locations, host: EngineHost
) -> Tool | None:
    """The rebuild tool of a package the user set as the parameter overlay: from the rebuild.json they picked, else
    the one found beside the package, or None."""
    from bayle.adapters.overhauls.backends import declared

    if rebuild_file is not None:
        recipe = declared.recipe(Path(profile), layer, file=Path(rebuild_file), loc=loc, host=host)
        return CommandTool(recipe) if recipe is not None else None
    for kind in _adapters():
        recipe = kind.recipe(Path(profile), layer, loc=loc, host=host)
        if recipe is not None:
            return CommandTool(recipe)
    return None


def combine():
    """The launcher's own Combine (backends.builtin), for the workflows that look for it or read its files."""
    from bayle.adapters.overhauls.backends import builtin

    return builtin
