"""The manifest an overhaul build keeps beside its package (installation.json), and who made it.

The launcher's own installs record INSTALLED_BY in it. A manifest without it was written by some other installer: the
launcher reads it (to detect and list the setup) and leaves it alone. installation.json is a legacy third-party
format that the launcher only reads; it never writes one for another installer."""

from __future__ import annotations

from pathlib import Path

from roundtable_souls.mods.backends import local_path

MANIFEST = "installation.json"
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
