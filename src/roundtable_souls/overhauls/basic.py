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
    a text list the form names          strings of a JSON file set in a message binder of the game and merged on top
                                        of the packages before it (Basic.texts)
    anything else                       copied into its own folder at the same path (its DLLs, their data)
    installers, .me3, empty files       left out: nothing of the mod's runs, and a profile is the player's

A download whose game files sit in one top folder (payload/mod/..., whatever the folder is called) is read with that
folder as the package root: its paths are the game's own paths. Files listed in Basic.skip are left out.

The derived parts ([recognise] and the one [[builds]], whose id is the config's id) are written into the TOML with
[basic] when the form saves it, so everything else reads it like any config. A config whose derived parts no longer
equal what make() gives (its steps edited by hand) is at the advanced level.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Iterable
from pathlib import Path

from roundtable_souls.game import catalog as games
from roundtable_souls.game import config as game_config
from roundtable_souls.overhauls.config import (
    AddText,
    Basic,
    BasicNative,
    BasicText,
    Build,
    Copy,
    Each,
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
LAUNCHER_FOLDERS = {
    "packages",
    "natives",
    "builds",
    "mods",
    "mod",
    "profiles",
    "overhauls",
    "sources",
    "library",
    ".roundtable",
    ".previous",
}
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


def _tables(blob: bytes, oodle) -> dict[str, set[int]]:
    """Table file name -> its text ids, for a message binder (.msgbnd.dcx)."""
    from roundtable_souls import formats

    body, _ = formats.dcx.unpack(blob, oodle)
    out = {}
    for e in formats.bnd4.read_bnd4(body).entries:
        try:
            out[(e.name or "").replace("\\", "/").rsplit("/", 1)[-1]] = set(formats.fmg.read_fmg(e.data).entries)
        except formats.FormatError, struct.error, IndexError:
            continue  # not a text table
    return out


def _copies(files: list[str], folders: set[str], langs: set[str] | None = None) -> dict[str, dict[str, str]]:
    """The game's copies of message binders a download carries outside the game folders (<anything>/msg/<language>/
    X.msgbnd.dcx): binder name (lower case) -> language -> file. langs: only these languages."""
    out: dict[str, dict[str, str]] = {}
    for f in files:
        parts = f.split("/")
        low = [p.lower() for p in parts]
        if not low[-1].endswith(MERGED_ENDING) or len(parts) < 4 or low[0] in folders or low[-3] != "msg":
            continue
        if langs is None or low[-2] in langs:
            out.setdefault(low[-1], {})[low[-2]] = f
    return out


def text_tables(folder: Path, text: BasicText, folders: set[str], game_dir: Path | None = None) -> list[str]:
    """The tables of the download's copy of the binder a texts entry sets strings in, sorted; empty when the download
    has no copy or it can't be opened (the choice list of the form)."""
    from roundtable_souls.game.oodle import find_oodle

    langs = _copies(files_of(folder), folders).get(text.file.rsplit("/", 1)[-1].lower(), {})
    if not langs:
        return []
    lang = "engus" if "engus" in langs else sorted(langs)[0]
    try:
        return sorted(_tables((folder / langs[lang]).read_bytes(), find_oodle(game_dir)), key=str.lower)
    except Exception:  # noqa: BLE001  # shortcut: an unreadable copy means no choices, not an error
        return []


def propose_texts(folder: Path, files: list[str], folders: set[str], game_dir: Path | None = None) -> list[BasicText]:
    """[[basic.texts]] for a download that ships the game's copies of a message binder (<anything>/msg/<language>/
    X.msgbnd.dcx, outside the game folders) and <language>.json files of text ids to strings. The table is the one
    of the copy holding most of the ids (more than half, and no other table as many); when none is that clear (new
    ids, as a mod's own, are in none) it is left unset ("") for the player to choose. "*" is the engus.json (the
    default for a language with no file of its own). Nothing when a file does not read or the copy can't be opened
    (a compressed one needs the game's own Oodle library: game_dir)."""
    from roundtable_souls.game.oodle import find_oodle

    jsons = {Path(f).stem.lower(): f for f in files if f.lower().endswith(".json")}
    out = []
    for name, langs in sorted(_copies(files, folders, set(jsons)).items()):
        lang = "engus" if "engus" in langs else sorted(langs)[0]
        try:
            raw = json.loads((folder / jsons[lang]).read_text(encoding="utf-8-sig"))
            ids = {int(k) for k, v in raw.items() if isinstance(v, str)}
            if not ids or len(ids) != len(raw):
                continue
            held = {
                t: len(ids & have)
                for t, have in _tables((folder / langs[lang]).read_bytes(), find_oodle(game_dir)).items()
            }
        except Exception:  # noqa: BLE001  # shortcut: any unreadable copy or JSON means no proposal, not an error
            continue
        ranked = sorted(held.items(), key=lambda kv: -kv[1])
        clear = bool(ranked) and ranked[0][1] * 2 > len(ids) and (len(ranked) == 1 or ranked[1][1] < ranked[0][1])
        texts = {k: jsons[k] for k in sorted(langs) if k in jsons and k != "engus"}
        if "engus" in jsons:
            texts["*"] = jsons["engus"]
        out.append(BasicText(file=f"msg/{{each}}/{name}", table=ranked[0][0] if clear else "", texts=texts))
    return out


def propose(folder: Path, version: str | None = None, game: str = "eldenring", game_dir: Path | None = None) -> Basic:
    """The form's starting values for a mod folder: its top-level DLLs with no special options, loading after the
    other DLLs; the settings files beside them kept on updates; message texts (propose_texts); a binder meant for a game path placed there (and the
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
    texts = propose_texts(folder, files, folders, game_dir)
    return Basic(
        version=version,
        natives=[BasicNative(file=p.name) for p in dlls],
        keep=keep,
        place=place,
        skip=skip,
        texts=texts,
    )


def leaves(f: str, skip: list[str]) -> bool:
    return any(f.lower() == s.lower() or _under(f, s) for s in skip)


# What the setup does with one file (Basic.files; the Files table of the form): merge (parameters are combined),
# whole (copied as it is, not merged), keep (a settings file of the player's), copy, place:<game path>, leave.
KINDS = {  # kind of file -> the actions it can have, the automatic one first
    "regulation": ("merge", "whole", "leave"),
    "binder": ("merge", "whole", "leave"),  # a binder in a game folder
    "game": ("copy", "leave"),  # any other file in a game folder
    "settings": ("copy", "keep", "place", "leave"),  # outside the game folders
    "loose": ("copy", "place", "leave"),
}


def file_kind(f: str, folders: set[str], regulation: str, root: str) -> str:
    """What sort of file this is: regulation | binder | game | settings | loose."""
    g = f[len(root) + 1 :] if root and _under(f, root) else f
    glow = g.lower()
    if glow == regulation:
        return "regulation"
    if "/" in glow and glow.split("/")[0] in folders:
        return "binder" if glow.endswith(MERGED_ENDING) else "game"
    return "settings" if Path(f).suffix.lower() in SETTINGS_SUFFIXES else "loose"


def action_of(f: str, kind: str, basic: Basic) -> str:
    """What the setup does with the file: the Files table's choice, else what the older lists say, else automatic."""
    low = f.lower()
    own = {k.lower(): v for k, v in basic.files.items()}.get(low)
    if own is not None:
        return own
    placed = {k.lower(): v for k, v in basic.place.items()}.get(low)
    legacy = []  # what the older lists say, in order; one the file's kind can't have was ignored by older versions
    if leaves(f, basic.skip):
        legacy.append("leave")
    if placed is not None:
        legacy.append(f"place:{placed}")
    if low in {n.lower() for n in basic.not_merged}:
        legacy.append("whole" if kind in ("regulation", "binder") else "copy")
    if low in {k.lower() for k in basic.keep}:
        legacy.append("keep")
    for act in legacy:
        if ("place" if act.startswith("place:") else act) in KINDS[kind]:
            return act
    return KINDS[kind][0]


def encode_action(action: str, target: str = "") -> str:
    """A Files table choice as Basic.files stores it: the action, or place:<game path> for a placed file."""
    return f"place:{target}" if action == "place" else action


def decode_action(value: str) -> tuple[str, str]:
    """(action, game path) of a stored choice; the path is "" unless the file is placed."""
    return ("place", value[6:]) if value.startswith("place:") else (value, "")


def _step(f: str, kind: str, act: str, regulation: str, root: str) -> Step:
    """The step for one file of the download; f is its path there, the game's path is f without the package root."""
    g = f[len(root) + 1 :] if root and _under(f, root) else f
    if kind == "regulation" and act == "merge":
        return Params(do="params", file=g, patch=f)
    if kind == "binder" and act == "merge":
        return Merge(do="merge", file=g, patch=f)
    if kind in ("regulation", "binder", "game"):
        return Copy(do="copy", **{"from": f}, to=f"{PACKAGE}/{g}")
    if act == "keep":
        return KeepConfig(do="config", **{"from": f}, to=f)
    if g.lower().split("/")[0] == PACKAGE and "/" in g:
        raise ValueError(f"{f} is in a folder named {PACKAGE}, which is where the launcher puts the merged files.")
    return Copy(do="copy", **{"from": f}, to=f)


def _placed(f: str, to: str, whole: bool) -> Step:
    if to.lower().endswith(MERGED_ENDING) and not whole:
        return Merge(do="merge", file=to, patch=f)
    return Copy(do="copy", **{"from": f}, to=f"{PACKAGE}/{to}")


def _text(t: BasicText) -> Step:
    each = Each(game="languages") if "{each}" in t.file else None
    return AddText(do="text", file=t.file, table=t.table, texts=t.texts, each=each)


def make(
    *,
    id: str,
    label: str,
    game: str,
    basic: Basic,
    folder: Path,
    short_label: str | None = None,
    reserved: Iterable[str] = (),
    notes: list[str] | None = None,
    root: str | None = None,
    unset_tables: bool = False,
) -> OverhaulConfig:
    """The whole config for a mod folder at the basic level. Raises ValueError when there is nothing to set up or a
    file the form names is not in the folder. reserved: more folder names the launcher uses (the player's own names for
    the packages and natives folders, from the caller). Files and place entries naming a file a newer download dropped
    are left out of the result and said in notes (when given); DLLs and texts files that are gone raise. root: the
    package root to use instead of the one found (level() tries the one older versions found). A texts entry with no
    table chosen raises, unless unset_tables (the form that asks for it: it is left out of the steps)."""
    if id.lower() in LAUNCHER_FOLDERS | {r.lower() for r in reserved} or id.startswith("."):
        raise ValueError(f"{id} is a name the launcher uses for its own folders; choose another.")
    gc = game_config.load(game)
    regulation = games.BY_KEY[game].regulation.lower() if game in games.BY_KEY else games.REGULATION
    folders = set(gc.mod_folders)
    everything = files_of(folder)
    if root is None:
        root = package_root(everything, folders, regulation)
    have = {f.lower() for f in everything}
    for t in basic.texts:
        if not t.table and not unset_tables:
            raise ValueError(f"Choose the table of {t.file} that the texts are set in.")
    stale = [n for n in (*basic.place, *basic.files) if n.lower() not in have]
    if stale:
        for n in stale:
            if notes is not None:
                notes.append(f"{n} is not in the mod's folder any more; its setting was dropped.")
        basic = basic.model_copy(
            update={
                "place": {k: v for k, v in basic.place.items() if k not in stale},
                "files": {k: v for k, v in basic.files.items() if k not in stale},
            }
        )
    texts_from = {v.lower() for t in basic.texts for v in t.texts.values()}
    named = [*(n.file for n in basic.natives), *texts_from]
    for name in named:
        if name.lower() not in have:
            raise ValueError(f"{name} is not in the mod's folder.")
    acts: dict[str, tuple[str, str]] = {}  # file -> (kind, action) for the files that stay
    taken: dict[str, str] = {}
    for f in everything:
        kind = file_kind(f, folders, regulation, root)
        act = action_of(f, kind, basic)
        if act.startswith("place:"):
            to = act[6:]
            if kind not in ("settings", "loose"):
                raise ValueError(f"{f} is in a game folder already, so it can't be placed at another path.")
            if to.lower() != regulation and not ("/" in to and to.lower().split("/")[0] in folders):
                raise ValueError(f"{f} is placed at {to!r}, which is not in one of the game's folders.")
            if to.lower() in taken:
                raise ValueError(f"{f} and {taken[to.lower()]} are both placed at {to}.")
            taken[to.lower()] = f
        elif act not in KINDS[kind]:
            raise ValueError(f"{f} can't be set to {act!r}.")
        if act == "leave":
            if any(n.file.lower() == f.lower() for n in basic.natives):
                raise ValueError(f"{f} is one of the DLLs; take it out of the DLL list to leave it out.")
            continue
        acts[f] = (kind, act)
    steps = [
        _placed(f, act[6:], f.lower() in {n.lower() for n in basic.not_merged})
        if act.startswith("place:")
        else _step(f, kind, act, regulation, root)
        for f, (kind, act) in acts.items()
        if f.lower() not in texts_from
    ] + [_text(t) for t in basic.texts if t.table]
    files = [f for f in acts if f.lower() not in texts_from]
    if not steps:
        raise ValueError("The mod's folder has no files to set up.")
    in_package = any(
        s.do in ("params", "merge", "text") or (s.do == "copy" and s.to.startswith(f"{PACKAGE}/")) for s in steps
    )
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
    for root in (None, ""):  # "": a download with a payload folder, as older versions read it (no package root)
        try:
            derived = make(
                id=config.id,
                label=config.label,
                game=config.game,
                basic=config.basic,
                folder=folder,
                short_label=config.short_label,
                root=root,
                unset_tables=True,
            )
        except ValueError:
            continue
        # basic is left out: stale entries are pruned from the derived one, and the saved ones are not hand edits
        if derived.model_dump(exclude={"basic"}) == config.model_dump(exclude={"basic"}):
            return "basic"
    return "advanced"
