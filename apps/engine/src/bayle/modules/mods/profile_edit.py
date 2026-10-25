"""Install, remove and configure mods in a me3 profile, and create or delete profiles.

A folder is a *package* when it holds game asset folders (parts, chr,
msg, ...) or regulation.bin, a *native* when it holds DLLs and no assets, a whole *me3 profile* when it
contains a .me3 file. Single-folder wrappers (the usual zip layout) are unwrapped first.

Profile edits are text-level so comments and order survive: new [[packages]] / [[natives]] blocks go
at the end (later loads later, so a new mod overrides what is above it), and per-mod options rewrite
only the keys inside one block. Profiles in the inline-array form some installers write are
converted to blocks first (that form has no comments to lose). The functions here change text; every
write of a profile goes through mods.profile_writer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

import re
import shutil
import time
from pathlib import Path

from bayle.adapters.formats import me3_profile
from bayle.adapters.formats.me3_profile import (  # the one profile reader; re-exported for the mods layer
    block_options,
    blocks,
    entry_ref,  # noqa: F401
    is_array_form,
    quote,
    read_text,
    resolve,
    to_blocks,
)
from bayle.modules.mods import library, naming
from bayle.modules.mods.models import ModError

# ----------------------------------------------------------------------------- detection


# ----------------------------------------------------------------------------- archives


# ----------------------------------------------------------------------------- where things live
def roots(profile: Path, text: str) -> tuple[Path, Path]:
    """(packages root, natives root). New packages go into the mods container existing packages share (a folder
    named mod / mods / packages beside the profile), else mod/; natives likewise into natives/. A package that lives
    inside another mod's own folder (an overhaul's Folder/mod) is never used as the container."""
    profile = Path(profile)
    if is_array_form(text):
        text = to_blocks(text)
    counts: dict[tuple[str, Path], int] = {}
    for b in blocks(text):
        o = block_options(text, b["index"])
        if not o["path"]:
            continue
        parent = resolve(profile, o["path"]).parent
        counts[(b["kind"], parent)] = counts.get((b["kind"], parent), 0) + 1

    def pick(kind, names, default):
        best = None
        for (k, parent), _n in sorted(counts.items(), key=lambda kv: -kv[1]):
            if k == kind and parent.name.lower() in names and parent.parent == profile.parent:
                best = parent
                break
        return best or profile.parent / default

    lay = library.layout()  # the launcher's own folders, as Settings names them
    packages = lay.packages if library.own_folder(profile) else "mod"
    return (
        pick("package", ("mod", "mods", "packages", lay.packages.lower()), packages),
        pick("native", ("natives", "dll", "dlls", lay.natives.lower()), lay.natives),
    )


def slug(name: str) -> str:
    """A folder / id friendly name: Nexus's numeric suffix dropped, odd characters collapsed to one dash. The case is
    kept (today's installs); the launcher's own layout names folders with mods.naming.mod_id."""
    base = naming.NEXUS_SUFFIX.sub("", name.strip())
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", base)
    s = re.sub(r"-{2,}", "-", s).strip("-.")
    return s[:60] or "mod"


def rel(profile: Path, target: Path) -> str:
    """target as a path from the profile's folder when inside it, else as given."""
    try:
        return str(Path(target).relative_to(Path(profile).parent)).replace("\\", "/")
    except ValueError:
        return str(target).replace("\\", "/")


# ----------------------------------------------------------------------------- operations
def set_options(profile: Path, index: int, opts: dict, *, loc: Locations) -> Path | None:
    """Rewrite one entry's options (set_block_options) through the writer: the mod that must stay last follows an id
    renamed here. Returns the .bak. A loop the change would make among the other entries shows on the Load order
    card; one it would make itself is refused (mods.profile_writer)."""
    from bayle.modules.mods import profile_writer

    w = profile_writer.ProfileWriter(Path(profile), loc)
    o = w.options(index)
    name = o["id"] or Path(o["path"]).name
    if set(opts) == {"enabled"}:
        what = f"before turning {name} {'on' if opts['enabled'] else 'off'}"
    else:
        what = f"before changing {name}'s options"
    w.set_options(index, opts)
    return w.write(what).backup


def entries(profile: Path) -> list[dict]:
    """Every block, enabled or not, with its options; 'index' addresses it for the other operations."""
    return me3_profile.entries(read_text(Path(profile)))


# ----------------------------------------------------------------------------- package folders in a profile


# ----------------------------------------------------------------------------- profiles
def create_profile(folder: Path, name: str, game: str = "eldenring", copy_from: Path | None = None) -> Path:
    """A new profile in me3's profiles folder `folder`, in a folder of its own: <name>/<name>.me3 with mod/ and
    natives/ beside it. A copy of another profile takes its text; when that one has a folder of its own its mod and
    natives folders are copied too, so the relative entry paths keep working."""
    stem = slug(name)
    if stem.lower().endswith(".me3"):
        stem = stem[:-4]
    home = library.profiles_root(Path(folder), game) / stem
    path = home / f"{stem}.me3"
    if path.exists():
        raise ModError(f"{path.name} already exists")
    src = Path(copy_from) if copy_from and Path(copy_from).is_file() else None
    if src is not None:
        text = read_text(src)
    else:
        text = f'profileVersion = "v1"\n\n[[supports]]\ngame = {quote(game)}\n'
    home.mkdir(parents=True, exist_ok=True)
    from bayle.modules.mods import profile_writer

    profile_writer.ProfileWriter.create(path, text).write("new profile")
    for sub_name in library.copied_folders(src) if src is not None else ():  # a copy keeps the names its entries use
        if (src.parent / sub_name).is_dir():
            shutil.copytree(src.parent / sub_name, home / sub_name, dirs_exist_ok=True)
    for sub_name in ("packages", "natives"):
        (home / sub_name).mkdir(exist_ok=True)
    return path


def delete_profile(path: Path) -> Path:
    """Move the .me3 into the launcher's deleted profiles (data_folder.deleted_profiles), with a note of where it
    lived. Mod folders are never touched; its .bak (in .roundtable/backups, or beside it from launchers before 3.23) and
    its offline copy are removed; the offline copy is regenerated when needed."""
    import json

    from bayle.adapters.system import data_folder

    path = Path(path)
    if not path.is_file():
        raise ModError(f"{path} is not a file")
    trash = data_folder.deleted_profiles(path.parent)
    trash.mkdir(parents=True, exist_ok=True)
    dest = trash / f"{path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.me3"
    shutil.move(str(path), str(dest))
    Path(str(dest) + ".json").write_text(
        json.dumps({"from": str(path), "when": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=1), encoding="utf-8"
    )
    baks = (library.state_of(path).backups / (path.name + ".bak"), path.with_name(path.name + ".bak"))
    for extra in (*baks, path.with_name(path.stem + ".offline.me3")):
        if extra.exists():
            try:
                extra.unlink()
            except OSError:
                pass
    return dest
