"""Review fixes of the overhaul setup (overhauls.basic, mods.engine): paths stay inside their folders, old lists
survive, and so on. Temporary folders and synthetic files only."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from bayle.mods import engine, overhaul_install
from bayle.mods import models as mod_models
from bayle.overhauls import basic
from bayle.overhauls.config import Basic


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
    with pytest.raises(mod_models.EngineError, match="outside"):
        engine._in(base, "../outside.txt")
    with pytest.raises(mod_models.EngineError, match="outside"):
        engine._in(base, "map/../../x")


# ----------------------------------------------------------------------------- saving with no Files table
def test_saving_without_the_mods_folder_keeps_the_old_lists_and_files():
    from bayle.overhauls.config import OverhaulConfig
    from bayle.services import mod_configs

    old = Basic(keep=["a.ini"], place={"x.bnd": "map/x.bnd"}, skip=["junk"], files={"b.ini": "keep"})
    config = OverhaulConfig.model_construct(basic=old)
    assert mod_configs.files_to_store([], {}) is None
    kept = mod_configs.with_basic(config, natives=[{"file": "M.dll"}], files=None).basic
    assert (kept.keep, kept.place, kept.skip, kept.files) == (old.keep, old.place, old.skip, old.files)
    assert [n.file for n in kept.natives] == ["M.dll"]


# ----------------------------------------------------------------------------- reserved folder names
def test_an_overhaul_cannot_take_the_name_of_the_players_own_packages_folder(tmp_path, monkeypatch):
    from bayle.config import layout
    from bayle.overhauls import basic

    folder = make_folder(tmp_path / "dl", ["M.dll"])
    kw = {"label": "M", "game": "eldenring", "basic": basic.propose(folder), "folder": folder}
    basic.make(id="MyPkgs", **kw)  # fine until the player names a folder so
    monkeypatch.setattr(layout, "layout", lambda: layout.Layout(packages="MyPkgs", natives="Dlls"))
    names = layout.reserved_names()
    for name in ("mypkgs", "Dlls", ".roundtable", ".previous"):
        with pytest.raises(ValueError, match="uses for its own folders"):
            basic.make(id=name, reserved=names, **kw)


# ----------------------------------------------------------------------------- old lists a file's kind can't have
def test_an_old_keep_for_a_file_in_a_game_folder_is_ignored_as_before():
    b = Basic(keep=["map/x.ini"], not_merged=["map/y.ini"])
    assert basic.action_of("map/x.ini", "game", b) == "copy"
    assert basic.action_of("map/y.ini", "game", b) == "copy"
    assert basic.action_of("x.ini", "settings", Basic(keep=["x.ini"])) == "keep"
    assert basic.action_of("x.bnd", "binder", Basic(place={"x.bnd": "map/x.bnd"})) == "merge"


# ----------------------------------------------------------------------------- stale entries, old package roots
def test_settings_for_a_file_a_new_download_dropped_are_pruned_and_said(tmp_path):
    folder = make_folder(tmp_path / "dl", ["M.dll", "M.ini"])
    b = Basic(natives=[{"file": "M.dll"}], files={"gone.ini": "keep"}, place={"gone.bnd": "map/gone.bnd"})
    notes: list[str] = []
    config = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder, notes=notes)
    assert config.basic.files == {} and config.basic.place == {} and len(notes) == 2
    assert basic.level(config.model_copy(update={"basic": b}), folder) == "basic"
    gone_dll = Basic(natives=[{"file": "N.dll"}])
    with pytest.raises(ValueError, match="N.dll is not in"):
        basic.make(id="m", label="M", game="eldenring", basic=gone_dll, folder=folder)


def test_a_config_saved_before_package_roots_stays_basic(tmp_path):
    folder = make_folder(tmp_path / "dl", ["payload/mod/chr/c0000.anibnd.dcx", "payload/M.dll"])
    b = Basic()
    old = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder, root="")
    new = basic.make(id="m", label="M", game="eldenring", basic=b, folder=folder)
    assert old.model_dump() != new.model_dump()
    assert basic.level(old, folder) == "basic" and basic.level(new, folder) == "basic"
    edited = old.model_copy(update={"recognise": old.recognise.model_copy(update={"mod_ids": ["other"]})})
    assert basic.level(edited, folder) == "advanced"


# ----------------------------------------------------------------------------- undo of the other profiles
def test_undo_restores_the_other_profiles_exact_bytes_first_even_when_the_main_take_back_fails(tmp_path, monkeypatch):
    import base64
    import hashlib

    from bayle.mods import operations

    raw = b"name = '\xe9\xff'\n"  # not UTF-8
    other = tmp_path / "other.me3"
    other.write_bytes(b"after")
    record = {
        "type": "overhaul-reapply",
        "operation": str(tmp_path / "op"),
        "others": [
            {
                "profile": str(other),
                "before_b64": base64.b64encode(raw).decode(),
                "after": hashlib.sha256(b"after").hexdigest(),
            }
        ],
    }

    def boom(*a, **k):
        raise operations.OperationError("gone")

    monkeypatch.setattr(operations, "take_back", boom)
    with pytest.raises(operations.OperationError):
        overhaul_install._undo_kind(record, lambda s: None, None)
    assert other.read_bytes() == raw


# ----------------------------------------------------------------------------- a DLL and a package with one name
def test_an_entry_is_found_by_kind_so_a_dll_and_a_package_named_alike_stay_apart():
    from bayle.mods import overhaul_install

    class W:
        def entries(self):
            return [
                {"kind": "native", "path": "natives/Same.dll", "row": {}},
                {"kind": "package", "id": "Same", "path": "packages/Same", "row": {}},
            ]

    w = W()
    assert overhaul_install._entry_named(w, "same", "package")["kind"] == "package"
    assert overhaul_install._entry_named(w, "Same.dll", "native")["kind"] == "native"
    assert overhaul_install._entry_named(w, "Same.dll", "package") is None
