"""The Settings page's folder-layout changes: check, then the Confirm in the presenter's words, then one job with
exactly what was checked; refusals and stale answers start nothing. The real SettingsService runs over a real
JobManager (work runs inline unless a test holds it); only the folder moves themselves are faked."""

from pathlib import Path

import pytest
from bayle.adapters.persistence.settings_file import load_settings, save_settings
from bayle.errors import Cancelled
from bayle.modules.settings import locations as layout_service
from bayle.modules.settings.service import SettingsService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from PySide6.QtCore import QObject

from bayle_qt.notifications import Notifier
from bayle_qt.pages.settings.adapter import SettingsAdapter
from support import er

STALE = "Things changed since you were asked. Ask again."


class Host(QObject):
    """The window's side of the page: a real service and job manager; work for a job waits in `held` when `hold`."""

    busy = False

    def __init__(self):
        super().__init__()
        self.hold, self.held, self.game_running = False, [], False
        self.jobs = JobManager(EventBus(), spawn=self._spawn, game_running=lambda: self.game_running)
        self.job_manager = self.jobs
        self.settings_service = SettingsService(self.jobs, er)
        self.picked: Path | None = None

    def _spawn(self, run, name=None):
        if self.hold:
            self.held.append(run)
        else:
            run()

    def release(self):
        while self.held:
            self.held.pop(0)()

    def run_in_background(self, work, on_result):
        on_result(work())

    def pick_folder(self, title):
        return self.picked

    def settings_changed(self, key):
        pass

    def update_state(self):
        return {"line": "", "tone": "muted", "notices": []}

    def watch_updates(self, call):
        pass


class Page:
    """The adapter with what the user would see: toasts and Confirms, and a way to answer a Confirm."""

    def __init__(self, host):
        self.host, self.toasts, self.confirms = host, [], []
        self.notifier = Notifier()
        self.notifier.toastRequested.connect(lambda text, error: self.toasts.append((text, error)))
        self.notifier.confirmRequested.connect(lambda *a: self.confirms.append(a))
        self.adapter = SettingsAdapter(host, self.notifier)

    def answer(self, ok):
        self.notifier.answer(self.confirms[-1][0], ok)

    def jobs_started(self):
        return self.host.jobs._count


@pytest.fixture
def calls(monkeypatch):
    """Every layout change that reached the folders, by kind; the facts a relocate check reads."""
    got = {"rename": [], "relocate": [], "move_all": []}
    monkeypatch.setattr(layout_service, "rename_layout", lambda loc, **names: got["rename"].append(names) or {})

    def relocate(loc, new, progress=None, cancel=None):
        if cancel is not None and cancel():
            raise Cancelled()
        got["relocate"].append(Path(new))
        return {}

    monkeypatch.setattr(layout_service, "relocate", relocate)
    monkeypatch.setattr(layout_service, "profiles_facts", lambda loc: (3, 5 * 1024 * 1024))
    monkeypatch.setattr(layout_service, "free_bytes", lambda path: 10**12)
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [])
    monkeypatch.setattr(
        layout_service, "move_all", lambda loc, found: got["move_all"].append(list(found)) or len(found)
    )
    return got


@pytest.fixture
def page(qt_app, calls):
    p = Page(Host())
    yield p
    p.notifier.drop_pending()


def rename_draft(page, value="x-{game}"):
    page.adapter.editLayout("pattern", value)
    page.adapter.applyLayout()


# ---- rename
def test_rename_confirms_old_to_new_then_starts_one_job_with_the_checked_names(page, calls):
    rename_draft(page)
    assert len(page.confirms) == 1 and page.jobs_started() == 0
    _, title, changes, safety, apply, _ = page.confirms[0]
    assert title == "Rename folders?" and apply == "Rename" and safety == "Undo in Activity."
    assert changes == [f"Game folder: {load_settings().game_folder_pattern} becomes x-{{game}}."]
    page.answer(True)
    assert page.jobs_started() == 1 and calls["rename"] == [{"pattern": "x-{game}"}]
    assert page.toasts == []


def test_cancelling_the_rename_confirm_starts_nothing(page, calls):
    rename_draft(page)
    page.answer(False)
    assert page.jobs_started() == 0 and calls["rename"] == [] and page.toasts == []


def test_a_rename_with_nothing_changed_or_a_bad_name_never_asks(page, calls):
    page.adapter.applyLayout()  # no draft change
    page.adapter.editLayout("pattern", "oops")  # no {game}
    page.adapter.applyLayout()
    assert page.confirms == [] and page.jobs_started() == 0
    errors = page.adapter._layout_check["errors"]
    assert list(errors) == ["pattern"] and errors["pattern"]


def test_a_rename_checked_then_changed_in_settings_is_refused_as_stale(page, calls):
    rename_draft(page)
    save_settings(game_folder_pattern="y-{game}")  # another change lands while the Confirm is open
    page.answer(True)
    assert page.toasts == [(STALE, True)]
    assert page.jobs_started() == 0 and calls["rename"] == []


def test_a_rename_checked_then_saved_elsewhere_has_nothing_left_to_change(page, calls):
    rename_draft(page)
    save_settings(game_folder_pattern="x-{game}")
    page.answer(True)
    assert page.toasts == [("The names are the ones in use already.", True)]
    assert page.jobs_started() == 0 and calls["rename"] == []


# ---- refusals
def test_a_busy_job_manager_refuses_every_check_before_any_confirm(page, calls):
    page.host.hold = True
    page.host.jobs.start(lambda ctx: {}, title="Other")
    rename_draft(page)
    page.adapter.moveAll()
    assert page.confirms == [] and page.jobs_started() == 1
    assert page.toasts == [
        ("Wait for the current job.. Another job is running.", True),
        ("Another job is running.", False),
    ]


def test_a_running_game_refuses_the_rename(page, calls):
    page.host.game_running = True
    rename_draft(page)
    assert page.confirms == [] and page.jobs_started() == 0 and calls["rename"] == []
    assert page.toasts == [("The game is running.. Close it first.", True)]


def test_the_game_starting_after_the_confirm_refuses_the_start(page, calls):
    rename_draft(page)
    page.host.game_running = True
    page.answer(True)
    assert page.toasts == [("The game is running.. Close it first.", True)] and calls["rename"] == []


# ---- relocate
def test_relocate_confirm_shows_count_size_and_path_warnings_then_starts_with_the_saved_root(page, calls, tmp_path):
    save_settings(profiles_root=str(tmp_path / "old"))
    page.adapter.refresh()
    page.host.picked = tmp_path / "OneDrive" / "profiles"
    page.adapter.changeProfilesFolder()
    _, title, changes, safety, apply, _ = page.confirms[0]
    assert title == f"Move your profiles and mods to {page.host.picked}?" and apply == "Move"
    assert changes[0] == "3 profiles, 5.0 MB."
    assert len(changes) == 2 and changes[1].startswith("This folder looks synced by OneDrive")
    assert safety == "Undo in Activity." and page.jobs_started() == 0
    page.answer(True)
    assert calls["relocate"] == [page.host.picked] and page.jobs_started() == 1


def test_relocate_warns_when_there_is_too_little_room(page, calls, tmp_path, monkeypatch):
    monkeypatch.setattr(layout_service, "free_bytes", lambda path: 1024)
    page.host.picked = tmp_path / "small"
    page.adapter.changeProfilesFolder()
    assert any(w.startswith("There is not enough free space") for w in page.confirms[0][2])


def test_relocate_with_no_folder_picked_or_a_cancelled_confirm_starts_nothing(page, calls, tmp_path):
    page.adapter.changeProfilesFolder()  # the picker was dismissed
    assert page.confirms == []
    page.host.picked = tmp_path / "new"
    page.adapter.changeProfilesFolder()
    page.answer(False)
    assert page.jobs_started() == 0 and calls["relocate"] == []


def test_relocate_with_the_saved_root_changed_since_the_check_is_stale(page, calls, tmp_path):
    page.host.picked = tmp_path / "new"
    page.adapter.changeProfilesFolder()
    save_settings(profiles_root=str(tmp_path / "elsewhere"))
    page.answer(True)
    assert page.toasts == [(STALE, True)] and page.jobs_started() == 0 and calls["relocate"] == []


def test_cancelling_the_running_relocate_stops_the_job(page, calls, tmp_path):
    page.host.hold = True
    page.host.picked = tmp_path / "new"
    page.adapter.changeProfilesFolder()
    page.answer(True)
    job_id = page.adapter._move_job
    assert page.jobs_started() == 1 and job_id
    page.adapter.cancelMove()
    page.host.release()
    assert page.host.jobs.get(job_id).state == "cancelled"
    assert calls["relocate"] == []


# ---- move all
def test_move_all_with_nothing_outside_says_so_without_an_error(page, calls):
    page.adapter.moveAll()
    assert page.confirms == [] and page.jobs_started() == 0
    assert page.toasts == [("No profiles are outside Bayle's folder.", False)]


def test_move_all_confirms_the_list_then_starts_with_it(page, calls, monkeypatch, tmp_path):
    found = [tmp_path / "a.me3", tmp_path / "b.me3"]
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: found)
    page.adapter.moveAll()
    _, title, changes, _, apply, _ = page.confirms[0]
    assert title == "Move all profiles into Bayle's folder?" and apply == "Move all"
    assert changes == ["2 profiles move: a, b."] and page.jobs_started() == 0
    page.answer(True)
    assert calls["move_all"] == [found] and page.jobs_started() == 1


def test_move_all_whose_list_changed_since_the_check_is_stale(page, calls, monkeypatch, tmp_path):
    found = [tmp_path / "a.me3"]
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: found)
    page.adapter.moveAll()
    found.append(tmp_path / "b.me3")
    page.answer(True)
    assert page.toasts == [(STALE, False)] and page.jobs_started() == 0 and calls["move_all"] == []
