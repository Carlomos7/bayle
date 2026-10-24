"""Back up, Save a copy and Import (group C and D) through Session.run and the job they start. Every file is invented
bytes in the test's own folders; the game never runs unless a test says so. The source of each is only ever read:
every test that can, proves its sha256 and mtime_ns did not move. A source another program is writing or holding is
simulated from inside a patched open() so nothing depends on timing."""

import builtins
import hashlib
import os
from types import SimpleNamespace

import pytest

from bayle.api.routers import saves as saves_router
from bayle.errors import Busy, OperationError
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.platform import files
from bayle.saves import backups as save_backups
from bayle.saves import fix as save_fix
from bayle.saves import library as save_library
from bayle.saves import regulation as save_regulation
from bayle.services import saves as saves_service
from bayle.services.saves_page import SavesService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import Direct

SAVE = b"SAVE first save " * 40
SAVE2 = b"SAVE second save " * 40
NOT_A_SAVE = b"just some text"


class World:
    """One account with two live saves. queue=None: jobs run at once; a list: they wait in it to be run by hand."""

    def __init__(self, tmp_path, queue=None):
        self.tmp = tmp_path
        self.root = tmp_path / "saves"
        self.folder = self.root / "76561198000000001"
        self.folder.mkdir(parents=True)
        self.save = self.folder / "ER0000.sl2"
        self.save.write_bytes(SAVE)
        self.save2 = self.folder / "ER0000.co2"
        self.save2.write_bytes(SAVE2)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(self.root)))
        self.queue = queue

    def session(self, **jobs) -> Direct:
        if self.queue is None:

            def spawn(run, name=None):
                run()
        else:

            def spawn(run, name=None):
                self.queue.append(run)

        jobs_ = JobManager(EventBus(), spawn=spawn, **jobs)
        return Direct(saves_router, "saves", SavesService(jobs_, lambda: self.loc), jobs_)

    def outside(self, name="picked.sl2", data=SAVE):
        p = self.tmp / name
        p.write_bytes(data)
        return p

    def entries(self):
        return save_library.load(self.folder)["entries"]

    def library_files(self):
        lib = save_library.folder_for(self.folder)
        return sorted(p.name for p in lib.rglob("*") if p.is_file()) if lib.exists() else []

    def backup_files(self):
        folder = save_backups.backups(self.folder)
        return sorted(p.name for p in folder.glob("*.bak")) if folder.exists() else []


def _only_saves_start_with_SAVE(monkeypatch):
    # the one stand-in: invented bytes count as a save when they start with SAVE; check_whole itself is the real one
    monkeypatch.setattr(save_regulation, "is_pc_save", lambda data: data.startswith(b"SAVE"))


@pytest.fixture
def world(tmp_path, monkeypatch):
    _only_saves_start_with_SAVE(monkeypatch)
    return World(tmp_path)


@pytest.fixture
def queued(tmp_path, monkeypatch):
    _only_saves_start_with_SAVE(monkeypatch)
    return World(tmp_path, queue=[])


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def start(s, name, params):
    return s.run(name, params).job_id


def done(s, job_id):
    snap = s.jobs.get(job_id)
    assert snap is not None and snap.state == "done", snap
    return snap.result


def failed(s, job_id):
    snap = s.jobs.get(job_id)
    assert snap is not None and snap.state == "failed" and snap.error is not None, snap
    return snap.error


def refused(s, name, params) -> str:
    with pytest.raises(OperationError) as e:
        s.run(name, params)
    return e.value.code


def fast_reads(monkeypatch, retry_for=0.05):
    """The settled read with no pauses and a short lock wait, in both places that read a source."""
    real = files.read_settled

    def quick(p):
        return real(p, pause=0, retry_for=retry_for)

    monkeypatch.setattr(save_library, "read_settled", quick)
    monkeypatch.setattr(save_fix, "read_settled", quick)


def source_acts(monkeypatch, src, steps):
    """files.open for src: the n-th open first runs steps[n] (an exception to raise, or a callable that changes the
    file as another program would); later opens are plain. Returns the list of opens."""
    opens, real = [], builtins.open

    def fake(path, *a, **kw):
        if os.path.normcase(str(path)) != os.path.normcase(str(src)):
            return real(path, *a, **kw)
        n = len(opens)
        opens.append(n)
        step = steps[n] if n < len(steps) else None
        if isinstance(step, BaseException):
            raise step
        if step is not None:
            step()
        return real(path, *a, **kw)

    monkeypatch.setattr(files, "open", fake, raising=False)
    return opens


def append(src, extra=b"!"):
    def go():
        with open(src, "ab") as f:
            f.write(extra)

    return go


def lock_error(winerror):
    e = PermissionError(13, "in use")
    e.winerror = winerror  # type: ignore[attr-defined]
    return e


# ------------------------------------------------------------------------------------ results and the source
def test_save_copy_adds_the_copy_and_says_what_it_made(world):
    s = world.session()
    before = fingerprint(world.save)
    r = done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "  My   run "}))
    [entry] = world.entries()
    assert r == {"source": str(world.save), "entry_id": entry["id"], "name": "My run"}
    assert entry["sha256"] == hashlib.sha256(SAVE).hexdigest() and entry["size"] == len(SAVE)
    assert (save_library.folder_for(world.folder) / entry["file"]).read_bytes() == SAVE
    assert fingerprint(world.save) == before


def test_back_up_takes_one_backup_per_save_with_the_bytes_and_modified_time(world):
    s = world.session()
    before = {p: fingerprint(p) for p in (world.save, world.save2)}
    r = done(s, start(s, "saves.back_up", {"everything": True}))
    assert r["saves"] == [str(world.save), str(world.save2)] and len(r["backups"]) == 2
    for save, bak in zip((world.save, world.save2), r["backups"], strict=True):
        assert open(bak, "rb").read() == save.read_bytes()
        assert os.stat(bak).st_mtime_ns == before[save][1]
    assert {p: fingerprint(p) for p in before} == before


def test_import_adds_each_file_and_leaves_the_picked_files_alone(world):
    s = world.session()
    one, two = world.outside("a.sl2"), world.outside("b.sl2", SAVE2)
    before = {p: fingerprint(p) for p in (one, two)}
    r = done(s, start(s, "saves.import_files", {"files": [str(one), str(two)]}))
    assert r["failed"] == [] and [i["file"] for i in r["imported"]] == [str(one), str(two)]
    assert {e["id"] for e in world.entries()} == {i["entry_id"] for i in r["imported"]}
    assert {p: fingerprint(p) for p in before} == before


def test_a_single_import_takes_the_given_name(world):
    s = world.session()
    r = done(s, start(s, "saves.import_files", {"files": [str(world.outside())], "name": "Boss run"}))
    assert [i["name"] for i in r["imported"]] == ["Boss run"] == [e["name"] for e in world.entries()]


def test_the_source_is_never_modified_when_an_operation_fails(world, monkeypatch):
    s = world.session()
    bad = world.outside("bad.sl2", NOT_A_SAVE)
    before = {p: fingerprint(p) for p in (world.save, bad)}
    with monkeypatch.context() as m:
        m.setattr(save_library, "_sha256", lambda p: "wrong")  # the copy "does not read back the same"
        assert failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"})).code == "failed"
    assert failed(s, start(s, "saves.import_files", {"files": [str(bad)]})).code == "not_imported"
    with monkeypatch.context() as m:
        m.setattr(save_fix, "read_settled", lambda p: (_ for _ in ()).throw(files.Unsettled("changing")))
        assert failed(s, start(s, "saves.back_up", {"paths": [str(world.save)]})).code == "source_changed"
    assert {p: fingerprint(p) for p in before} == before


# --------------------------------------------------------------------------------- a source that moves or locks
def test_a_source_that_keeps_changing_is_source_changed_and_nothing_is_added(world, monkeypatch):
    fast_reads(monkeypatch)
    s = world.session()
    source_acts(monkeypatch, world.save, [append(world.save)] * 50)
    err = failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))
    assert err.code == "source_changed"
    assert world.entries() == [] and world.library_files() == []


def test_a_source_that_settles_after_one_change_is_copied_as_its_final_bytes(world, monkeypatch):
    fast_reads(monkeypatch)
    s = world.session()
    source_acts(monkeypatch, world.save, [append(world.save, b"TAIL")])
    r = done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))
    [entry] = world.entries()
    final = world.save.read_bytes()
    assert final == SAVE + b"TAIL" and entry["id"] == r["entry_id"]
    assert (save_library.folder_for(world.folder) / entry["file"]).read_bytes() == final
    assert entry["sha256"] == hashlib.sha256(final).hexdigest() and entry["size"] == len(final)


def test_a_backup_of_a_source_that_keeps_changing_is_source_changed_and_makes_no_backup(world, monkeypatch):
    fast_reads(monkeypatch)
    s = world.session()
    source_acts(monkeypatch, world.save, [append(world.save)] * 50)
    assert failed(s, start(s, "saves.back_up", {"paths": [str(world.save)]})).code == "source_changed"
    assert world.backup_files() == []


def test_an_import_of_a_source_that_keeps_changing_is_listed_as_failed(world, monkeypatch):
    fast_reads(monkeypatch)
    s = world.session()
    moving, steady = world.outside("moving.sl2"), world.outside("steady.sl2", SAVE2)
    source_acts(monkeypatch, moving, [append(moving)] * 50)
    r = done(s, start(s, "saves.import_files", {"files": [str(moving), str(steady)]}))
    assert r["failed"] == [{"file": str(moving), "code": "source_changed"}]
    assert [i["file"] for i in r["imported"]] == [str(steady)] and len(world.entries()) == 1


def test_a_source_locked_for_a_moment_is_retried_and_copied(world, monkeypatch):
    fast_reads(monkeypatch, retry_for=5)
    s = world.session()
    opens = source_acts(monkeypatch, world.save, [lock_error(32), lock_error(33)])
    done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))
    assert len(opens) == 3 and len(world.entries()) == 1


def test_a_source_locked_for_good_is_source_locked_and_nothing_is_added(world, monkeypatch):
    fast_reads(monkeypatch)
    s = world.session()
    source_acts(monkeypatch, world.save, [lock_error(32)] * 100_000)
    assert failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"})).code == "source_locked"
    assert world.entries() == [] and world.library_files() == []
    assert failed(s, start(s, "saves.back_up", {"paths": [str(world.save)]})).code == "source_locked"
    assert world.backup_files() == []


def test_access_denied_on_the_source_fails_at_once_without_waiting(world, monkeypatch):
    fast_reads(monkeypatch, retry_for=30)
    s = world.session()
    opens = source_acts(monkeypatch, world.save, [lock_error(5)] * 100)
    assert failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"})).code == "failed"
    assert len(opens) == 1 and world.entries() == []


# ---------------------------------------------------------------------------------- invalid and vanished sources
def test_a_save_that_disappears_after_validation_is_not_found(queued):
    s = queued.session()
    job = start(s, "saves.save_copy", {"path": str(queued.save), "name": "X"})  # validated and queued, not yet run
    queued.save.unlink()
    queued.queue.pop()()
    assert failed(s, job).code == "not_found" and queued.entries() == []


def test_a_backup_of_a_save_that_disappears_after_validation_is_not_found(queued):
    s = queued.session()
    job = start(s, "saves.back_up", {"paths": [str(queued.save)]})
    queued.save.unlink()
    queued.queue.pop()()
    assert failed(s, job).code == "not_found" and queued.backup_files() == []


def test_a_picked_file_that_disappears_after_validation_is_listed_not_found(queued):
    s = queued.session()
    gone, here = queued.outside("gone.sl2"), queued.outside("here.sl2", SAVE2)
    job = start(s, "saves.import_files", {"files": [str(gone), str(here)]})
    gone.unlink()
    queued.queue.pop()()
    r = done(s, job)
    assert r["failed"] == [{"file": str(gone), "code": "not_found"}] and len(r["imported"]) == 1


def test_a_single_picked_file_that_is_not_there_is_refused_not_found(world):
    assert refused(world.session(), "saves.import_files", {"files": [str(world.tmp / "nope.sl2")]}) == "not_found"
    assert world.entries() == []


def test_a_directory_is_not_importable(world):
    s = world.session()
    folder = world.tmp / "a-folder.sl2"
    folder.mkdir()
    assert refused(s, "saves.import_files", {"files": [str(folder)]}) == "not_found"
    r = done(s, start(s, "saves.import_files", {"files": [str(folder), str(world.outside())]}))
    assert [f["file"] for f in r["failed"]] == [str(folder)] and len(r["imported"]) == 1


def test_a_file_that_is_not_a_save_is_listed_not_a_save_and_not_added(world):
    s = world.session()
    text = world.outside("notes.sl2", NOT_A_SAVE)
    before = fingerprint(text)
    r = done(s, start(s, "saves.import_files", {"files": [str(text), str(world.outside("ok.sl2"))]}))
    assert r["failed"] == [{"file": str(text), "code": "not_a_save"}] and len(world.entries()) == 1
    assert failed(s, start(s, "saves.import_files", {"files": [str(text)]})).code == "not_imported"
    assert len(world.entries()) == 1 and fingerprint(text) == before


def test_a_file_that_is_too_big_is_refused_before_it_is_read(world, monkeypatch):
    monkeypatch.setattr(save_library, "MAX_SAVE_BYTES", 10)
    s = world.session()
    big = world.outside("big.sl2")
    opens = source_acts(monkeypatch, big, [])
    assert failed(s, start(s, "saves.import_files", {"files": [str(big)]})).code == "not_imported"
    assert opens == []  # never opened, so never read into memory
    assert failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"})).code == "not_a_save"
    assert world.entries() == [] and world.library_files() == []


# The job's error should carry the details the service raised (not_imported: failed, a part-way back up: backed_up);
# the job's error is raised again with them (OperationError.from_info).


@pytest.mark.parametrize("data", [NOT_A_SAVE, b"x"])
def test_an_import_where_every_file_is_bad_names_each_failure_in_the_details(world, data):
    s = world.session()
    a, b = world.outside("a.sl2", data), world.outside("b.sl2", NOT_A_SAVE)
    err = failed(s, start(s, "saves.import_files", {"files": [str(a), str(b)]}))
    assert err.code == "not_imported"
    assert err.details["failed"] == [{"file": str(a), "code": "not_a_save"}, {"file": str(b), "code": "not_a_save"}]


def test_a_file_too_big_is_named_not_a_save_in_the_details(world, monkeypatch):
    monkeypatch.setattr(save_library, "MAX_SAVE_BYTES", 10)
    big = world.outside("big.sl2")
    s = world.session()
    err = failed(s, start(s, "saves.import_files", {"files": [str(big)]}))
    assert err.details["failed"] == [{"file": str(big), "code": "not_a_save"}]


# ---------------------------------------------------------------------------------------- the destination
def _refuse_the_new_copy(monkeypatch, world, times):
    """os.replace onto a Library copy (*.sl2 in the Library folder) refused with a sharing violation `times` times."""
    real, lib, refusals = os.replace, str(save_library.folder_for(world.folder)), []

    def replace(src, dst, *a, **k):
        if str(dst).startswith(lib) and str(dst).endswith(".sl2") and len(refusals) < times:
            refusals.append(dst)
            raise lock_error(32)
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", replace)
    return refusals


def test_a_destination_locked_for_a_moment_is_waited_out(world, monkeypatch):
    refusals = _refuse_the_new_copy(monkeypatch, world, 1)
    s = world.session()
    done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))
    assert len(refusals) == 1 and len(world.entries()) == 1


def test_a_destination_locked_for_good_fails_with_no_entry_and_no_stray_file(world, monkeypatch):
    _refuse_the_new_copy(monkeypatch, world, 10**9)
    s = world.session()
    err = failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))  # waits its 2 seconds out
    assert err.code == "failed" and world.entries() == []
    assert [n for n in world.library_files() if n.endswith((".tmp", ".sl2"))] == []


# --------------------------------------------------------------------------------------- an interrupted copy
def test_a_copy_that_fails_its_check_adds_nothing(world, monkeypatch):
    s = world.session()
    monkeypatch.setattr(save_library, "_sha256", lambda p: "not the same")
    err = failed(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))
    assert err.code == "failed" and "did not read back" in err.message
    assert world.entries() == [] and world.library_files() == []


def test_a_manifest_that_cannot_be_written_removes_the_new_copy_and_changes_nothing(world, monkeypatch):
    s = world.session()
    done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "First"}))
    lib = save_library.folder_for(world.folder)
    before = {p.name: p.read_bytes() for p in lib.rglob("*") if p.is_file()}

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(save_library, "_save", boom)
    err = failed(s, start(s, "saves.save_copy", {"path": str(world.save2), "name": "Second"}))
    assert err.code == "failed" and "disk full" in err.message
    assert {p.name: p.read_bytes() for p in lib.rglob("*") if p.is_file()} == before  # the Library as it was
    assert [e["name"] for e in world.entries()] == ["First"]


# ------------------------------------------------------------------------------------------- duplicates
def test_the_same_source_saved_twice_makes_two_independent_entries(world):
    s = world.session()
    a = done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "Same"}))
    b = done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "Same"}))
    assert a["entry_id"] != b["entry_id"]
    entries = world.entries()
    assert len(entries) == 2 and len({e["file"] for e in entries}) == 2
    assert all((save_library.folder_for(world.folder) / e["file"]).read_bytes() == SAVE for e in entries)


def test_two_backups_in_one_second_keep_both_under_distinct_names(world, monkeypatch):
    def strftime(fmt):
        return "20260101-000000" if fmt == "%Y%m%d-%H%M%S" else "2026-01-01 00:00:00"

    monkeypatch.setattr(save_fix, "time", SimpleNamespace(strftime=strftime))
    s = world.session()
    first = done(s, start(s, "saves.back_up", {"paths": [str(world.save)]}))["backups"][0]
    second = done(s, start(s, "saves.back_up", {"paths": [str(world.save)]}))["backups"][0]
    assert first.endswith("ER0000.sl2.20260101-000000.bak") and second.endswith("ER0000.sl2.20260101-000000-2.bak")
    assert open(first, "rb").read() == open(second, "rb").read() == SAVE


# ------------------------------------------------------------------------------------------------ back up
def test_back_up_of_a_path_that_is_not_listed_is_not_found_and_makes_no_folder(world):
    s = world.session()
    stray = world.outside("stray.sl2")
    assert refused(s, "saves.back_up", {"paths": [str(stray)]}) == "not_found"
    assert refused(s, "saves.back_up", {"paths": [str(world.save), str(stray)]}) == "not_found"
    assert not save_backups.backups(world.folder).exists() and world.backup_files() == []


def test_back_up_everything_with_no_saves_is_no_saves(world):
    world.save.unlink()
    world.save2.unlink()
    assert refused(world.session(), "saves.back_up", {"everything": True}) == "no_saves"


def test_back_up_with_nothing_named_is_invalid_params(world):
    assert refused(world.session(), "saves.back_up", {}) == "invalid_params"


def _second_save_changes(monkeypatch):
    real = save_fix.read_settled

    def read(path):
        if path.name == "ER0000.co2":
            raise files.Unsettled("kept changing")
        return real(path)

    monkeypatch.setattr(save_fix, "read_settled", read)


def test_a_back_up_that_fails_part_way_has_the_failures_code_and_keeps_the_first_backup(world, monkeypatch):
    s = world.session()
    _second_save_changes(monkeypatch)
    err = failed(s, start(s, "saves.back_up", {"everything": True}))
    assert err.code == "source_changed"
    [kept] = world.backup_files()
    assert kept.startswith("ER0000.sl2.") and (save_backups.backups(world.folder) / kept).read_bytes() == SAVE


def test_a_back_up_that_fails_part_way_names_the_backup_it_took(world, monkeypatch):
    s = world.session()
    _second_save_changes(monkeypatch)
    err = failed(s, start(s, "saves.back_up", {"everything": True}))
    [first] = err.details["backed_up"]
    assert os.path.basename(first) == world.backup_files()[0] and err.details["save"] == str(world.save2)


# ------------------------------------------------------------------------------------------------ the gates
def test_back_up_is_refused_while_the_game_runs_but_save_copy_and_import_are_not(world):
    s = world.session(game_running=lambda: True)
    with pytest.raises(Busy) as e:
        s.run("saves.back_up", {"everything": True})
    assert e.value.info.details["reason"] == "game_running" and world.backup_files() == []
    done(s, start(s, "saves.save_copy", {"path": str(world.save), "name": "X"}))
    done(s, start(s, "saves.import_files", {"files": [str(world.outside())]}))
    assert len(world.entries()) == 2 and world.save.read_bytes() == SAVE


CALLS = [
    ("saves.back_up", lambda w: {"everything": True}),
    ("saves.save_copy", lambda w: {"path": str(w.save), "name": "X"}),
    ("saves.import_files", lambda w: {"files": [str(w.outside())]}),
]


@pytest.mark.parametrize(("name", "params"), CALLS)
def test_each_is_refused_beside_another_writing_job(queued, name, params):
    s = queued.session()
    s.jobs.start(lambda ctx: None, title="a running write")  # queued, never finishes: the writer slot is held
    with pytest.raises(Busy) as e:
        s.run(name, params(queued))
    assert e.value.info.details["reason"] == "job"
    assert queued.entries() == [] and queued.backup_files() == []


@pytest.mark.parametrize(("name", "params"), CALLS)
def test_each_is_refused_while_outside_work_is_running(world, name, params):
    s = world.session(external_busy=lambda: True)
    with pytest.raises(Busy):
        s.run(name, params(world))
    assert world.entries() == [] and world.backup_files() == []


def test_two_save_copies_cannot_run_at_once(queued):
    s = queued.session()
    start(s, "saves.save_copy", {"path": str(queued.save), "name": "One"})
    with pytest.raises(Busy):
        s.run("saves.save_copy", {"path": str(queued.save2), "name": "Two"})
    queued.queue.pop()()
    assert [e["name"] for e in queued.entries()] == ["One"]


def test_a_save_copy_can_start_once_the_one_before_it_has_finished(queued):
    s = queued.session()
    first = start(s, "saves.save_copy", {"path": str(queued.save), "name": "One"})
    queued.queue.pop()()
    done(s, first)
    start(s, "saves.save_copy", {"path": str(queued.save2), "name": "Two"})
    queued.queue.pop()()
    assert [e["name"] for e in queued.entries()] == ["One", "Two"]


# ------------------------------------------------------------------------------------------------ import
def test_an_import_with_one_bad_file_lists_what_was_imported_and_what_failed(world):
    s = world.session()
    good, bad = world.outside("good.sl2"), world.outside("bad.sl2", NOT_A_SAVE)
    r = done(s, start(s, "saves.import_files", {"files": [str(bad), str(good)]}))
    assert [i["file"] for i in r["imported"]] == [str(good)]
    assert r["failed"] == [{"file": str(bad), "code": "not_a_save"}]
    assert len(world.entries()) == 1


def test_an_import_where_every_file_is_bad_is_not_imported_and_adds_nothing(world):
    s = world.session()
    a, b = world.outside("a.sl2", NOT_A_SAVE), world.outside("b.sl2", b"x")
    assert failed(s, start(s, "saves.import_files", {"files": [str(a), str(b)]})).code == "not_imported"
    assert world.entries() == []


def test_a_name_with_several_files_is_invalid_params(world):
    picked = [str(world.outside("a.sl2")), str(world.outside("b.sl2"))]
    assert refused(world.session(), "saves.import_files", {"files": picked, "name": "Both"}) == "invalid_params"
    assert world.entries() == []


def test_no_files_is_invalid_params(world):
    assert refused(world.session(), "saves.import_files", {"files": []}) == "invalid_params"


@pytest.mark.parametrize("name", ["", "   ", "\t\n"])
def test_an_empty_or_blank_name_is_invalid_name(world, name):
    s = world.session()
    assert refused(s, "saves.import_files", {"files": [str(world.outside())], "name": name}) == "invalid_name"
    assert refused(s, "saves.save_copy", {"path": str(world.save), "name": name}) == "invalid_name"
    assert world.entries() == []


def test_save_copy_of_an_unlisted_path_is_not_found(world):
    assert refused(world.session(), "saves.save_copy", {"path": str(world.outside()), "name": "X"}) == "not_found"
    assert world.entries() == [] and world.library_files() == []


def test_import_without_a_save_folder_is_no_saves(world):
    world.save.unlink()
    world.save2.unlink()
    picked = world.outside("x.sl2")
    assert refused(world.session(), "saves.import_files", {"files": [str(picked)]}) == "no_saves"
    assert picked.read_bytes() == SAVE


# ----------------------------------------------------- the callers of fix.backup still take the same backup
def test_the_manual_backup_is_of_the_saves_bytes_as_they_are_now(world):
    bak = saves_service.back_up_now(world.save, loc=world.loc)
    assert bak.read_bytes() == SAVE and save_fix.read_manifest(bak)["action"] == "Manual backup"
    world.save.write_bytes(SAVE2)
    assert saves_service.back_up_now(world.save, loc=world.loc).read_bytes() == SAVE2
