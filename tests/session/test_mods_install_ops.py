"""The Install mod dialog as a draft the session holds (mods.install_*) through Session.run: no Qt, no window."""

import zipfile
from pathlib import Path

import pytest

from bayle.platform import threads
from bayle.services import mods as mod_service
from bayle.services.errors import OperationError
from bayle.services.mods import profile_entries
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.session.ops.mods_install import drafts
from support import er, mods_profile


def make(**jobs_kw) -> Session:
    return Session(
        JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs_kw), plans=PlanStore(), locations=er
    )


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


@pytest.fixture
def download(tmp_path) -> Path:
    src = tmp_path / "dl" / "grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.partsbnd.dcx").write_bytes(b"g")
    return src


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


def opened(s, profile, source):
    return s.run("mods.install_open", {"profile": str(profile), "source": str(source)})


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


def test_a_download_is_opened_edited_planned_again_and_installed_as_a_logged_job(profile, download):
    s = make()
    got = opened(s, profile, download)
    assert got.pending is False and got.view["title"] == "Install grass" and got.view["canInstall"]
    renamed = s.run("mods.install_edit", {"draft_id": got.draft_id, "field": "name", "text": "grass2"})
    assert renamed.pending and renamed.view["busy"] and renamed.view["canInstall"] is False  # waits for the plan
    assert renamed.view["id"] == "grass2"  # the id follows the name
    replanned = s.run("mods.install_replan", {"draft_id": got.draft_id})
    assert replanned.view["busy"] is False and replanned.view["canInstall"]
    job = s.run("mods.install_finish", {"draft_id": got.draft_id, "name": "grass2"})
    snap = s.jobs.get(job)
    assert (snap.state, snap.title) == ("done", "Installing grass2...")
    assert snap.result == {"name": "grass2", "overhaul": False, "update": False}
    assert "grass2" in [e["name"] for e in profile_entries(profile)]
    assert (
        refused(s, "mods.install_edit", {"draft_id": got.draft_id, "field": "name", "text": "x"}).code
        == "unknown_draft"
    )


def test_a_tick_is_in_memory_and_asks_for_no_new_plan(profile, download):
    s, view = make(), None
    view = opened(s, profile, download)
    ticks = [i["name"] for i in view.view["items"]]
    assert ticks  # the files of the download, ticked as the plan proposes
    got = s.run("mods.install_edit", {"draft_id": view.draft_id, "field": "tick", "key": ticks[0], "on": False})
    assert got.pending is False and next(i for i in got.view["items"] if i["name"] == ticks[0])["on"] is False


def test_what_cannot_be_opened_is_a_refusal_with_a_code(profile, tmp_path):
    s = make()
    assert (
        refused(s, "mods.install_open", {"profile": str(profile), "source": str(tmp_path / "nope.zip")}).code
        == "unreadable"
    )
    empty = tmp_path / "dl" / "empty"
    empty.mkdir(parents=True)
    assert refused(s, "mods.install_open", {"profile": str(profile), "source": str(empty)}).code == "not_installable"
    listed = refused(s, "mods.install_open", {"profile": str(profile), "source": str(profile.parent / "mod" / "flora")})
    assert listed.code == "already_listed" and listed.message == "flora"


def test_an_install_that_is_not_ready_is_refused_before_a_job_starts(profile, download):
    s = make()
    got = opened(s, profile, download)
    s.run("mods.install_edit", {"draft_id": got.draft_id, "field": "name", "text": ""})
    assert refused(s, "mods.install_finish", {"draft_id": got.draft_id}).code == "not_ready"
    assert s.jobs.get("j1") is None
    assert refused(make(external_busy=lambda: True), "mods.install_finish", {"draft_id": "d1"}).code == "busy"


def test_closing_a_draft_drops_the_unpacked_copy_and_import_keeps_it(profile, tmp_path):
    archive = tmp_path / "dl" / "grass.zip"
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("grass/parts/grass.partsbnd.dcx", b"g")
    s = make()
    got = opened(s, profile, archive)
    staging = Path(drafts(s).get(got.draft_id).draft.plan["staging"])
    assert staging.is_dir()
    s.run("mods.install_close", {"draft_id": got.draft_id})
    assert not staging.exists()
    assert refused(s, "mods.install_close", {"draft_id": got.draft_id}).code == "unknown_draft"
    again = opened(s, profile, archive)
    assert refused(s, "mods.install_import", {"draft_id": again.draft_id}).code == "no_profiles"  # ships no profile


def test_the_heavy_reads_are_refused_on_the_ui_thread_but_an_edit_is_not(profile, download):
    s = make()
    got = opened(s, profile, download)
    threads.enable()  # this thread is "the UI thread" from here on
    try:
        assert s.run("mods.install_edit", {"draft_id": got.draft_id, "field": "rebuild", "on": False}).view
        for op in ("mods.install_replan", "mods.install_preview"):
            with pytest.raises(threads.UiThreadIO):
                s.run(op, {"draft_id": got.draft_id})
        with threads.as_worker():
            s.run("mods.install_replan", {"draft_id": got.draft_id})
    finally:
        threads.disable()


def test_an_edit_made_while_a_plan_is_read_drops_that_answer_and_asks_again(profile, download, monkeypatch):
    s = make()
    got = opened(s, profile, download)
    s.run("mods.install_edit", {"draft_id": got.draft_id, "field": "name", "text": "grass2"})
    real = mod_service.replan_mod_install

    def meanwhile(*a, **k):
        out = real(*a, **k)
        s.run(
            "mods.install_edit", {"draft_id": got.draft_id, "field": "name", "text": "grass3"}
        )  # typed during the read
        return out

    monkeypatch.setattr(mod_service, "replan_mod_install", meanwhile)
    state = drafts(s).get(got.draft_id)
    s.run("mods.install_replan", {"draft_id": got.draft_id})
    assert state.planned[0] == "grass" and state.draft.busy  # the answer for grass2 was dropped
    monkeypatch.setattr(mod_service, "replan_mod_install", real)
    s.run("mods.install_replan", {"draft_id": got.draft_id})
    assert state.planned[0] == "grass3" and not state.draft.busy
