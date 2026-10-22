"""The Saves adapter over a real Session (no window): a restore is asked in the presenter's words, the answer starts the
session's job, the adapter follows it, reads the page again and tells the result with an Undo that takes it back."""

import pytest

from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.saves import regulation as save_regulation
from bayle.services import saves as saves_service
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.ui.notifications import Notifier
from bayle.ui.pages.saves.adapter import SavesAdapter

OLD, NEW = b"old save " * 40, b"new save " * 40


class Host:
    busy = False
    game_running = False

    def __init__(self, loc):
        self.locations = loc
        self.session = Session(
            JobManager(EventBus(), spawn=lambda run, name=None: run()),
            plans=PlanStore(),
            locations=lambda: loc,
        )

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
