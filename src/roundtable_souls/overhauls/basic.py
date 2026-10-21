"""The basic level of an overhaul config: what the Overhaul setup form sets ([basic] in the TOML), and the whole
config derived from it and the mod's own files, so a mod no shipped config describes can be set up as an overhaul
without anyone writing build steps (docs/Overhaul configs.md, "Basic").

What each of the mod's files becomes (make):

    regulation.bin                      params: combined on top of the packages before it
    a binder in a game folder (*bnd.dcx) merge: merged on top of the last package before it that ships it, or used
                                        whole when none does (the form can untick one: then copied whole)
    any other file in a game folder     copied into its package (mod/<path>)
    a settings file the form keeps      config: the player's copy kept on updates, new keys added
    anything else                       copied into its own folder at the same path (its DLLs, their data)
    installers, .me3, empty files       left out: nothing of the mod's runs, and a profile is the player's

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


def propose(folder: Path, version: str | None = None, game: str = "eldenring") -> Basic:
    """The form's starting values for a mod folder: its top-level DLLs with no special options, loading after the
    other DLLs; the settings files beside them kept on updates."""
    folder = Path(folder)
    ignored = set(game_config.load(game).ignored_dlls)
    dlls = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".dll" and p.name.lower() not in ignored),
        key=lambda p: p.name.lower(),
    )
    keep = (
        []
        if not dlls
        else [f for f in files_of(folder) if "/" not in f and Path(f).suffix.lower() in SETTINGS_SUFFIXES]
    )
    return Basic(version=version, natives=[BasicNative(file=p.name) for p in dlls], keep=keep)


def _step(f: str, basic: Basic, folders: set[str], regulation: str) -> Step:
    low = f.lower()
    top = low.split("/")[0]
    if low == regulation:
        return Params(do="params", file=f, patch=f)
    if "/" in low and top in folders:
        if low.endswith(MERGED_ENDING) and low not in {n.lower() for n in basic.not_merged}:
            return Merge(do="merge", file=f, patch=f)
        return Copy(do="copy", **{"from": f}, to=f"{PACKAGE}/{f}")
    if low in {k.lower() for k in basic.keep}:
        return KeepConfig(do="config", **{"from": f}, to=f)
    if top == PACKAGE and "/" in low:
        raise ValueError(f"{f} is in a folder named {PACKAGE}, which is where the launcher puts the merged files.")
    return Copy(do="copy", **{"from": f}, to=f)


def make(
    *, id: str, label: str, game: str, basic: Basic, folder: Path, short_label: str | None = None
) -> OverhaulConfig:
    """The whole config for a mod folder at the basic level. Raises ValueError when there is nothing to set up or a
    DLL the form names is not in the folder."""
    gc = game_config.load(game)
    regulation = games.BY_KEY[game].regulation.lower() if game in games.BY_KEY else "regulation.bin"
    files = files_of(folder)
    have = {f.lower() for f in files}
    for n in basic.natives:
        if n.file.lower() not in have:
            raise ValueError(f"{n.file} is not in the mod's folder.")
    steps = [_step(f, basic, set(gc.mod_folders), regulation) for f in files]
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
