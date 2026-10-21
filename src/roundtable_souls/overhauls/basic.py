"""The basic level of an overhaul config: what the Overhaul setup form sets ([basic] in the TOML), and the whole
config derived from it and the mod's own files, so a mod no shipped config describes can be set up as an overhaul
without anyone writing build steps (docs/Overhaul configs.md, "Basic").

What each of the mod's files becomes (make):

    regulation.bin                      params: combined on top of the packages before it
    a binder in a game folder (*bnd.dcx) merge: merged on top of the last package before it that ships it, or used
                                        whole when none does (the form can untick one: then copied whole)
    any other file in a game folder     copied into its package (mod/<path>)
    a settings file the form keeps      config: the player's copy kept on updates, new keys added
    a file the form places              a file outside the game folders meant for a game path (Basic.place): merged
                                        there like a binder in a game folder, or copied (the form can untick it)
    anything else                       copied into its own folder at the same path (its DLLs, their data)
    installers, .me3, empty files       left out: nothing of the mod's runs, and a profile is the player's

A download whose game files sit in one top folder (payload/mod/..., whatever the folder is called) is read with that
folder as the package root: its paths are the game's own paths. Files listed in Basic.skip are left out.

The derived parts ([recognise] and the one [[builds]], whose id is the config's id) are written into the TOML with
[basic] when the form saves it, so everything else reads it like any config. A config whose derived parts no longer
equal what make() gives (its steps edited by hand) is at the advanced level.
"""

from __future__ import annotations

from pathlib import Path

from roundtable_souls.game import catalog as games
from roundtable_souls.game import config as game_config
from roundtable_souls.overhauls.config import (
    Basic,
    BasicNative,
    Build,
    Copy,
    Initializer,
    Install,
    InstallNative,
    InstallPackage,
    KeepConfig,
    Match,
    Merge,
    Output,
    OverhaulConfig,
    Params,
    Recognise,
    Step,
)

INSTALLER_SUFFIXES = {".exe", ".cmd", ".bat", ".ps1", ".py"}  # a download that ships its own installer
SETTINGS_SUFFIXES = {".ini", ".toml", ".json", ".cfg", ".conf", ".yaml", ".yml", ".xml"}
MERGED_ENDING = "bnd.dcx"  # binders (anibnd, behbnd, partsbnd, msgbnd, talkesdbnd, ...): the merger reads them
PACKAGE = "mod"  # the package's folder inside the overhaul's own folder (Output.mod)
LAUNCHER_FOLDERS = {"packages", "natives", "builds", "mods", "mod", "profiles", "overhauls", "sources", "library"}
LAUNCHER_RECORD = (
    "roundtable.json"  # the launcher's own file at the top of its copy of a download (mods.library.RECORD)
)


def files_of(folder: Path) -> list[str]:
    """The mod's files a basic config can take, as forward-slash paths from its folder, sorted. Empty files are left
    out (a build refuses to leave one; shortcut: an empty marker file a mod needs is lost, add it as an advanced
    step if one ever matters)."""
    folder = Path(folder)
    out = []
    for p in folder.rglob("*"):
        if not p.is_file() or p.suffix.lower() in INSTALLER_SUFFIXES or p.suffix.lower() == ".me3":
            continue
        if p.name == LAUNCHER_RECORD and p.parent == folder:
            continue
        if p.stat().st_size:
            out.append(p.relative_to(folder).as_posix())
    return sorted(out, key=str.lower)


def _under(f: str, folder: str) -> bool:
    return f.lower().startswith(folder.lower().rstrip("/") + "/")


def package_root(files: list[str], folders: set[str], regulation: str) -> str:
    """The folder the mod's game files sit in, or "" when they sit at the top: up to two folders deep (payload/mod),
    none of them a game folder, holding game folders or the regulation. The shallowest wins (a folder of copies of the
    game's files deeper down is not it), then the one with the most files."""
    found: dict[str, tuple[int, int, str]] = {}  # lower-case folder -> (depth, minus files, as written)
    for f in files:
        parts = f.split("/")
        low = [p.lower() for p in parts]
        if low[0] == regulation or (len(parts) > 1 and low[0] in folders):
            return ""  # game files at the top: that is the root
        for depth in (1, 2):
            rest = low[depth:]
            if any(p in folders for p in low[:depth]) or not rest:
                break
            if (len(rest) > 1 and rest[0] in folders) or rest == [regulation]:
                key = "/".join(low[:depth])
                was = found.get(key, (depth, 0, "/".join(parts[:depth])))
                found[key] = (depth, was[1] - 1, was[2])
    return min(found.values())[2] if found else ""


def _mirrors(files: list[str], folders: set[str], root: str) -> tuple[dict[str, str], list[str]]:
    """Copies of the game's own files a download carries outside its game folders (a folder of base copies, laid out
    like the game): a loose binder with the name of exactly one file in such a folder is meant for that game path.
    Returns ({loose file: game path}, the copy folders, which nothing needs)."""
    mirrored: dict[str, dict[str, list[str]]] = {}  # folder -> file name -> game paths
    for f in files:
        if root and _under(f, root):
            continue
        parts = f.split("/")
        for i in range(1, len(parts) - 1):
            if parts[i].lower() in folders:
                mirrored.setdefault("/".join(parts[:i]), {}).setdefault(parts[-1].lower(), []).append(
                    "/".join(parts[i:])
                )
                break
    place: dict[str, str] = {}
    skip: list[str] = []
    for f in files:
        name, top = f.rsplit("/", 1)[-1].lower(), f.split("/")[0].lower()
        if not f.lower().endswith(MERGED_ENDING) or top in folders or (root and _under(f, root)):
            continue
        for folder, names in mirrored.items():
            if not _under(f, folder) and len(names.get(name, [])) == 1:
                place[f] = names[name][0]
                if folder not in skip:
                    skip.append(folder)
    return place, sorted(skip, key=str.lower)


def propose(folder: Path, version: str | None = None, game: str = "eldenring") -> Basic:
    """The form's starting values for a mod folder: its top-level DLLs with no special options, loading after the
    other DLLs; the settings files beside them kept on updates; a binder meant for a game path placed there (and the
    folder of game copies it was matched in left out)."""
    folder = Path(folder)
    gc = game_config.load(game)
    ignored = set(gc.ignored_dlls)
    dlls = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".dll" and p.name.lower() not in ignored),
        key=lambda p: p.name.lower(),
    )
    files = files_of(folder)
    keep = [] if not dlls else [f for f in files if "/" not in f and Path(f).suffix.lower() in SETTINGS_SUFFIXES]
    regulation = games.BY_KEY[game].regulation.lower() if game in games.BY_KEY else games.REGULATION
    folders = set(gc.mod_folders)
    place, skip = _mirrors(files, folders, package_root(files, folders, regulation))
    return Basic(version=version, natives=[BasicNative(file=p.name) for p in dlls], keep=keep, place=place, skip=skip)


def leaves(f: str, skip: list[str]) -> bool:
    return any(f.lower() == s.lower() or _under(f, s) for s in skip)


def _step(f: str, basic: Basic, folders: set[str], regulation: str, root: str) -> Step:
    """The step for one file of the download; f is its path there, the game's path is f without the package root."""
    low = f.lower()
    g = f[len(root) + 1 :] if root and _under(f, root) else f
    glow = g.lower()
    top = glow.split("/")[0]
    if glow == regulation:
        return Params(do="params", file=g, patch=f)
    if "/" in glow and top in folders:
        if glow.endswith(MERGED_ENDING) and low not in {n.lower() for n in basic.not_merged}:
            return Merge(do="merge", file=g, patch=f)
        return Copy(do="copy", **{"from": f}, to=f"{PACKAGE}/{g}")
    if low in {k.lower() for k in basic.keep}:
        return KeepConfig(do="config", **{"from": f}, to=f)
    if top == PACKAGE and "/" in low:
        raise ValueError(f"{f} is in a folder named {PACKAGE}, which is where the launcher puts the merged files.")
    return Copy(do="copy", **{"from": f}, to=f)


def _placed(f: str, to: str, basic: Basic) -> Step:
    if to.lower().endswith(MERGED_ENDING) and f.lower() not in {n.lower() for n in basic.not_merged}:
        return Merge(do="merge", file=to, patch=f)
    return Copy(do="copy", **{"from": f}, to=f"{PACKAGE}/{to}")


def make(
    *, id: str, label: str, game: str, basic: Basic, folder: Path, short_label: str | None = None
) -> OverhaulConfig:
    """The whole config for a mod folder at the basic level. Raises ValueError when there is nothing to set up or a
    file the form names is not in the folder."""
    if id.lower() in LAUNCHER_FOLDERS or id.startswith("."):
        raise ValueError(f"{id} is a name the launcher uses for its own folders; choose another.")
    gc = game_config.load(game)
    regulation = games.BY_KEY[game].regulation.lower() if game in games.BY_KEY else games.REGULATION
    folders = set(gc.mod_folders)
    files = [f for f in files_of(folder) if not leaves(f, basic.skip)]
    have = {f.lower() for f in files}
    for named in [*(n.file for n in basic.natives), *basic.place]:
        if named.lower() not in have:
            raise ValueError(f"{named} is not in the mod's folder.")
    taken: dict[str, str] = {}
    for src, to in basic.place.items():
        if to.lower() != regulation and not ("/" in to and to.lower().split("/")[0] in folders):
            raise ValueError(f"{src} is placed at {to}, which is not in one of the game's folders.")
        if to.lower() in taken:
            raise ValueError(f"{src} and {taken[to.lower()]} are both placed at {to}.")
        taken[to.lower()] = src
    placed = {k.lower(): v for k, v in basic.place.items()}
    root = package_root(files, folders, regulation)
    steps = [
        _placed(f, placed[f.lower()], basic) if f.lower() in placed else _step(f, basic, folders, regulation, root)
        for f in files
    ]
    if not steps:
        raise ValueError("The mod's folder has no files to set up.")
    in_package = any(s.do in ("params", "merge") or (s.do == "copy" and s.to.startswith(f"{PACKAGE}/")) for s in steps)
    dlls = [n.file.lower().rsplit("/", 1)[-1] for n in basic.natives]
    install = Install(
        owned_package_ids=[id] if in_package else [],
        owned_dlls=dlls,
        natives=[
            InstallNative(
                file=n.file,
                load_early=n.load_early or None,
                initializer=Initializer(function=n.initializer) if n.initializer else None,
                after_enabled_natives=n.after_others,
            )
            for n in basic.natives
        ],
        package=InstallPackage(id=id, folder=PACKAGE, after_enabled_packages=True) if in_package else None,
    )
    build = Build(
        id=id,
        match=Match(files=files),
        output=Output(mod=PACKAGE),
        steps=steps,
        install=install,
    )
    return OverhaulConfig(
        overhaul=1,
        id=id,
        label=label,
        short_label=short_label or label,
        game=game,
        recognise=Recognise(folder=id, manifest="overhaul.json", mod_ids=[id, *dlls], profile_marks=[id]),
        builds=[build],
        basic=basic,
    )


def level(config: OverhaulConfig, folder: Path) -> str:
    """ "basic" when the config's derived parts are still what make() gives for the mod's folder, else "advanced"."""
    if config.basic is None:
        return "advanced"
    try:
        derived = make(
            id=config.id,
            label=config.label,
            game=config.game,
            basic=config.basic,
            folder=folder,
            short_label=config.short_label,
        )
    except ValueError:
        return "advanced"
    return "basic" if derived.model_dump() == config.model_dump() else "advanced"
