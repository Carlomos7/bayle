"""The Saves adapter over a real Session (no window): a restore is asked in the presenter's words, the answer starts the
session's job, the adapter follows it, reads the page again and tells the result with an Undo that takes it back."""

from pathlib import Path

import pytest

from bayle.errors import OperationError
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.saves import regulation as save_regulation
from bayle.services import saves as saves_service
from bayle.services.saves_page import SavesService
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.ui.notifications import Notifier
from bayle.ui.pages.saves.adapter import SavesAdapter
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore

OLD, NEW = b"old save " * 40, b"new save " * 40


class Host:
    busy = False
    game_running = False

    def __init__(self, loc):
        self.locations = loc
        jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
        self.saves_service = SavesService(jobs, lambda: loc)
        self.session = Session(jobs, plans=PlanStore(), locations=lambda: loc, services={"saves": self.saves_service})

    def run_in_background(self, work, on_result):
        on_result(work())

    def follow_job(self, job_id, done):
        done(self.session.jobs.get(job_id))

    def pick_file(self, title, filters):
        return None

    def open_path(self, path):
        pass

    def saves_in_use(self):
        return {}


@pytest.fixture
def flow(tmp_path, monkeypatch):
    root = tmp_path / "saves"
    save = root / "76561198000000001" / "ER0000.sl2"
    save.parent.mkdir(parents=True)
    save.write_bytes(OLD)
    loc = Locations(catalog.ELDEN_RING, Overrides(saves_dir=str(root)))
    monkeypatch.setattr(save_regulation, "is_pc_save", lambda data: True)
    monkeypatch.setattr(
        saves_service,
        "save_info",
        lambda path, game=None, kind=None, *, loc: {"path": path, "name": path.name, "kind": "Standard"},
    )
    notifier, said = Notifier(), {"asked": [], "toasts": [], "actions": []}
    notifier.confirmFullRequested.connect(lambda token, words: said["asked"].append((token, words)))
    notifier.toastRequested.connect(lambda text, error: said["toasts"].append((text, error)))
    notifier.toastActionRequested.connect(lambda text, error, action, token: said["actions"].append((text, token)))
    adapter = SavesAdapter(Host(loc), notifier)
    adapter.presenter.card = lambda info, role, running: {"path": str(info["path"])}  # the cards are not under test
    return adapter, notifier, said, save


def test_a_restore_is_asked_runs_as_a_job_is_told_with_undo_and_undo_takes_it_back(flow):
    adapter, notifier, said, save = flow
    adapter.host.session.run("saves.back_up", {"everything": True})  # the backup to restore
    adapter.refresh()
    backup = adapter.host.session.snapshot("saves").backups[0]["path"]
    save.write_bytes(NEW)
    adapter.restoreBackup(str(backup), str(save))
    ((token, words),) = said["asked"]
    assert "ER0000.sl2" in words["title"] and save.read_bytes() == NEW  # asked; nothing written yet
    notifier.answerWith(token, True, False)
    assert save.read_bytes() == OLD
    ((text, action),) = said["actions"]
    assert text == "ER0000.sl2 is back as it was in the backup"
    notifier.toastAction(action)  # the toast's Undo
    assert save.read_bytes() == NEW


def test_a_declined_restore_writes_nothing(flow):
    adapter, notifier, said, save = flow
    adapter.host.session.run("saves.back_up", {"everything": True})
    backup = adapter.host.session.snapshot("saves").backups[0]["path"]
    save.write_bytes(NEW)
    adapter.restoreBackup(str(backup), str(save))
    notifier.answerWith(said["asked"][0][0], False, False)
    assert save.read_bytes() == NEW and said["actions"] == []


def test_the_page_reads_through_the_session(flow):
    adapter, _notifier, _said, save = flow
    adapter.refresh()
    assert [str(i["path"]) for i in adapter._infos] == [str(save)]


# ---- the upkeep of copies and backups: straight to the service, asked in the presenter's words
def _no_group_b_runs(adapter):
    real = adapter.host.session.run

    def run(name, params=None):
        assert name not in {f"saves.{n}" for n in ("adopt_legacy", "keep_as", "keep_backup", "rename_copy")}
        assert name not in {f"saves.{n}" for n in ("finish_stranded", "delete_backup", "remove_copy")}
        return real(name, params)

    adapter.host.session.run = run


def _backup(adapter):
    adapter.host.session.run("saves.back_up", {"everything": True})
    return str(adapter.host.saves_service.page().backups[0]["path"])


def _copy(adapter, save):
    adapter.host.session.run("saves.save_copy", {"path": str(save), "name": "mine"})
    ((folder, lib),) = adapter.host.saves_service.page().libraries.items()
    return str(folder), lib["entries"][0]["id"] if "entries" in lib else lib["rows"][0]["id"]


def test_delete_backup_asks_in_the_presenter_words_and_yes_removes_it(flow):
    adapter, notifier, said, _save = flow
    _no_group_b_runs(adapter)
    backup = _backup(adapter)
    adapter.deleteBackup(backup)
    ((token, words),) = said["asked"]
    assert words["title"] == "Remove this backup" and Path(backup).exists()
    notifier.answerWith(token, True, False)
    assert not Path(backup).exists() and ("Backup removed", False) in said["toasts"]


def test_delete_backup_declined_removes_nothing(flow):
    adapter, notifier, said, _save = flow
    backup = _backup(adapter)
    adapter.deleteBackup(backup)
    notifier.answerWith(said["asked"][0][0], False, False)
    assert Path(backup).exists() and said["toasts"] == []


def test_delete_backup_stale_asks_again_and_removes_only_when_confirmed(flow):
    adapter, notifier, said, _save = flow
    backup = _backup(adapter)
    adapter.deleteBackup(backup)
    Path(backup).write_bytes(b"changed" * 10)  # it changed after the question was shown
    notifier.answerWith(said["asked"][0][0], True, False)
    assert len(said["asked"]) == 2 and Path(backup).exists()
    notifier.answerWith(said["asked"][1][0], True, False)
    assert not Path(backup).exists()


def test_delete_backup_not_listed_is_an_error_toast(flow):
    adapter, _notifier, said, save = flow
    adapter.deleteBackup(str(save.parent / "nothing.bak"))
    assert said["asked"] == [] and said["toasts"][-1][1] is True


def test_remove_copy_asks_then_yes_removes_no_keeps(flow):
    adapter, notifier, said, save = flow
    _no_group_b_runs(adapter)
    folder, entry = _copy(adapter, save)
    adapter.removeCopy(folder, entry)
    ((token, words),) = said["asked"]
    assert words["title"] == "Remove 'mine' from the Library"
    notifier.answerWith(token, False, False)
    adapter.host.saves_service.check_remove_copy(folder, entry)  # still there
    adapter.removeCopy(folder, entry)
    notifier.answerWith(said["asked"][1][0], True, False)
    with pytest.raises(OperationError) as e:
        adapter.host.saves_service.check_remove_copy(folder, entry)
    assert e.value.code == "not_found"


def test_remove_copy_stale_asks_again_with_the_new_name(flow):
    adapter, notifier, said, save = flow
    folder, entry = _copy(adapter, save)
    adapter.removeCopy(folder, entry)
    adapter.host.saves_service.rename_copy(folder, entry, "other")
    notifier.answerWith(said["asked"][0][0], True, False)
    assert said["asked"][1][1]["title"] == "Remove 'other' from the Library"
    adapter.host.saves_service.check_remove_copy(folder, entry)  # nothing removed yet


def test_remove_copy_not_found_is_an_error_toast(flow):
    adapter, _notifier, said, save = flow
    folder, _entry = _copy(adapter, save)
    adapter.removeCopy(folder, "nope")
    assert said["asked"] == [] and said["toasts"][-1][1] is True


def test_keep_rename_and_finish_reach_the_service_without_session_run(flow):
    adapter, _notifier, said, save = flow
    _no_group_b_runs(adapter)
    backup = _backup(adapter)
    adapter.letAgeOut(backup)
    adapter.keepAs(backup, "kept one")
    assert ("Kept as 'kept one' in the Library", False) in said["toasts"]
    folder, entry = _copy(adapter, save)
    adapter.renameCopy(folder, entry, "renamed")
    assert adapter.host.saves_service.check_remove_copy(folder, entry) == "renamed"
    adapter.finishStranded(folder, "nope", True)  # not_found: told, not raised
    assert said["toasts"][-1][1] is True


# ---- Back up, Save a copy and Import: the service starts the job, the adapter follows it and words the end
def _no_session_runs(adapter):
    real = adapter.host.session.run

    def run(name, params=None):
        assert name not in {"saves.back_up", "saves.save_copy", "saves.import_files"}
        return real(name, params)

    adapter.host.session.run = run


def test_back_up_all_and_one_are_worded_and_carry_no_undo(flow):
    adapter, _n, said, save = flow
    _no_session_runs(adapter)
    adapter.backUpAll()
    adapter.backUpNow(str(save))
    assert said["toasts"][0] == ("Backed up 1 save file(s).", False)
    assert said["toasts"][1][0].startswith("Backed up ER0000.sl2 (") and said["actions"] == []


def test_save_copy_and_import_are_worded(flow, tmp_path):
    adapter, _n, said, save = flow
    _no_session_runs(adapter)
    adapter.saveCopy(str(save), "mine")
    assert said["toasts"][-1] == ("Saved a copy of ER0000.sl2 as 'mine'", False)
    adapter.importFile(str(save), "other")
    assert said["toasts"][-1] == ("Imported 'other' into the Library", False)
    adapter._libs = {"x": {}}  # the page has read a Library
    adapter._import_many([save, tmp_path / "missing.sl2"])
    assert said["toasts"][-1] == ("Imported 1 files into the Library. Not imported: missing.sl2", False)
    assert said["actions"] == []


class _Recorder:
    """Stands in for the service: records the call and hands out a job id."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*a, **k):
            self.calls.append((name, a, k))
            return "job-1"

        return call


def test_each_slot_calls_the_service_with_its_arguments_and_follows_the_job(flow):
    adapter, _n, _said, _save = flow
    rec, followed = _Recorder(), []
    adapter.host.saves_service = rec
    adapter.host.follow_job = lambda job_id, done: followed.append(job_id)
    adapter._libs = {"x": {}}
    adapter.backUpAll()
    adapter.backUpNow("a.sl2")
    adapter.saveCopy("a.sl2", "n")
    adapter.importFile("b.sl2", "m")
    adapter._import_many([Path("c.sl2"), Path("d.sl2")])
    got = [(n, a, {k: v for k, v in kw.items() if k != "title"}, "title" in kw) for n, a, kw in rec.calls]
    assert got == [
        ("back_up", (), {"everything": True}, True),
        ("back_up", (["a.sl2"],), {}, True),
        ("save_copy", ("a.sl2", "n"), {}, True),
        ("import_files", (["b.sl2"], "m"), {}, True),
        ("import_files", (["c.sl2", "d.sl2"],), {}, True),
    ]
    assert followed == ["job-1"] * 5


@pytest.mark.parametrize("reason,title", [("game_running", "Close Elden Ring first"), ("job", "A job is running")])
def test_a_service_refusal_to_start_toasts_like_the_gate(flow, reason, title):
    adapter, _n, said, save = flow
    from bayle.errors import Busy

    def refuse(*a, **k):
        raise Busy("no", {"reason": reason})

    adapter.host.saves_service.back_up = refuse
    adapter.backUpNow(str(save))
    assert said["toasts"] == [
        (f"{title}. " + adapter.presenter.refusal_busy("Elden Ring", reason == "game_running").body, True)
    ]


@pytest.mark.parametrize(
    "code,details,expected",
    [
        ("source_changed", {}, "The save changed while it was read. Try again when the game is not saving."),
        ("source_locked", {}, "Another program holds the file. Close it and try again."),
        ("not_a_save", {}, "That file is not a save file for this game."),
        ("library_unreadable", {}, "The Library cannot be read, so nothing was added."),
        ("library_busy", {}, "The Library is in use by another change. Try again in a moment."),
        (
            "not_imported",
            {"failed": [{"file": "C:/x/a.sl2", "code": "not_a_save"}, {"file": "b.sl2", "code": "x"}]},
            "None of these files could be imported: a.sl2, b.sl2",
        ),
        ("failed", {"backed_up": ["C:/b/one.bak"]}, "boom Backed up before it stopped: one.bak"),
    ],
)
def test_a_failed_job_is_worded_by_its_code(flow, code, details, expected):
    from bayle.errors import ErrorInfo
    from bayle.work.jobs import JobSnapshot

    adapter, _n, said, _save = flow
    snap = JobSnapshot("j", "t", "failed", error=ErrorInfo(code, "boom", details))
    adapter.host.saves_service.back_up = lambda *a, **k: "j"
    adapter.host.follow_job = lambda job_id, done: done(snap)
    adapter.backUpAll()
    assert said["toasts"] == [(expected, True)]


def test_an_unknown_failure_code_falls_back_to_the_message(flow):
    from bayle.errors import ErrorInfo
    from bayle.work.jobs import JobSnapshot

    adapter, _n, said, _save = flow
    adapter.host.saves_service.back_up = lambda *a, **k: "j"
    adapter.host.follow_job = lambda j, done: done(JobSnapshot("j", "t", "failed", error=ErrorInfo("odd", "It broke.")))
    adapter.backUpAll()
    assert said["toasts"] == [("It broke.", True)]
