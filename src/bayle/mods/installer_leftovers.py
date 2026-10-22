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

from bayle.formats import me3_profile
from bayle.mods import library
from bayle.mods.overhaul_manifest import launcher_installed
from bayle.resources import DATA_DIR

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
    return any(used_by(p, folder) for p in Path(base).glob("*.me3"))


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


def setup_folders(base: Path) -> list[Found]:
    """The installer's setup copies and backups in base, whether or not a setup is live."""
    base, r = Path(base), rules()
    mine: dict[str, Found] = {}
    for _folder, data in manifest_folders(base):
        setup = data.get(r.get("manifest_setup_key", ""))
        if isinstance(setup, str) and Path(setup).is_dir() and _norm(Path(setup).parent) == _norm(base):
            mine[_norm(setup)] = Found(Path(setup), False)
    for folder in _folders(base):
        if any(fnmatch.fnmatch(f.name, g) for f in folder.glob("*") if f.is_file() for g in r.get("setup_files", [])):
            mine[_norm(folder)] = Found(folder, False)
        elif any((sub / b).is_file() for sub in _folders(folder) for b in r.get("backup_files", [])):
            mine[_norm(folder)] = Found(folder, True)
    return list(mine.values())


def find(base: Path) -> list[Found]:
    """The installer folders in base no profile there uses, backups last: unused manifest folders (copies of a
    setup included) always; setup copies and backups only when no setup is live."""
    base = Path(base)
    mine = {_norm(f): Found(f, False) for f, _ in manifest_folders(base)}
    if not any(
        used(base, f) for f, _ in manifest_folders(base, named=False)
    ):  # a live setup keeps its copy and backups
        mine.update({_norm(f.path): f for f in setup_folders(base)})
    shown = [f for f in mine.values() if not used(base, f.path)]
    return sorted(shown, key=lambda f: (f.backups, f.path.name.lower()))


@dataclass(frozen=True)
class Setup:
    """An installer's setup a profile uses: its folder and manifest."""

    folder: Path
    manifest: dict
    manifest_name: str


def setup_of(profile: Path) -> Setup | None:
    """The setup a profile uses that some installer made (no overhaul config needed): a manifest folder, not the
    launcher's, that the profile's entries point into."""
    profile, r = Path(profile), rules()
    for folder, data in manifest_folders(profile.parent, named=False):
        if used_by(profile, folder):
            name = next(n for n in r.get("manifests", []) if (folder / n).is_file())
            return Setup(folder, data, name)
    return None


def used_by(profile: Path, folder: Path) -> bool:
    """This profile has an entry that points into folder."""
    try:
        entries = me3_profile.entries(me3_profile.read_text(profile))
    except OSError, ValueError:
        return False
    top = _norm(folder)
    return any(
        e.get("path") and _norm(me3_profile.resolve(profile, e["path"])).startswith(top + os.sep) for e in entries
    )


def other_users(profile: Path, folder: Path) -> list[Path]:
    """The other profiles beside this one that point into folder."""
    return [p for p in sorted(Path(profile).parent.glob("*.me3")) if _norm(p) != _norm(profile) and used_by(p, folder)]


def base_profile(setup: Setup, profile: Path) -> dict | None:
    """The profile as it was before the installer ran, when its manifest keeps it (a key from the data, in the
    manifest's row for this profile, else at the top)."""
    r = rules()
    rows = [
        row
        for row in setup.manifest.get(r.get("manifest_profiles_key", ""), []) or []
        if isinstance(row, dict) and isinstance(row.get("path"), str) and _norm(row["path"]) == _norm(profile)
    ]
    for holder in (*rows, setup.manifest):
        for key in r.get("base_profile_keys", []):
            if isinstance(holder.get(key), dict):
                return holder[key]
    return None
