"""Review fixes of the overhaul setup (overhauls.basic, mods.engine): paths stay inside their folders, old lists
survive, and so on. Temporary folders and synthetic files only."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from roundtable_souls.mods import engine
from roundtable_souls.overhauls.config import Basic


def make_folder(root: Path, names: list[str]) -> Path:
    for n in names:
        (root / n).parent.mkdir(parents=True, exist_ok=True)
        (root / n).write_bytes(b"x")
    return root


# ----------------------------------------------------------------------------- paths stay inside their folders
BAD = ["map/../../../x", "../x", "/abs/x", "C:/x", "C:x", r"map\..\x", "a//b", "./a", ""]


@pytest.mark.parametrize("bad", BAD)
def test_basic_paths_that_leave_their_folder_are_refused(bad):
    with pytest.raises(ValidationError):
        Basic(place={"a.bnd": bad})
    with pytest.raises(ValidationError):
        Basic(place={bad: "map/a"})
    with pytest.raises(ValidationError):
        Basic(files={bad: "copy"})
    with pytest.raises(ValidationError):
        Basic(files={"a.bnd": f"place:{bad}"})


def test_good_paths_pass():
    Basic(place={"x/a.bnd": "map/a.bnd"}, files={"x/b.ini": "keep", "c.bin": "place:map/c.bin"})


def test_the_engine_refuses_a_step_path_outside_its_folder(tmp_path):
    base = tmp_path / "setup"
    base.mkdir()
    assert engine._in(base, "a/b.txt") == base / "a/b.txt"
    with pytest.raises(engine.EngineError, match="outside"):
        engine._in(base, "../outside.txt")
    with pytest.raises(engine.EngineError, match="outside"):
        engine._in(base, "map/../../x")


# ----------------------------------------------------------------------------- saving with no Files table
def test_saving_without_the_mods_folder_keeps_the_old_lists_and_files():
    from roundtable_souls.overhauls.config import OverhaulConfig
    from roundtable_souls.services import mod_configs

    old = Basic(keep=["a.ini"], place={"x.bnd": "map/x.bnd"}, skip=["junk"], files={"b.ini": "keep"})
    config = OverhaulConfig.model_construct(basic=old)
    assert mod_configs.files_to_store([], {}) is None
    kept = mod_configs.with_basic(config, natives=[{"file": "M.dll"}], files=None).basic
    assert (kept.keep, kept.place, kept.skip, kept.files) == (old.keep, old.place, old.skip, old.files)
    assert [n.file for n in kept.natives] == ["M.dll"]


# ----------------------------------------------------------------------------- reserved folder names
def test_an_overhaul_cannot_take_the_name_of_the_players_own_packages_folder(tmp_path, monkeypatch):
    from roundtable_souls.config import layout
    from roundtable_souls.overhauls import basic

    folder = make_folder(tmp_path / "dl", ["M.dll"])
    kw = {"label": "M", "game": "eldenring", "basic": basic.propose(folder), "folder": folder}
    basic.make(id="MyPkgs", **kw)  # fine until the player names a folder so
    monkeypatch.setattr(layout, "layout", lambda: layout.Layout(packages="MyPkgs", natives="Dlls"))
    names = layout.reserved_names()
    for name in ("mypkgs", "Dlls", ".roundtable", ".previous"):
        with pytest.raises(ValueError, match="uses for its own folders"):
            basic.make(id=name, reserved=names, **kw)
