"""The launcher's own build of an overhaul it installed: the manifest it keeps beside the package says so
(INSTALLED_BY), the download copy is in the launcher's sources folder, and the launcher builds from it
(mods.engine). A manifest written by another installer is not this adapter's: nothing of a download runs, and such a
setup is left as it is."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.mods.backends import Recipe
from bayle.mods.overhaul_manifest import LEGACY_MANIFEST, MANIFEST, find_setup, launcher_installed

if TYPE_CHECKING:
    from bayle.game.locate import Locations


def _read(manifest: Path) -> dict | None:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("sources"), list):
        return None
    return data


def recipe(profile: Path, layer: dict, *, loc: Locations) -> Recipe | None:
    """The launcher's build of a package it installed (its manifest with INSTALLED_BY), else None."""
    folder = Path(layer["folder"])
    for cand, name in ((c, n) for c in (folder, folder.parent) for n in (MANIFEST, LEGACY_MANIFEST)):
        manifest = cand / name
        if manifest.is_file():
            data = _read(manifest)
            if data is not None and launcher_installed(data):
                return _recipe(Path(profile), layer, manifest, data, loc)
    return None


def _recipe(profile: Path, layer: dict, manifest: Path, data: dict, loc: Locations) -> Recipe:
    setup = find_setup(profile, data)
    matched = engine_match(setup)
    built = _engine(profile, layer, setup, loc)
    problem = None
    if setup is None:
        problem = (
            f"The launcher's copy of {layer['name']}'s download is gone, so it can't be rebuilt. Install it again "
            "with the launcher, or remove it."
        )
    elif built is None:
        problem = (
            f"{layer['name']} was installed by the launcher, but none of the launcher's overhaul configs fits its "
            "download any more. Install it again with the launcher, or remove it."
        )
    engine_problem, run, approval = built or (None, None, f"engine|{setup}")
    return Recipe(
        label=f"the launcher's build of {layer['name']}",
        package=layer,
        profile=profile,
        command=[],
        cwd=setup or manifest.parent,
        sources_file=manifest,
        merges=_merges(matched),
        own=[p for p in (manifest.parent, setup) if p is not None],
        approval=approval,
        problem=problem or engine_problem,
        engine=run,
    )


def _merges(recipe: dict | None) -> set[str]:
    """The game files the build's steps combine (lower-case, relative to the package), from the recipe itself.
    shortcut: a step repeated with `each` is not listed, only the files its sources name are checked."""
    out: set[str] = set()
    for s in (recipe or {}).get("steps") or []:
        if s.get("do") in ("merge", "params") and s.get("file") and "{" not in s["file"]:
            out.add(str(s["file"]).replace("\\", "/").lower())
        elif s.get("do") == "hook" and s.get("folder") and s.get("entry"):
            out.add(f"{s['folder']}/{s['entry']}".replace("\\", "/").lower())
    return out


class _Build:
    """What Tool.run calls when the launcher builds the mod itself (mods.engine)."""

    def __init__(self, profile: Path, layer: dict, setup: Path, recipe: dict, version: str, loc: Locations):
        self.profile, self.layer, self.setup, self.recipe, self.version = profile, layer, setup, recipe, version
        self.loc = loc
        self.describe = (
            f"The launcher builds {recipe['label']} {version} itself from its download in {setup.name} "
            f"({recipe['id']}); nothing from the download runs."
        )

    def __call__(self, log):
        from bayle.mods import engine

        engine.build(self.profile, Path(self.layer["folder"]), self.setup, self.recipe, self.version, log, loc=self.loc)

    def reasons(self, manifest: dict) -> list[str]:
        """Why the build its manifest records is out of date beyond its sources (mods.engine.input_reasons)."""
        from bayle.mods import engine

        return engine.input_reasons(manifest, self.recipe, self.loc)


def engine_match(setup: Path | None) -> dict | None:
    from bayle.mods import engine

    return engine.match(setup)[0]


def _engine(profile: Path, layer: dict, setup: Path | None, loc: Locations):
    """(problem, the build to run, approval key) when a recipe fits the download; None otherwise."""
    from bayle.mods import engine

    if setup is None:
        return None
    recipe, version, _why = engine.match(setup)
    if recipe is None:
        return None
    game_dir = loc.game_dir()
    problem = None if game_dir and Path(game_dir).is_dir() else "The game was not found."
    return problem, _Build(profile, layer, setup, recipe, version or "", loc), f"engine|{setup}|{recipe['id']}"
