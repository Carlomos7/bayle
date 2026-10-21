"""The manifest an overhaul build keeps beside its package (overhaul.json), and who made it.

The launcher's own installs record INSTALLED_BY in it. A manifest without it was written by some other installer: the
launcher reads it (to detect and list the setup) and leaves it alone. installation.json is a legacy third-party
format: it is only ever read here (builds the launcher made before 4.1 kept their manifest under that name too); the
launcher writes it only when a config names it."""

from __future__ import annotations

from pathlib import Path

from roundtable_souls.mods.backends import local_path

MANIFEST = "overhaul.json"  # what a config without a manifest name gets
LEGACY_MANIFEST = "installation.json"  # read-only: another installer's manifest, or an older launcher build's
INSTALLED_BY = "installedBy"  # in the manifest: the launcher installed it (mods.overhaul_install)


def launcher_installed(data: dict) -> bool:
    """The manifest is of an install the launcher made: the launcher builds it from its copy of the download."""
    return bool(data.get(INSTALLED_BY))


def find_setup(profile: Path, data: dict) -> Path | None:
    """The launcher's copy of the download a launcher-made install was built from, or None."""
    written = data.get("maintenance")
    if written and launcher_installed(data):
        here = local_path(written, profile)
        if here.is_dir():
            return here
    return None
