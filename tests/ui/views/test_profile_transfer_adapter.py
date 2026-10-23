"""The Export / Import page's adapter over a real Session: an export follows its job's events to a finished run, and
an import of a file it opened goes through the backend resource and ends with the profile changed."""

from pathlib import Path

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QGuiApplication

from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.ui.jobs import Jobs
from bayle.ui.notifications import Notifier
from bayle.ui.pages.profile_transfer.adapter import ProfileTransferAdapter
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore
from support import er

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n[[packages]]\nid = "flora"\npath = \'mod/flora\'\n'
)


class Host:
    busy = False
    game_running = False
    locations = er()

    def __init__(self, profile: Path, picked: Path | None = None):
        self.profile, self.picked, self.changed = profile, picked, []
        self.jobs = Jobs()
        self.session = Session(JobManager(EventBus()), plans=PlanStore(), locations=er)

    def run_in_background(self, work, on_result):
        self.jobs.start(lambda _progress: work(), on_result=on_result)

    def pick_folder(self, title):
        return self.picked

    def pick_file(self, title, filters):
        return self.picked

    def open_path(self, path):
        pass

    def profile_changed(self, note):
        self.changed.append(note)


def settle(ms: int = 50) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    QGuiApplication.processEvents()


def wait_done(page) -> dict:
    """Let the job's worker thread and the page's event delivery run until the export has ended."""
    for _ in range(100):
        settle()
        run = page._state()["ex"]["run"]
        if run["phase"] not in ("running", "idle"):
            return run
    raise AssertionError(page._state()["ex"]["run"])


def make(root: Path) -> Path:
    (root / "mod/flora").mkdir(parents=True)
    (root / "mod/flora/a.dcx").write_text("x")
    me3 = root / "my.me3"
    me3.write_text(PROFILE)
    return me3


def test_an_export_runs_as_a_session_job_and_shows_done(qt_app, tmp_path):
    host = Host(make(tmp_path / "a"), tmp_path / "out")
    page = ProfileTransferAdapter(host, Notifier())
    page.refresh()
    settle()
    page.chooseFolder()
    page.setText("kind", "full")
    assert page._state()["ex"]["ready"], page._state()["ex"]["reason"]
    page.exportNow()
    run = wait_done(page)
    assert run["phase"] == "done" and Path(run["path"]).suffix == ".zip", run


def test_an_opened_file_is_a_resource_the_import_uses_up(qt_app, tmp_path):
    src = make(tmp_path / "a")
    host = Host(src, tmp_path / "out")
    page = ProfileTransferAdapter(host, Notifier())
    page.refresh()
    settle()
    page.chooseFolder()
    page.exportNow()  # a share list
    out = Path(wait_done(page)["path"])
    dst = make(tmp_path / "b")
    host.profile, host.picked = dst, out
    page.open_transfer("import")
    page.openFile()
    for _ in range(100):
        settle()
        if page._preview is not None or page._state()["imp"]["error"]:
            break
    imp = page._state()["imp"]
    assert imp["file"] and not imp["error"]
    assert page._res
    page.cancel()
    assert page._res == "" and page._state()["imp"]["file"] == ""
