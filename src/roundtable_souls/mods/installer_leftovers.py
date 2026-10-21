"""What an overhaul's own installer left beside a me3 profile, recognised without any overhaul config: its manifest
(a known file name whose profile fields name a profile in the same folder), its setup copy (the folder the manifest
names, or one holding a known maintenance file) and its backups (folders of timestamped folders that each hold a
restore file). The file names are data (data/installer-leftovers.json); nothing here knows a particular installer.
A folder some profile beside it still points into is never listed. Read only."""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.formats import me3_profile
from roundtable_souls.mods import library
from roundtable_souls.mods.overhaul_manifest import launcher_installed
from roundtable_souls.resources import DATA_DIR

_SKIP = (library.STATE, library.LEGACY_STATE)  # the launcher's own hidden folders


@dataclass(frozen=True)
class Found:
    path: Path
    backups: bool  # the installer's backups of the profile: the only copy from before it


def rules() -> dict:
    try:
        data = json.loads((DATA_DIR / "installer-leftovers.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _norm(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _folders(base: Path) -> list[Path]:
    try:
        return sorted(p for p in Path(base).iterdir() if p.is_dir() and not p.name.startswith(_SKIP))
    except OSError:
        return []


def used(base: Path, folder: Path) -> bool:
    """Some profile in base has an entry that points into folder."""
    top = _norm(folder)
    for profile in Path(base).glob("*.me3"):
        try:
            entries = me3_profile.entries(me3_profile.read_text(profile))
        except OSError, ValueError:
            continue
        for e in entries:
            if e.get("path") and _norm(me3_profile.resolve(profile, e["path"])).startswith(top + os.sep):
                return True
    return False


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return data if isinstance(data, dict) else None


def _names_profile_in(data: dict, base: Path, r: dict) -> bool:
    paths = [data.get(k) for k in r.get("manifest_profile_keys", [])]
    paths += [
        row.get("path") for row in data.get(r.get("manifest_profiles_key", ""), []) or [] if isinstance(row, dict)
    ]
    return any(isinstance(p, str) and _norm(Path(p).parent) == _norm(base) for p in paths)


def manifest_folders(base: Path, *, named: bool = True) -> list[tuple[Path, dict]]:
    """Folders in base holding an installer's manifest (not the launcher's own); named: that names a profile in base."""
    r, out = rules(), []
    for folder in _folders(base):
        for name in r.get("manifests", []):
            data = _read(folder / name)
            if data is not None and not launcher_installed(data) and (not named or _names_profile_in(data, base, r)):
                out.append((folder, data))
                break
    return out


def find(base: Path) -> list[Found]:
    """The installer folders in base no profile there uses, backups last."""
    base, r = Path(base), rules()
    mine: dict[str, Found] = {}
    setups = manifest_folders(base)
    if any(used(base, folder) for folder, _ in manifest_folders(base, named=False)):
        return []  # a setup is still live: its copy and backups stay until it is removed
    for folder, data in setups:
        mine[_norm(folder)] = Found(folder, False)
        setup = data.get(r.get("manifest_setup_key", ""))
        if isinstance(setup, str) and Path(setup).is_dir() and _norm(Path(setup).parent) == _norm(base):
            mine[_norm(setup)] = Found(Path(setup), False)
    for folder in _folders(base):
        if any(fnmatch.fnmatch(f.name, g) for f in folder.glob("*") if f.is_file() for g in r.get("setup_files", [])):
            mine[_norm(folder)] = Found(folder, False)
        elif any((sub / b).is_file() for sub in _folders(folder) for b in r.get("backup_files", [])):
            mine[_norm(folder)] = Found(folder, True)
    shown = [f for f in mine.values() if not used(base, f.path)]
    return sorted(shown, key=lambda f: (f.backups, f.path.name.lower()))
