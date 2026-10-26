"""The Install mod dialog through the route functions on the real ModInstallService (mods.install_*): no Qt, no window. The
engine opens and plans a download and holds it by id; the client sends its choices again with the call that needs
them."""

import zipfile
from pathlib import Path

import pytest

from bayle.adapters.system import threads
from bayle.errors import OperationError
from bayle.modules.mods import profile_mods
from bayle.modules.mods.mod_install import ModInstallService
from bayle.modules.mods.service import profile_entries
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import ServiceCalls, er, mods_profile


def make(**jobs_kw) -> ServiceCalls:
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs_kw)
    return ServiceCalls(jobs, mod_install=ModInstallService(jobs, er))


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


@pytest.fixture
def download(tmp_path) -> Path:
    src = tmp_path / "dl" / "grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.partsbnd.dcx").write_bytes(b"g")
    return src


@pytest.fixture
def archive(tmp_path) -> Path:
    path = tmp_path / "dl" / "grass.zip"
    path.parent.mkdir()
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("grass/parts/grass.partsbnd.dcx", b"g")
    return path


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


def opened(s, profile, source):
    return s.run("mods.install_open", {"profile": str(profile), "source": str(source)})


def finish(got, **choices):
    body = {"name": "grass", "id": "grass", **choices}
    return {"install_id": got.install_id, "choices": body, "expect": list(got.stamp) if got.stamp else None}


def test_the_paths_that_can_be_installed_are_told_from_the_rest(tmp_path, download):
    (tmp_path / "x.zip").write_bytes(b"z")
    (tmp_path / "x.dll").write_bytes(b"d")
    (tmp_path / "notes.txt").write_bytes(b"t")
    got = make().run(
        "mods.install_sources",
        {"paths": [str(download), str(tmp_path / "x.zip"), str(tmp_path / "x.dll"), str(tmp_path / "notes.txt")]},
    )
    assert [Path(x).name for x in got.usable] == ["grass", "x.zip", "x.dll"]
    assert [Path(x).name for x in got.skipped] == ["notes.txt"]


def test_a_download_is_opened_planned_again_and_installed_as_a_job_with_the_clients_choices(profile, download):
    s = make()
    got = opened(s, profile, download)
    assert got.plan["name"] == "grass" and got.plan["option"] == "plain" and got.plan["kind"] == "package"
    assert isinstance(got.plan["dest"], str) and got.stamp
    renamed = s.run("mods.install_replan", {"install_id": got.install_id, "name": "grass2", "id": "grass2"})
    assert renamed.plan["name"] == "grass2" and renamed.plan["id"] == "grass2"
    job = s.run("mods.install_finish", finish(got, name="grass2", id="grass2")).job_id
    snap = s.jobs.get(job)
    assert (snap.state, snap.title) == ("done", "Installing grass2...")
    assert snap.result == {"name": "grass2", "overhaul": False, "update": False}
    assert "grass2" in [e["name"] for e in profile_entries(profile)]
    assert refused(s, "mods.install_close", {"install_id": got.install_id}).code == "unknown_install"


def test_the_install_plans_again_by_itself_when_the_name_changed(profile, download):
    s = make()
    got = opened(s, profile, download)
    s.run("mods.install_finish", finish(got, name="other", id="other"))
    assert "other" in [e["name"] for e in profile_entries(profile)]


def test_what_cannot_be_opened_is_a_refusal_with_a_code(profile, tmp_path):
    s = make()
    missing = {"profile": str(profile), "source": str(tmp_path / "nope.zip")}
    assert refused(s, "mods.install_open", missing).code == "not_found"
    assert refused(s, "mods.install_open", {"profile": str(tmp_path / "no.me3"), "source": str(tmp_path)}).code == (
        "not_found"
    )
    bad = tmp_path / "dl" / "bad.zip"
    bad.parent.mkdir()
    bad.write_bytes(b"not a zip")
    assert refused(s, "mods.install_open", {"profile": str(profile), "source": str(bad)}).code == "unreadable"
    empty = tmp_path / "dl" / "empty"
    empty.mkdir(parents=True)
    assert refused(s, "mods.install_open", {"profile": str(profile), "source": str(empty)}).code == "not_installable"
    listed = refused(s, "mods.install_open", {"profile": str(profile), "source": str(profile.parent / "mod" / "flora")})
    assert listed.code == "already_listed" and listed.message == "flora"


def test_an_install_that_is_not_ready_is_refused_before_a_job_starts(profile, download):
    s = make()
    got = opened(s, profile, download)
    blank = refused(s, "mods.install_finish", finish(got, name=" "))
    assert blank.code == "not_ready" and blank.details["reason"] == "name_blank"
    unticked = [it["name"] for it in got.plan["contents"]]
    nothing = refused(s, "mods.install_finish", finish(got, exclude=unticked))
    assert nothing.code == "not_ready" and nothing.details["reason"] == "nothing_loaded"
    assert s.jobs.get("j1") is None
    busy = make(external_busy=lambda: True)
    again = opened(busy, profile, download)
    assert refused(busy, "mods.install_finish", finish(again)).code == "busy"
    assert "grass" not in [e["name"] for e in profile_entries(profile)]


def test_a_profile_that_changed_since_the_open_is_stale_and_the_install_stays_open(profile, download):
    s = make()
    got = opened(s, profile, download)
    profile.write_text(profile.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert refused(s, "mods.install_finish", finish(got)).code == "stale"
    assert s.run("mods.install_replan", {"install_id": got.install_id, "name": "grass"}).plan["name"] == "grass"


def test_a_failed_install_leaves_the_profile_and_drops_the_unpacked_copy(profile, archive, monkeypatch):
    s = make()
    got = opened(s, profile, archive)
    staging = Path(got.plan["staging"])
    assert staging.is_dir()
    before = profile.read_bytes()

    def boom(*a, **k):
        raise OperationError("failed", "disk full")

    monkeypatch.setattr(profile_mods, "install_and_record", boom)
    snap = s.jobs.get(s.run("mods.install_finish", finish(got)).job_id)
    assert snap.state == "failed" and snap.error is not None and snap.error.message == "disk full"
    assert profile.read_bytes() == before and not staging.exists()
    assert refused(s, "mods.install_finish", finish(got)).code == "unknown_install"


def test_closing_an_install_drops_the_unpacked_copy_and_import_needs_profiles(profile, archive):
    s = make()
    got = opened(s, profile, archive)
    staging = Path(got.plan["staging"])
    assert staging.is_dir()
    s.run("mods.install_close", {"install_id": got.install_id})
    assert not staging.exists()
    assert refused(s, "mods.install_close", {"install_id": got.install_id}).code == "unknown_install"
    again = opened(s, profile, archive)
    assert refused(s, "mods.install_import", {"install_id": again.install_id}).code == "no_profiles"


def test_the_heavy_reads_are_refused_on_the_ui_thread(profile, download):
    s = make()
    got = opened(s, profile, download)
    threads.enable()  # this thread is "the UI thread" from here on
    try:
        with pytest.raises(threads.UiThreadIO):
            s.run("mods.install_replan", {"install_id": got.install_id, "name": "grass"})
        with pytest.raises(threads.UiThreadIO):
            opened(s, profile, download)
        with threads.as_worker():
            s.run("mods.install_replan", {"install_id": got.install_id, "name": "grass"})
    finally:
        threads.disable()
