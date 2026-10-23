"""SavesService (the group A reads) without a session or a window: invented saves in tmp folders only."""

import pytest

from bayle.errors import OperationError
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.saves import library as save_library
from bayle.services import saves as saves_service
from bayle.services.saves_page import SavesService


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "saves"
    folder = root / "76561198000000001"
    folder.mkdir(parents=True)
    save = folder / "ER0000.sl2"
    save.write_bytes(b"save " * 40)
    loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(root)))
    info = {"path": save, "name": save.name, "characters": [], "findings": []}
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: dict(info))
    monkeypatch.setattr(saves_service.save_analyze, "format_health_report", lambda i: f"report of {i['name']}")
    monkeypatch.setattr(save_library, "characters", lambda path, game=None: [])
    return SavesService(None, lambda: loc), folder, save  # type: ignore[arg-type]


def test_page_lists_the_live_saves(world):
    svc, _folder, save = world
    assert [i["name"] for i in svc.page().infos] == [save.name]


def test_save_info_and_report_read_the_save(world):
    svc, _folder, save = world
    assert svc.save_info(save)["path"] == str(save)
    assert svc.health_report(save) == "report of ER0000.sl2"


def test_default_name(world):
    svc, _folder, save = world
    assert svc.default_name(save)


def test_copy_entry_unknown_is_copy_unusable(world):
    svc, folder, _save = world
    with pytest.raises(OperationError) as e:
        svc.copy_entry(folder, "nope")
    assert e.value.code == "copy_unusable"


def test_no_game_is_a_code(tmp_path):
    with pytest.raises(OperationError) as e:
        SavesService(None, lambda: None).page()  # type: ignore[arg-type]
    assert e.value.code == "no_game"


def test_missing_save_path_gives_an_info_not_a_crash(tmp_path):
    loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(tmp_path)))
    info = SavesService(None, lambda: loc).save_info(tmp_path / "gone.sl2")  # type: ignore[arg-type]
    assert info["path"].endswith("gone.sl2")


def test_folder_makes_only_an_empty_backups_or_library_folder(world):
    svc, folder, _save = world
    before = {p for p in folder.parent.rglob("*")}
    assert svc.folder("saves") == folder
    for which in ("backups", "library"):
        got = svc.folder(which)
        assert got is not None and got.is_dir() and not any(got.iterdir())
    new = {p for p in folder.parent.rglob("*")} - before
    assert all(p.is_dir() for p in new)
    assert folder.joinpath("ER0000.sl2").read_bytes() == b"save " * 40
