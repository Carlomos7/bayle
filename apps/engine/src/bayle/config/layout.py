"""Where the launcher's game folder is: <Profiles folder>/<game_folder_pattern> (config.settings). The rest of the
layout (profiles, packages, natives, builds, Shared mods) is mods.library's."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Layout:
    """The folder names Settings lets the player choose (config.settings: profiles_root, game_folder_pattern,
    packages_folder, natives_folder, shared_folder)."""

    root: str | None = None
    pattern: str = "b-{game}"
    packages: str = "packages"
    natives: str = "natives"
    shared: str = ".shared"


def layout() -> Layout:
    """The layout settings as they are now."""
    from bayle.config.settings import load_settings

    s = load_settings()
    return Layout(s.profiles_root, s.game_folder_pattern, s.packages_folder, s.natives_folder, s.shared_folder)


def reserved_names() -> list[str]:
    """The folder names the player's layout gives the launcher's own folders (an overhaul can't be named like one)."""
    lay = layout()
    return [lay.packages, lay.natives, lay.shared]


def game_root(profiles_dir: Path, game: str) -> Path:
    """The launcher's own folder for one game: b-<game> in the Profiles folder (me3's profiles folder unless Settings
    names another)."""
    lay = layout()
    return Path(lay.root or profiles_dir) / lay.pattern.format(game=game)
