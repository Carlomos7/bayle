"""A setup that another installer made is detected and left alone: nothing from its download runs, and nothing in it
changes, whatever the launcher is asked to do with the profile."""

import json
import subprocess
from pathlib import Path

from test_engine import PROFILE, Example

from bayle.modules.games import catalog as games
from bayle.modules.games.locate import Locations, Overrides
from bayle.modules.launch import play
from bayle.modules.mods import rebuild as merge
from support import er


def snapshot(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def installer_made(world):
    """The world's manifest as an installer other than the launcher leaves it (no installedBy)."""
    manifest = world.own / "installation.json"
    data = json.loads(manifest.read_text())
    data.pop("installedBy")
    data["profile"] = str(world.profile)
    manifest.write_text(json.dumps(data))
    return manifest


def test_an_installer_made_setup_is_listed_and_a_changed_profile_leaves_it_byte_identical(tmp_path, monkeypatch):
    world = Example(tmp_path, monkeypatch)
    manifest = installer_made(world)
    started = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: started.append(a))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    (world.base / "mod" / "newer").mkdir()
    (world.base / "mod" / "newer" / "regulation.bin").write_bytes(b"a mod added below the overhaul")
    world.profile.write_text(
        PROFILE.replace(
            '[[packages]]\nid = "example-overhaul"',
            '[[packages]]\nid = "newer"\npath = \'mod/newer\'\n\n[[packages]]\nid = "example-overhaul"',
        ),
        encoding="utf-8",
    )
    before = snapshot(world.base)

    loc = Locations(
        games.ELDEN_RING, Overrides(profiles_dir=str(world.base), game_exe=str(world.game / "eldenring.exe"))
    )
    assert ("manifest", manifest) in [(s.kind, Path(s.source)) for s in play.discover(None, loc)]
    health = merge.health(world.profile, loc=er())
    assert health["backend"] is None  # no tool is found for it, so none can run
    assert merge.play_check(world.profile, loc=er()) is None  # Play does not rebuild it
    assert merge.update_before_play(world.profile, lambda s: None, loc=er()) is None
    assert merge.find_backend(world.profile, loc=er()) is None
    assert "another installer" in (merge.setup_problem(world.profile, loc=er()) or "")

    assert snapshot(world.base) == before
    assert started == []  # nothing of the download (its installer, its bundled Python) was started
