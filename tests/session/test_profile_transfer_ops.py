"""The Export / Import profile operations through Session.run / snapshot / answer: no Qt, no window."""

import json
import zipfile
from pathlib import Path

import pytest

from bayle.errors import OperationError
from bayle.services.transfer_resources import TransferResources
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore
from support import er

PROFILE = (
    'profileVersion = "v1"\nsavefile = "ER0000.sl2"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\n\n"
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    "[[packages]]\nid = \"fauna\"\npath = 'mod/fauna'\n"
)


def make(root: Path, volume: int = 5) -> Path:
    files = {
        "mod/flora/flora.ini": f"[Main]\nvolume = {volume}\n",
        "mod/flora/parts/a.dcx": "flora",
        "mod/fauna/fauna.ini": "[Main]\nspeed = 1\n",
        "natives/SeamlessCoop/ersc.dll": "dll",
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data)
    me3 = root / "my.me3"
    me3.write_text(PROFILE)
    return me3


def inline(run, name=None):
    run()


def session(resources=None):
    jobs = JobManager(EventBus(), spawn=inline)
    services = {"transfer_resources": resources} if resources else None
    return Session(jobs, plans=PlanStore(), locations=er, services=services)


def tree(root: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def events(s: Session, job_id: str) -> list:
    sub = s.jobs.bus.subscribe(since=0)
    out = []
    while (e := sub.get(0)) is not None:
        if e.job_id == job_id:
            out.append(e)
    return out


def test_the_listing_reads_without_writing(tmp_path):
    prof = make(tmp_path / "me")
    before = tree(tmp_path)
    got = session().snapshot("profile_transfer", profile=str(prof))
    assert len(got.mods) == 3
    assert all(m.size > 0 for m in got.mods)
    assert tree(tmp_path) == before
    assert session().snapshot("profile_transfer").mods == []


def test_a_full_export_reports_typed_progress_and_a_typed_result(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    keys = [m.key for m in s.snapshot("profile_transfer", profile=str(prof)).mods]
    job = s.run(
        "profile_transfer.export",
        dict(profile=str(prof), kind="full", name="Pack", chosen=keys, folder=str(tmp_path / "out")),
    )
    snap = s.jobs.get(job)
    assert snap is not None and snap.state == "done"
    out = Path(snap.result["path"])
    assert out.suffix == ".zip" and snap.result["size"] == out.stat().st_size
    progress = [e for e in events(s, job) if e.type == "progress"]
    assert progress and progress[-1].data["detail"]["count"] >= 1
    assert progress[-1].data["done"] == progress[-1].data["total"]
    with zipfile.ZipFile(out) as z:
        assert "manifest.json" in z.namelist()


def test_a_share_list_export_writes_one_json(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    job = s.run("profile_transfer.export", dict(profile=str(prof), name="Mine", folder=str(tmp_path / "out")))
    out = Path(s.jobs.get(job).result["path"])
    assert json.loads(out.read_text(encoding="utf-8"))["name"] == "Mine"


def test_cancelling_an_export_stops_it_and_removes_the_partial_zip(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    keys = [m.key for m in s.snapshot("profile_transfer", profile=str(prof)).mods]
    pending = []
    s.jobs._runner._spawn = lambda run, name=None: pending.append(run)  # type: ignore[attr-defined]  # hold the work
    job = s.run(
        "profile_transfer.export",
        dict(profile=str(prof), kind="full", name="Pack", chosen=keys, folder=str(tmp_path / "out")),
    )
    assert s.jobs.cancel(job)
    pending[0]()
    assert s.jobs.get(job).state == "cancelled"
    assert list((tmp_path / "out").iterdir()) == []


def test_an_export_without_mods_fails_with_a_code(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    job = s.run("profile_transfer.export", dict(profile=str(prof), kind="full", name="P", folder=str(tmp_path / "o")))
    snap = s.jobs.get(job)
    assert snap.state == "failed" and snap.error.code == "export_failed"


def test_a_big_export_is_a_plan_that_starts_the_job(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    keys = [m.key for m in s.snapshot("profile_transfer", profile=str(prof)).mods]
    params = dict(
        profile=str(prof), kind="full", name="Pack", chosen=keys, folder=str(tmp_path / "o"), size=3 * 1024**3
    )
    plan = s.run("profile_transfer.confirm_export", params)
    assert isinstance(plan.words, Confirm) and "3.0 GB" in plan.words.changes[0]
    assert s.answer(plan.id, {"ok": False}) is None and not (tmp_path / "o").exists()
    plan = s.run("profile_transfer.confirm_export", params)
    job = s.answer(plan.id, {"ok": True})
    assert s.jobs.get(job).state == "done"


def test_open_preview_and_import_a_full_export_then_the_resource_is_gone(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    s = session()
    keys = [m.key for m in s.snapshot("profile_transfer", profile=str(src)).mods]
    out = s.jobs.get(
        s.run(
            "profile_transfer.export",
            dict(profile=str(src), kind="full", name="Pack", chosen=keys, folder=str(tmp_path / "o")),
        )
    ).result["path"]
    opened = s.run("profile_transfer.open_file", {"path": out})
    assert opened.is_zip and opened.new_profile and "full export" in opened.file
    res = s.service("transfer_resources", TransferResources)
    unpacked = res.get(opened.resource).incoming.unpacked
    assert unpacked.exists()
    before = tree(dst.parent)
    pre = s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name="Imported"))
    assert not pre.refusals and not pre.undecided
    assert tree(dst.parent) == before  # a preview writes nothing to the profile
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name=""))
    assert e.value.code == "name_needed"
    job = s.run("profile_transfer.import", dict(resource=opened.resource))
    snap = s.jobs.get(job)
    assert snap.state == "done" and snap.result == {"name": "imported.me3"}
    assert (dst.parent / "imported.me3").exists()
    assert not unpacked.exists() and res.open_ids() == []  # the backend let go of it


def test_import_without_a_preview_is_refused(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    keys = [m.key for m in s.snapshot("profile_transfer", profile=str(prof)).mods]
    out = s.jobs.get(
        s.run("profile_transfer.export", dict(profile=str(prof), name="Mine", folder=str(tmp_path / "o")))
    ).result["path"]
    opened = s.run("profile_transfer.open_file", {"path": out})
    assert keys
    job = s.run("profile_transfer.import", dict(resource=opened.resource))
    assert s.jobs.get(job).error.code == "no_preview"


def test_a_file_that_is_not_a_profile_is_unreadable(tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"nope")
    with pytest.raises(OperationError) as e:
        session().run("profile_transfer.open_file", {"path": str(bad)})
    assert e.value.code == "unreadable"


def test_a_bundled_profile_is_a_resource_with_a_staging_folder_that_goes_with_it(tmp_path):
    dst = make(tmp_path / "b", 5)
    staging = tmp_path / "staging"
    (staging / "dl").mkdir(parents=True)
    me3 = make(staging / "dl", 7)
    s = session()
    opened = s.run(
        "profile_transfer.open_bundled", dict(unpacked=str(staging / "dl"), profiles=[str(me3)], staging=str(staging))
    )
    assert opened.new_name == "my"
    pre = s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name="Fresh"))
    assert pre.lines
    assert s.run("profile_transfer.discard", dict(resource=opened.resource)).found
    assert not staging.exists()
    assert not s.run("profile_transfer.discard", dict(resource=opened.resource)).found
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name="Fresh"))
    assert e.value.code == "not_found"


def test_an_untouched_resource_is_deleted_after_its_ttl(tmp_path):
    now = [0.0]
    res = TransferResources(clock=lambda: now[0], ttl=100)
    folder = tmp_path / "staging"
    folder.mkdir()
    one = res.add(staging=folder)
    now[0] = 99
    assert res.get(one.id) is one  # touching it starts the wait again
    now[0] = 250
    res.add()  # the next call sweeps
    assert not folder.exists()
    with pytest.raises(OperationError):
        res.get(one.id)
