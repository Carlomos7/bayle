"""A profile's own folder in me3's profiles folder, and the launcher's files in it. Each profile owns its mods:

    profiles/<name>/<name>.me3     the profile
    profiles/<name>/mod/           packages (game-file mods), one folder each
    profiles/<name>/natives/       DLL mods, one folder each
    profiles/<name>/builds/<what>/ what the launcher makes for this profile: an overhaul's id (its build, merged
                                   package, sources/ by role: merge/ text/ hooks/ base/, overhaul/) or
                                   combined-parameters; build.json, merge-report.txt, .previous/
    profiles/<name>/.roundtable/   the launcher's own (hidden): settings.json, backups/, previous/ (an updated mod's
                                   old copy), ops/ and ops.lock (journals)

A profile that sits loose in a folder with others (an existing setup) keeps its mod folders where they are
(mods.profile_edit.roots) and gets the same builds/ under .roundtable/profiles/<name>/ so two profiles never share
one. mods.migrate moves the shared rs-<game> library older versions made into this layout.
ProfileFolder answers where each of these is; mods.naming says what things are called. Nothing is created until
ensure() asks for it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.platform import files

PREFIX = "rs-"  # the launcher's folder for a game in me3's profiles folder: rs-<game key>
STATE = ".roundtable"  # the launcher's own folder beside the profile
SETTINGS = "settings.json"  # per-profile launcher choices (was roundtable.json beside the profile)
BACKUPS = "backups"  # each profile's .bak (was beside the .me3)
PREVIOUS_COPIES = "previous"  # an updated mod's old copy until it is kept or rolled back
OPS = "ops"  # operation journals (was .roundtable-ops beside the profile)
OPS_LOCK = OPS + ".lock"
PREVIOUS = ".previous"  # a build's previous copy, for Undo rebuild
HIDDEN = (STATE, PREVIOUS)  # given Windows' hidden attribute when ensure() makes them
RECORD = "roundtable.json"  # the launcher's file beside a mod's files
ROLES = ("merge", "text", "hooks", "base")  # an overhaul's sources, by what its builds do with them


@dataclass(frozen=True)
class SourceFolders:
    """builds/<overhaul id>/sources/: one folder per role and the record of where each file came from."""

    root: Path
    merge: Path
    text: Path
    hooks: Path
    base: Path
    record: Path

    def role(self, name: str) -> Path:
        if name not in ROLES:
            raise ValueError(f"not a source role: {name}")
        return self.root / name


@dataclass(frozen=True)
class BuildFolder:
    """builds/<what>/: what a build made, its inputs (build.json), its report, the previous
    build kept for Undo rebuild, and the install's side effects on the profile (roundtable.json)."""

    root: Path
    record: Path
    report: Path
    previous: Path
    side_effects: Path


@dataclass(frozen=True)
class StateFolders:
    """.roundtable/: the launcher's own files for a profile."""

    root: Path
    settings: Path
    backups: Path
    previous: Path
    ops: Path
    ops_lock: Path


def game_root(profiles_dir: Path, game: str) -> Path:
    """The launcher's own folder for one game: rs-<game> in me3's profiles folder."""
    return Path(profiles_dir) / f"{PREFIX}{game}"


def in_game_root(profile: Path, profiles_dir: Path, game: str) -> bool:
    """Whether the profile is somewhere below rs-<game> (case aside)."""
    root = os.path.normcase(os.path.abspath(game_root(profiles_dir, game)))
    return os.path.normcase(os.path.abspath(profile)).startswith(root + os.sep)


def is_user_profile(path: Path) -> bool:
    """A .me3 that is a profile, not an offline copy or one me3 generates."""
    name = Path(path).name.lower()
    return name.endswith(".me3") and not name.endswith((".offline.me3", "-default.me3"))


def own_folder(profile: Path) -> bool:
    """Whether the profile sits alone in a folder named after it (<name>/<name>.me3). A folder that holds other
    profiles too is nobody's own: its mod/ would be wrongly owned by one of them."""
    profile = Path(profile)
    if profile.parent.name.lower() != profile.stem.lower():
        return False
    try:
        return not any(
            p.name.lower() != profile.name.lower() and is_user_profile(p) for p in profile.parent.glob("*.me3")
        )
    except OSError:
        return False


@dataclass(frozen=True)
class ProfileFolder:
    """Where the launcher's files for ONE profile go (paths only; nothing is read or made here but by ensure and
    prune)."""

    root: Path

    @classmethod
    def of(cls, profile: Path) -> ProfileFolder:
        profile = Path(profile)
        return cls(profile.parent if own_folder(profile) else profile.parent / STATE / "profiles" / profile.stem)

    @property
    def packages(self) -> Path:
        return self.root / "mod"

    @property
    def natives(self) -> Path:
        return self.root / "natives"

    @property
    def builds(self) -> Path:
        return self.root / "builds"

    def package(self, mod_id: str) -> Path:
        return self.packages / mod_id

    def native(self, mod_id: str) -> Path:
        return self.natives / mod_id

    def overhaul(self, overhaul_id: str) -> Path:
        """The overhaul's settings files the launcher keeps for the player."""
        return self.builds / overhaul_id / "overhaul"

    def overhaul_record(self, overhaul_id: str) -> Path:
        return self.overhaul(overhaul_id) / RECORD

    def sources(self, overhaul_id: str) -> SourceFolders:
        root = self.builds / overhaul_id / "sources"
        return SourceFolders(root, root / "merge", root / "text", root / "hooks", root / "base", root / RECORD)

    def build(self, what: str) -> BuildFolder:
        """what: an overhaul's id, or combined-parameters."""
        root = self.builds / what
        return BuildFolder(root, root / "build.json", root / "merge-report.txt", root / PREVIOUS, root / RECORD)

    # ------------------------------------------------------------------ making folders
    def ensure(self, *folders: Path) -> list[Path]:
        """Make these folders (inside the profile's folder) and the ones above them, only these; .roundtable and
        .previous get Windows' hidden attribute when made. Returns the folders made."""
        made: list[Path] = []
        root = Path(os.path.abspath(self.root))
        for folder in folders:
            folder = Path(os.path.abspath(folder))
            if folder != root and root not in folder.parents:
                raise ValueError(f"{folder} is not inside {self.root}")
            chain = [folder, *(p for p in folder.parents if p == root or root in p.parents)]
            for p in reversed(chain):
                if p.is_dir():
                    continue
                p.mkdir(parents=p == root)
                made.append(p)
                if p.name in HIDDEN:
                    files.hide(p)
        return made

    def prune(self, folder: Path) -> list[Path]:
        """Remove folder and the folders above it while they are empty, up to the profile's folder (which stays); a
        folder already gone counts as empty. Nothing outside is touched. Returns the folders removed."""
        root = Path(os.path.abspath(self.root))
        folder = Path(os.path.abspath(folder))
        gone: list[Path] = []
        while root in folder.parents:
            try:
                if folder.exists():
                    if not folder.is_dir() or any(folder.iterdir()):
                        break
                    folder.rmdir()
                    gone.append(folder)
            except OSError:
                break
            folder = folder.parent
        return gone


def _state_folders(root: Path) -> StateFolders:
    return StateFolders(root, root / SETTINGS, root / BACKUPS, root / PREVIOUS_COPIES, root / OPS, root / OPS_LOCK)


def state_of(profile: Path) -> StateFolders:
    """The launcher's own folder for a profile: .roundtable beside it (in its own folder, or shared by the loose
    profiles of a folder)."""
    return _state_folders(Path(profile).parent / STATE)


def ensure_state(state: StateFolders, *folders: Path) -> None:
    """Make the state folder (hidden on Windows when made) and the given folders inside it."""
    if not state.root.is_dir():
        state.root.mkdir(parents=True, exist_ok=True)
        files.hide(state.root)
    for f in folders:
        f.mkdir(parents=True, exist_ok=True)


def profile_backup(profile: Path) -> Path:
    """Where the profile's .bak goes: <state>/backups/<name>.me3.bak (made when missing)."""
    state = state_of(profile)
    ensure_state(state, state.backups)
    return state.backups / (Path(profile).name + ".bak")
