"""After the app was renamed (Roundtable Souls -> Bayle), on the first start of an installed copy.

Velopack itself renames the shortcuts it made (shortcuts.rs, create_or_update_manifest_lnks) and rewrites the
uninstall entry's DisplayName (registry.rs, update_uninstall_entry) when it applies an update, and only adds the new
stub "<title>.exe" beside the old one. Two things are left to us:
  - shortcuts the launcher made itself (the Inno migration: they point at the stub, so Velopack skips them): rename
    "<previous>.lnk" to "<title>.lnk" in the Desktop and Start menu folders, only when they start this install;
  - the old stub "<previous>.exe": Steam shortcuts point at it and cannot be rewritten while Steam runs (and Steam
    is how the launcher is often started), so it stays, and is copied again from the new stub if it went missing.
Both steps look at the files each time, so they are idempotent and safe to retry.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from roundtable_souls.config import identity
from roundtable_souls.config.settings import identity_matches, is_installed, velopack_root


def _inside(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError, OSError:
        return False


def rename_links(
    folders: list[Path], root: Path, old: str, new: str,
    read_target: Callable[[Path], Path | None], rename: Callable[[Path, Path], None] = Path.rename,
) -> list[Path]:  # fmt: skip
    """Rename "<old>.lnk" to "<new>.lnk" in each folder when it starts a program inside root. Returns the new paths."""
    done = []
    for folder in folders:
        src, dst = folder / f"{old}.lnk", folder / f"{new}.lnk"
        if old == new or not src.is_file() or dst.exists():
            continue
        target = read_target(src)
        if target is None or not _inside(target, root):
            continue  # somebody else's shortcut with the same name
        try:
            rename(src, dst)
            done.append(dst)
        except OSError:
            continue
    return done


def keep_previous_stub(root: Path, old_stub: str, new_stub: str, copy=shutil.copy2) -> bool:
    """Make sure root/<old_stub> exists next to root/<new_stub>. Returns whether it was (re)created."""
    old, new = root / old_stub, root / new_stub
    if old_stub == new_stub or old.exists() or not new.is_file():
        return False
    try:
        copy(new, old)
    except OSError:
        return False
    return True


def _known_folder(name: str) -> Path:
    from roundtable_souls.updates.inno import _known_folder as known

    return known(name)


def _link_target(lnk: Path) -> Path | None:
    q = str(lnk).replace("'", "''")
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"(New-Object -ComObject WScript.Shell).CreateShortcut('{q}').TargetPath"],
        capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )  # fmt: skip
    text = out.stdout.strip()
    return Path(text) if text else None


def run() -> dict:
    """The real thing, for an installed Windows copy; {} when there is nothing to do."""
    ident = identity.get()
    root = velopack_root()
    if sys.platform != "win32" or root is None or not is_installed() or not identity_matches():
        return {}
    if ident.previous_title == ident.title:
        return {}
    restored = keep_previous_stub(root, ident.previous_stub_name, ident.stub_name)
    folders = [_known_folder("Programs"), _known_folder("Desktop")]
    renamed = rename_links(folders, root, ident.previous_title, ident.title, _link_target)
    return {"stub_restored": restored, "renamed": [str(p) for p in renamed]}
