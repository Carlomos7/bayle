"""The Saves operations through Session.run / snapshot / answer: no Qt, no window. Saves are invented files in the
test's own folders; the game is never running unless a test says so. The writes to live saves are in test_saves_writes.py."""

import pytest

from bayle.adapters.system.app_paths import data_dir
from bayle.api.routers import saves as saves_router
from bayle.errors import OperationError
from bayle.modules.games import catalog
from bayle.modules.games.locate import Locations, Overrides
from bayle.modules.saves import library as save_library
from bayle.modules.saves import regulation as save_regulation
from bayle.modules.saves import service as saves_service
from bayle.modules.saves.saves_page import SavesService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import Direct

OLD, NEW, OTHER = b"old save " * 40, b"new save " * 40, b"other save " * 40


def inline(run, name=None):
    run()


class World:
    """One account with one Standard save in a temporary saves folder."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.folder.mkdir(parents=True)
        self.save = self.folder / "ER0000.sl2"
        self.save.write_bytes(OLD)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(self.root)))

    def session(self, **jobs) -> Direct:
        jobs_ = JobManager(EventBus(), spawn=inline, **jobs)
        return Direct(saves_router, "saves", SavesService(jobs_, lambda: self.loc), jobs_)

    def backups(self):
        return saves_service.list_backups(loc=self.loc)


@pytest.fixture
def world(tmp_path, monkeypatch):
    # an invented file is not a whole save: the checks that read a save's layout accept it, and its signing is left alone
    monkeypatch.setattr(save_regulation, "is_pc_save", lambda data: True)
    monkeypatch.setattr(save_library, "check_whole", lambda data, game: None)
    monkeypatch.setattr(save_library, "signed_for_account", lambda data, target, game: (data, False))
    monkeypatch.setattr(save_library, "characters", lambda path, game=None: [])
    return World(tmp_path)


def finished(session: Direct, job_id: str):
    snap = session.jobs.get(job_id)
    assert snap is not None and snap.state == "done", snap
    return snap


# ---------------------------------------------------------------------------------------------------- reads
def _tree(*roots):
    return {
        str(p): (p.stat().st_mtime_ns, p.stat().st_size)
        for r in roots
        for p in [r, *r.rglob("*")]
        if "node_modules" not in p.parts
    }


def test_reading_the_page_writes_nothing(world, monkeypatch):
    world.session().run("saves.back_up", {"paths": [str(world.save)]})  # a backup to list
    info = {"path": world.save, "name": world.save.name, "kind": "Standard", "characters": [], "findings": []}
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: dict(info))
    s = world.session()
    before = _tree(world.root, data_dir())
    state = s.snapshot("saves")
    s.run("saves.default_name", {"path": str(world.save)})
    assert [i["name"] for i in state.infos] == ["ER0000.sl2"] and len(state.backups) == 1
    assert _tree(world.root, data_dir()) == before


def test_health_report_and_sheet_read_the_save(world, monkeypatch):
    info = {
        "path": world.save,
        "name": world.save.name,
        "characters": [
            {"slot": 1, "name": "Ann", "level": 10, "runes": 5, "hp": 300, "stats": {}, "ok": True},
        ],
        "findings": [],
        "vanilla_plan": [],
        "loading_plan": [],
        "checksum_fixes": {"slots": [], "ud10": False},
    }
    monkeypatch.setattr(saves_service, "save_info", lambda path, game=None, kind=None, *, loc: info)
    monkeypatch.setattr(saves_service.save_analyze, "format_health_report", lambda i: f"report of {i['name']}")
    s = world.session()
    assert s.run("saves.health_report", {"path": str(world.save)}).text == "report of ER0000.sl2"
    assert s.run("saves.sheet", {"path": str(world.save), "slot": 1}).data["characters"][0]["name"] == "Ann"


def test_adopt_legacy_is_a_command_and_the_folders_command_makes_them(world):
    s = world.session()
    assert s.run("saves.adopt_legacy").folders == [str(world.folder)]
    assert s.run("saves.folder", {"which": "saves"}).path == str(world.folder)
    backups = s.run("saves.folder", {"which": "backups"}).path
    assert backups and "backups" in backups.lower()
    assert s.run("saves.folder", {"which": "library"}).path


# ---------------------------------------------------------------------------------------------------- writes
def test_back_up_one_and_all_take_a_backup_and_say_so(world):
    s = world.session()
    one = finished(s, s.run("saves.back_up", {"paths": [str(world.save)]}).job_id)
    assert one.result["saves"] == [str(world.save)] and len(one.result["backups"]) == 1 and one.undo is None
    both = finished(s, s.run("saves.back_up", {"everything": True}).job_id)
    assert both.result["saves"] == [str(world.save)] and len(both.result["backups"]) == 1
    backups = world.backups()
    assert [b["action"] for b in backups] == ["Manual backup"] * 2
    assert all(b["path"].read_bytes() == OLD for b in backups)
    with pytest.raises(OperationError) as e:
        s.run("saves.back_up", {})
    assert e.value.code == "invalid_params"


# ---------------------------------------------------------------------------------------------------- the gate
def test_writing_jobs_are_refused_while_the_game_runs(world):
    from bayle.errors import Busy

    for name, params in (("saves.back_up", {"everything": True}), ("saves.post_session_repair", {})):
        with pytest.raises(Busy):
            world.session(game_running=lambda: True).run(name, params)
    assert world.backups() == [] and world.save.read_bytes() == OLD


# ---------------------------------------------------------------------------------------------------- the Library
def test_save_a_copy_and_import_add_to_the_library_even_while_the_game_runs(world):
    # the detail (results, failures, gates) is in test_saves_copy_in.py; this keeps the old page-level intent
    s = world.session(game_running=lambda: True)
    got = finished(s, s.run("saves.save_copy", {"path": str(world.save), "name": "Mine"}).job_id)
    assert got.result["name"] == "Mine" and got.result["source"] == str(world.save) and got.undo is None
    extra = world.folder / "x.sl2"
    extra.write_bytes(OTHER)
    one = finished(s, s.run("saves.import_files", {"files": [str(extra)], "name": "Imported"}).job_id)
    assert [i["name"] for i in one.result["imported"]] == ["Imported"] and one.result["failed"] == []
    many = finished(s, s.run("saves.import_files", {"files": [str(extra), str(world.save)]}).job_id)
    assert len(many.result["imported"]) == 2
    assert len(save_library.load(world.folder)["entries"]) == 4
    assert world.save.read_bytes() == OLD and world.backups() == []


def test_save_a_copy_is_refused_beside_a_running_write(world):
    from bayle.errors import Busy

    s = world.session(external_busy=lambda: True)
    with pytest.raises(Busy):
        s.run("saves.save_copy", {"path": str(world.save), "name": "Mine"})
    assert save_library.load(world.folder)["entries"] == []


def test_import_without_a_save_folder_is_refused_with_a_code(world, tmp_path):
    world.save.unlink()
    picked = tmp_path / "x.sl2"
    picked.write_bytes(OTHER)
    with pytest.raises(OperationError) as e:
        world.session().run("saves.import_files", {"files": [str(picked)]})
    assert e.value.code == "no_saves"
