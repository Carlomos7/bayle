"""The Export / Import page's adapter over the engine's Profile transfer interface (no window, work run inline): an
export follows its job to a finished run, a big one is asked about once, an opened file is a resource the import uses
up, a bundled download imports its profile, a refusal is told in the presenter's words. Fixtures live in tmp_path."""

from pathlib import Path

from bayle.platform.threads import as_worker
from bayle.services.profile_transfer import ProfileTransferService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager

from bayle_qt.notifications import Notifier
from bayle_qt.pages.profile_transfer.adapter import ProfileTransferAdapter
from support import er

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n[[packages]]\nid = "flora"\npath = \'mod/flora\'\n'
)


class Features:
    def __init__(self, service):
        self.profile_transfer = service


class Host:
    busy = False
    game_running = False
    locations = er()

    def __init__(self, profile: Path, picked: Path | None = None, hold: bool = False):
        self.profile, self.picked, self.changed = profile, picked, []
        self.pending: list = []  # held job bodies (hold=True), so a test can cancel before the work runs
        spawn = (lambda run, name=None: self.pending.append(run)) if hold else (lambda run, name=None: run())
        jobs = JobManager(EventBus(), spawn=spawn)
        self.features = Features(ProfileTransferService(jobs, er))
        self.job_manager = jobs
        self.followers: dict[str, object] = {}

    def run_in_background(self, work, on_result):
        with as_worker():  # the page's reads are disk work: a real host runs them off the UI thread
            got = work()
        on_result(got)

    def follow_job(self, job_id, done):
        snap = self.job_manager.get(job_id)
        if snap.state == "running":
            self.followers[job_id] = done
        else:
            done(snap)

    def release(self):
        """Run the held job bodies, then tell the followers."""
        with as_worker():
            while self.pending:
                self.pending.pop(0)()
        for job_id, done in list(self.followers.items()):
            done(self.job_manager.get(job_id))
        self.followers.clear()

    def pick_folder(self, title):
        return self.picked

    def pick_file(self, title, filters):
        return self.picked

    def open_path(self, path):
        pass

    def profile_changed(self, note):
        self.changed.append(note)


class Told(Notifier):
    """A Notifier that records the toasts and answers a confirm with `yes` (None: left unanswered)."""

    def __init__(self, yes=True):
        super().__init__()
        self.toasts, self.asked, self.yes = [], [], yes

    def toast(self, text, error=False):
        self.toasts.append((text, error))

    def confirm(self, words, on_answer, destructive=False):
        self.asked.append(words)
        if self.yes is not None:
            on_answer(self.yes)
        return 0


def make(root: Path) -> Path:
    (root / "mod/flora").mkdir(parents=True)
    (root / "mod/flora/a.dcx").write_text("x")
    me3 = root / "my.me3"
    me3.write_text(PROFILE)
    return me3


def exported(tmp_path, kind="list"):
    """A page showing profile a with an output folder chosen and the export done: (host, page, the file written)."""
    host = Host(make(tmp_path / "a"), tmp_path / "out")
    page = ProfileTransferAdapter(host, Told())
    page.refresh()
    page.chooseFolder()
    page.setText("kind", kind)
    page.exportNow()
    return host, page


def test_an_export_runs_as_a_job_the_page_follows_and_shows_done(qt_app, tmp_path):
    host, page = exported(tmp_path, "full")
    run = page._state()["ex"]["run"]
    assert run["phase"] == "done" and Path(run["path"]).suffix == ".zip", run
    assert Path(run["path"]).parent == tmp_path / "out" and not page._working


def test_a_big_export_is_asked_once_and_a_no_starts_nothing(qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr("bayle.services.profile_transfer.LARGE_EXPORT", 1)
    host = Host(make(tmp_path / "a"), tmp_path / "out")
    page = ProfileTransferAdapter(host, Told(yes=False))
    page.refresh()
    page.chooseFolder()
    page.setText("kind", "full")
    page.exportNow()
    assert len(page.notifier.asked) == 1 and "Export a big file?" in page.notifier.asked[0].title
    assert page._state()["ex"]["run"]["phase"] == "idle" and not (tmp_path / "out").exists()
    page.notifier.yes = True
    page.exportNow()
    assert page._state()["ex"]["run"]["phase"] == "done"


def test_an_export_the_mods_changed_under_is_refused_in_words(qt_app, tmp_path):
    host = Host(make(tmp_path / "a"), tmp_path / "out")
    page = ProfileTransferAdapter(host, Told())
    page.refresh()
    page.chooseFolder()
    page.setText("kind", "full")
    page._working = False
    page._start_export(expect=999)  # the size the player was asked about is not what the mods hold now
    run = page._state()["ex"]["run"]
    assert run["phase"] == "error" and "changed since you were asked" in run["text"]
    assert not (tmp_path / "out").exists()


def test_cancelling_an_export_ends_the_run_as_cancelled_and_writes_nothing(qt_app, tmp_path):
    host = Host(make(tmp_path / "a"), tmp_path / "out", hold=True)
    page = ProfileTransferAdapter(host, Told())
    page.refresh()
    page.chooseFolder()
    page.setText("kind", "full")
    page.exportNow()
    assert page._state()["ex"]["run"]["phase"] == "running"
    page.cancelExport()
    host.release()
    run = page._state()["ex"]["run"]
    assert run["phase"] == "cancelled" and list((tmp_path / "out").iterdir()) == []


def test_an_opened_file_is_a_resource_the_import_uses_up(qt_app, tmp_path):
    host, page = exported(tmp_path, "full")
    out = Path(page._state()["ex"]["run"]["path"])
    dst = make(tmp_path / "b")
    host.profile, host.picked = dst, out
    page.open_transfer("import")
    page.openFile()
    assert "(full export)" in page._state()["imp"]["file"] and page._res
    assert "already a profile" in page._state()["imp"]["error"]  # the zip's own name is taken in the new place
    page.setNewName("copy")
    page.renamed()
    assert not page._state()["imp"]["error"] and page._preview is not None and page._ticked
    res = host.features.profile_transfer._resources
    page.importNow()
    assert page.notifier.toasts[-1][1] is False and "Imported into" in page.notifier.toasts[-1][0]
    assert host.changed and res.open_ids() == [] and page._res == "" and (dst.parent / "copy.me3").exists()


def test_leaving_an_opened_file_lets_its_resource_go(qt_app, tmp_path):
    host, page = exported(tmp_path)
    host.profile, host.picked = make(tmp_path / "b"), Path(page._state()["ex"]["run"]["path"])
    page.open_transfer("import")
    page.openFile()
    res = host.features.profile_transfer._resources
    assert len(res.open_ids()) == 1
    page.cancel()
    assert page._res == "" and page._state()["imp"]["file"] == "" and res.open_ids() == []


def test_a_file_that_is_not_a_profile_is_told_not_opened(qt_app, tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"nope")
    host = Host(make(tmp_path / "b"), bad)
    page = ProfileTransferAdapter(host, Told())
    page.open_transfer("import")
    page.openFile()
    assert page._state()["imp"]["error"].startswith("Can't use that file.") and not page._res


def test_a_bundled_download_previews_and_imports_its_profile(qt_app, tmp_path):
    dst = make(tmp_path / "b")
    staging = tmp_path / "x" / "staging"
    (staging / "dl").mkdir(parents=True)
    me3 = make(staging / "dl")
    me3 = me3.rename(me3.with_name("dl.me3"))  # another name than the profile it is imported beside
    host = Host(dst)
    page = ProfileTransferAdapter(host, Told())
    page.open_profile_import(staging / "dl", [str(me3)], staging)
    bun = page._state()["bun"]
    assert bun["names"] == [str(me3)] and bun["lines"] and bun["canImport"], bun
    page.importBundled()
    assert page.notifier.toasts[-1][1] is False and "Imported into" in page.notifier.toasts[-1][0]
    assert (dst.parent / "dl.me3").exists() and not staging.exists()
