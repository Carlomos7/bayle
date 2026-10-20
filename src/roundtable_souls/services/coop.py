"""Seamless Co-op operations the window uses: finding a setup's ini, its password, scaling and every
setting, sharing them, and the words the settings form shows; and Seamless Co-op left in the game folder (its own
installer's place), which a me3 profile does not load: moved into the setup, or cleaned up."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls.coop.ini import (
    LINE_RE,
    PW_RE,
    SECTION_RE,
    _read,
    ersc_ini_for,
    read_settings_meta,
    write_keys,
    write_password,
)
from roundtable_souls.coop.scaling import (
    CUSTOM,
    NIGHTREIGN_SCALING,
    SCALING_KEYS,
    SCALING_LABELS,
    SCALING_PRESETS,
    ScalingSpec,
)
from roundtable_souls.coop.share import (
    COMMENT_PREFIX,
    JSON_FORMAT,
    export_settings,
    export_text,
    indent_lines,
    load_settings_json,
    parse_settings_json,
    plan_import,
    read_all_settings,
    strip_json_comments,
    toggle_comment,
)

__all__ = [
    "LINE_RE",
    "PW_RE",
    "SECTION_RE",
    "_read",
    "ersc_ini_for",
    "read_settings_meta",
    "write_keys",
    "write_password",
    "CUSTOM",
    "NIGHTREIGN_SCALING",
    "SCALING_KEYS",
    "SCALING_LABELS",
    "SCALING_PRESETS",
    "ScalingSpec",
    "COMMENT_PREFIX",
    "JSON_FORMAT",
    "export_settings",
    "export_text",
    "indent_lines",
    "load_settings_json",
    "parse_settings_json",
    "plan_import",
    "read_all_settings",
    "strip_json_comments",
    "toggle_comment",
    "GameFolderSeamless",
    "game_folder_seamless",
    "move_seamless_into_setup",
    "clean_up_game_folder_seamless",
    "relocate_dismissed",
    "dismiss_relocate",
]


# ----------------------------------------------------------------------------- Seamless Co-op in the game folder
CRASH_FOLDERS = {
    "crashdumps",
    "crashpad",
}  # Seamless Co-op writes these in the game folder whatever loads it: left alone


KEEP_IN_CLEANUP = {"locale"}  # beside the settings file, never removed by the clean-up


@dataclass
class GameFolderSeamless:
    """Seamless Co-op found in the game folder. kind: "move" (the profile does not load Seamless Co-op; its files
    here can be moved into the setup) or "cleanup" (the profile loads its own copy; these are leftovers)."""

    kind: str
    folder: Path  # <game>/SeamlessCoop
    files: list[Path] = field(default_factory=list)  # what would move or go: everything in folder but crash dumps
    launcher: Path | None = None  # Seamless Co-op's own launcher in the game folder, removed either way
    settings_differ: bool = False  # cleanup: the game folder's ini differs from the profile's (the profile's is kept)
    launcher_left: str = ""  # after an action: why the launcher could not be removed (it stays)

    def key(self, game: str, profile: str) -> str:
        return f"{game}|{Path(profile).name.lower()}|{self.kind}"


def game_folder_seamless(setup) -> GameFolderSeamless | None:
    """What of Seamless Co-op sits in the game folder of this setup's game, and what can be done with it. None when
    there is nothing (crash-dump folders alone don't count: Seamless Co-op recreates them) or no game folder."""
    from roundtable_souls.coop.ini import coop_ini_for

    game = setup.game
    if not game.coop_dll or setup.kind != "me3":
        return None
    gdir = setup.loc.game_dir()
    if not gdir:
        return None
    gdir = Path(gdir)
    folder = gdir / "SeamlessCoop"
    files = sorted(p for p in folder.iterdir() if p.name.lower() not in CRASH_FOLDERS) if folder.is_dir() else []
    has_dll = any(p.name.lower() == game.coop_dll.lower() and p.is_file() for p in files)
    launcher = gdir / game.coop_launcher if game.coop_launcher else None
    launcher = launcher if launcher is not None and launcher.is_file() else None
    loaded = coop_ini_for(setup.profile, game)  # the ini beside the DLL the profile loads, when it does
    if loaded is None:
        if not has_dll:
            return None
        return GameFolderSeamless("move", folder, files, launcher)
    # Cleaning up never removes the settings file or the locale folder (game model, 2026-10-20: Seamless Co-op reads
    # them from here whatever else is loaded), only what is left over beside them.
    files = [p for p in files if p.name.lower() not in KEEP_IN_CLEANUP | {(game.coop_ini or "").lower()}]
    if not files and launcher is None:
        return None
    mine = folder / game.coop_ini if game.coop_ini else None
    differ = bool(mine and mine.is_file() and mine.read_bytes() != Path(loaded).read_bytes())
    return GameFolderSeamless("cleanup", folder, files, launcher, differ)


def seamless_in_game_folder(loc) -> bool:
    """Whether Seamless Co-op's DLL is in loc's game folder (its own installer's place), with or without a profile."""
    game = loc.game
    gdir = loc.game_dir()
    return bool(game.coop_dll and gdir and (Path(gdir) / "SeamlessCoop" / game.coop_dll).is_file())


def move_seamless_into_setup(setup, found: GameFolderSeamless, log=lambda s: None) -> Path:
    """Move Seamless Co-op from the game folder into the setup's DLL folder (natives/SeamlessCoop, or -2…), add it to
    the profile as an early-loading DLL (a switched-off entry for it is replaced), and send its own launcher to the
    Recycle Bin. The settings file moves untouched (password included). Returns the new folder. If the profile
    can't be written, the files are moved back."""
    from roundtable_souls.mods import profile_edit
    from roundtable_souls.mods.profile_writer import ProfileWriter

    profile = Path(setup.profile)
    game = setup.game
    text = profile.read_bytes().decode("utf-8", errors="replace")
    _pk, natives = profile_edit.roots(profile, text)
    dest = natives / "SeamlessCoop"
    n = 2
    while dest.exists():
        dest = natives / f"SeamlessCoop-{n}"
        n += 1
    dest.mkdir(parents=True)
    moved: list[tuple[Path, Path]] = []
    try:
        for src in found.files:
            target = dest / src.name
            shutil.move(str(src), str(target))
            moved.append((src, target))
        w = ProfileWriter(profile, setup.loc)
        old = w.find("native", game.coop_dll)
        if old is not None:
            w.remove_entry(old)
        w.add_native(dest / game.coop_dll, load_early=True)
        w.write(f"before moving {game.coop_dll} from the game folder into this setup")
    except BaseException:
        for src, target in reversed(moved):
            try:
                shutil.move(str(target), str(src))
            except OSError:
                pass
        shutil.rmtree(dest, ignore_errors=True)
        raise
    log(f"Seamless Co-op moved from {found.folder} to {dest} and added to {profile.name}")
    _trash_launcher(found, log)
    return dest


def clean_up_game_folder_seamless(setup, found: GameFolderSeamless, log=lambda s: None) -> list[Path]:
    """Send the leftover Seamless Co-op files in the game folder (not the crash dumps) and its launcher to the Recycle
    Bin. The profile's own copy is untouched. Returns what was removed."""
    from roundtable_souls.platform import trash

    gone: list[Path] = []
    for p in found.files:
        trash.send(p)
        gone.append(p)
    gone += _trash_launcher(found, log)
    log(f"Seamless Co-op leftovers in the game folder sent to the Recycle Bin: {', '.join(p.name for p in gone)}")
    return gone


def _trash_launcher(found: GameFolderSeamless, log) -> list[Path]:
    """Send Seamless Co-op's own launcher to the Recycle Bin. A failure (the folder refuses deletes without admin
    rights) is logged and leaves the launcher where it is: the move or clean-up itself already happened."""
    from roundtable_souls.platform import trash

    if found.launcher is None or not found.launcher.is_file():
        return []
    try:
        trash.send(found.launcher)
    except OSError as e:
        found.launcher_left = f"{found.launcher.name} could not be removed ({e}); delete it by hand if you like"
        log(found.launcher_left)
        return []
    log(f"{found.launcher.name} sent to the Recycle Bin")
    return [found.launcher]


def relocate_dismissed(key: str) -> bool:
    from roundtable_souls.config.settings import load_settings

    return key in (load_settings().coop_relocate_dismissed or [])


def dismiss_relocate(key: str) -> None:
    from roundtable_souls.config.settings import change_settings

    def add(current):
        have = list(current.coop_relocate_dismissed or [])
        return {"coop_relocate_dismissed": [*have, key] if key not in have else have}

    change_settings(add)
