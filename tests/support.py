"""Helpers for the tests: Elden Ring's locations on this PC (er()), and for the integration tests, which need a real
Seamless Co-op save, a copy of one.

The save comes from ROUNDTABLE_TEST_SAVE when set, otherwise from the first ER0000.co2 under %APPDATA%\\EldenRing.
Tests copy it into a temp folder and never write the original. Without a save the tests skip.
"""

import os
import shutil
from pathlib import Path

import pytest

from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.saves.analyze import GameItems


def er() -> Locations:
    """Elden Ring with nothing set under Settings > Locations: what code that is handed a game's locations gets."""
    return Locations(catalog.ELDEN_RING)


def er_items() -> GameItems:
    """What a save is checked against with er(): the installed game's items (none when it is not installed)."""
    return GameItems.for_locations(er())


def live_save() -> Path | None:
    override = os.environ.get("ROUNDTABLE_TEST_SAVE")
    if override:
        p = Path(override)
        return p if p.is_file() else None
    return next((p for p in er().save_files() if p.suffix.lower() == ".co2"), None)


def copy_live_save(tmp_path: Path) -> Path:
    src = live_save()
    if src is None:
        pytest.skip("no Seamless Co-op save on this PC (set ROUNDTABLE_TEST_SAVE to use one)")
    tmp_path.mkdir(parents=True, exist_ok=True)
    copy = tmp_path / "ER0000.co2"
    shutil.copy2(src, copy)
    return copy


class FakeActivityFacts:
    """views.activity.ActivityFacts over plain data: no jobs index, log files or trash."""

    def __init__(self, jobs=(), available=bool, logs=None, in_trash=lambda p: False, files=None):
        self._jobs, self._available, self._logs, self._in_trash, self._files = (
            list(jobs),
            available,
            logs or {},
            in_trash,
            files or {},
        )
        self.seen_at = 0.0

    def jobs(self):
        return list(self._jobs)

    def undo_available(self, undo):
        return self._available(undo)

    def in_trash(self, path):
        return self._in_trash(path)

    def read_log(self, name):
        return self._logs.get(name, {"entries": [], "cut": False, "missing": True})

    def read_attachment(self, name):
        return self._logs.get(name, {"text": "", "cut": False, "missing": True})

    def log_file(self, name):
        return self._files.get(name)

    def unseen(self):
        return sum(1 for r in self._jobs if r.get("outcome") in ("failed", "interrupted"))

    def mark_seen(self):
        self.seen_at += 1
        return self.seen_at


MODS_PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    '[[packages]]\nid = "cloud"\npath = \'mod/cloud\'\nload_after = [{ id = "flora", optional = false }]\n\n'
    "[[natives]]\npath = 'natives/a.dll'\n"
)


def mods_profile(root: Path, text: str = MODS_PROFILE) -> Path:
    """A small me3 profile on disk (two packages, one DLL) with its folders: what the Mods operations are run over."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "main.me3"
    path.write_bytes(text.encode("utf-8"))  # LF whatever the platform
    for d in ("mod/flora/parts", "mod/cloud/parts", "natives"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "natives" / "a.dll").write_bytes(b"d")
    return path


def tree_state(*roots: Path) -> dict:
    """(mtime, size) of every file and folder under the roots: a read must leave it as it was."""
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for r in roots for p in [r, *r.rglob("*")]}
