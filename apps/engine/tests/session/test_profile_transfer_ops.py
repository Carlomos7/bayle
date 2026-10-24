"""The Export / Import profile operations through Session.run / snapshot: no Qt, no window. They are handed straight to
the session's ProfileTransferService, so these also cover the service: job results, stale, not_found, boundaries."""

import json
import zipfile
from pathlib import Path

import pytest

from bayle.api.routers import profile_transfer as profile_transfer_router
from bayle.errors import OperationError
from bayle.services.profile_transfer import ProfileTransferService
from bayle.services.transfer_resources import TransferResources
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import Direct, er

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
    service = ProfileTransferService(jobs, er, resources)
    return Direct(profile_transfer_router, "profile_transfer", service, jobs)


def job_of(s: Direct, name: str, params: dict):
    """Start a job operation and return its (finished) snapshot."""
    return s.jobs.get(s.run(name, params).job_id)


def tree(root: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def events(s: Direct, job_id: str) -> list:
    sub = s.jobs.bus.subscribe(since=0)
    out = []
    while (e := sub.get(0)) is not None:
        if e.job_id == job_id:
            out.append(e)
    return out


def keys_of(s: Direct, prof: Path) -> list[str]:
    return [m.key for m in s.snapshot("profile_transfer", profile=str(prof)).mods]


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
    job = s.run(
        "profile_transfer.export",
        dict(profile=str(prof), kind="full", name="Pack", chosen=keys_of(s, prof), folder=str(tmp_path / "out")),
    ).job_id
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
    snap = job_of(
        session(), "profile_transfer.export", dict(profile=str(prof), name="Mine", folder=str(tmp_path / "out"))
    )
    assert json.loads(Path(snap.result["path"]).read_text(encoding="utf-8"))["name"] == "Mine"


def test_cancelling_an_export_stops_it_and_removes_the_partial_zip(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    keys = keys_of(s, prof)
    pending = []
    s.jobs._runner._spawn = lambda run, name=None: pending.append(run)  # type: ignore[attr-defined]  # hold the work
    job = s.run(
        "profile_transfer.export",
        dict(profile=str(prof), kind="full", name="Pack", chosen=keys, folder=str(tmp_path / "out")),
    ).job_id
    assert s.jobs.cancel(job)
    pending[0]()
    assert s.jobs.get(job).state == "cancelled"
    assert list((tmp_path / "out").iterdir()) == []


def test_an_export_without_mods_fails_with_a_code_and_details(tmp_path):
    prof = make(tmp_path / "me")
    params = dict(profile=str(prof), kind="full", name="P", folder=str(tmp_path / "o"))
    snap = job_of(session(), "profile_transfer.export", params)
    assert snap.state == "failed" and snap.error.code == "export_failed"
    assert snap.error.details["name"] == "P" and snap.error.details["profile"] == str(prof)


def test_a_big_export_is_a_check_and_a_start_that_is_stale_when_the_mods_changed(tmp_path, monkeypatch):
    prof = make(tmp_path / "me")
    s = session()
    keys = keys_of(s, prof)
    monkeypatch.setattr("bayle.services.profile_transfer.LARGE_EXPORT", 1)
    got = s.run("profile_transfer.check_export", dict(profile=str(prof), kind="full", chosen=keys))
    assert got.big and got.size > 0
    assert not s.run("profile_transfer.check_export", dict(profile=str(prof), kind="list", chosen=keys)).big
    params = dict(profile=str(prof), kind="full", name="Pack", chosen=keys, folder=str(tmp_path / "o"))
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.export", {**params, "expect": got.size + 1})
    assert e.value.code == "stale" and not (tmp_path / "o").exists()
    assert job_of(s, "profile_transfer.export", {**params, "expect": got.size}).state == "done"


def test_an_export_names_only_what_the_listing_has(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    base = dict(profile=str(prof), name="P", folder=str(tmp_path / "o"))
    for change, code in [
        ({"chosen": ["package:nope"]}, "not_found"),
        ({"profile": str(tmp_path / "me" / "gone.me3")}, "not_found"),
        ({"profile": str(tmp_path / "me" / "mod" / "flora" / "flora.ini")}, "not_found"),
        ({"kind": "zip"}, "invalid_params"),
    ]:
        with pytest.raises(OperationError) as e:
            s.run("profile_transfer.export", {**base, **change})
        assert e.value.code == code, change
    assert not (tmp_path / "o").exists()


def test_open_preview_and_import_a_full_export_then_the_resource_is_gone(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    s = session()
    out = job_of(
        s,
        "profile_transfer.export",
        dict(profile=str(src), kind="full", name="Pack", chosen=keys_of(s, src), folder=str(tmp_path / "o")),
    ).result["path"]
    opened = s.run("profile_transfer.open_file", {"path": out})
    assert opened.kind == "zip" and opened.new_profile and opened.name == "Pack"
    res = s.service._resources
    unpacked = res.get(opened.resource).incoming.unpacked
    assert unpacked.exists()
    before = tree(dst.parent)
    pre = s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name="Imported"))
    assert not pre.refusals and not pre.undecided and pre.cards and pre.serial == 1
    assert tree(dst.parent) == before  # a preview writes nothing to the profile
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name=""))
    assert e.value.code == "name_needed"
    snap = job_of(s, "profile_transfer.import", dict(resource=opened.resource, expect=pre.serial))
    assert snap.state == "done" and snap.result == {"name": "imported.me3"}
    assert (dst.parent / "imported.me3").exists()
    assert not unpacked.exists() and res.open_ids() == []  # the backend let go of it


def test_import_without_a_preview_is_refused(tmp_path):
    prof = make(tmp_path / "me")
    s = session()
    out = job_of(s, "profile_transfer.export", dict(profile=str(prof), name="Mine", folder=str(tmp_path / "o")))
    opened = s.run("profile_transfer.open_file", {"path": out.result["path"]})
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.import", dict(resource=opened.resource))
    assert e.value.code == "no_preview"


def test_an_import_is_stale_when_a_newer_preview_was_made(tmp_path):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    s = session()
    out = job_of(s, "profile_transfer.export", dict(profile=str(src), name="Mine", folder=str(tmp_path / "o")))
    opened = s.run("profile_transfer.open_file", {"path": out.result["path"]})
    first = s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst)))
    s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst)))
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.import", dict(resource=opened.resource, expect=first.serial))
    assert e.value.code == "stale"
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.import", dict(resource="t99"))
    assert e.value.code == "not_found"


def test_a_failed_import_carries_a_code_and_details_and_keeps_the_resource(tmp_path, monkeypatch):
    src, dst = make(tmp_path / "a", 7), make(tmp_path / "b", 5)
    s = session()
    out = job_of(s, "profile_transfer.export", dict(profile=str(src), name="Mine", folder=str(tmp_path / "o")))
    opened = s.run("profile_transfer.open_file", {"path": out.result["path"]})
    s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst)))

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr("bayle.services.profile_transfer.apply", boom)
    snap = job_of(s, "profile_transfer.import", dict(resource=opened.resource))
    assert snap.state == "failed" and snap.error.code == "import_failed"
    assert snap.error.details == {"resource": opened.resource} and "disk full" in snap.error.message
    assert s.run("profile_transfer.discard", dict(resource=opened.resource)).found


def test_a_file_that_is_not_a_profile_is_unreadable(tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"nope")
    with pytest.raises(OperationError) as e:
        session().run("profile_transfer.open_file", {"path": str(bad)})
    assert e.value.code == "unreadable" and e.value.details["path"] == str(bad)


def test_a_bundled_profile_is_a_resource_with_a_staging_folder_that_goes_with_it(tmp_path):
    dst = make(tmp_path / "b", 5)
    staging = tmp_path / "x" / "staging"
    (staging / "dl").mkdir(parents=True)
    me3 = make(staging / "dl", 7)
    s = session()
    opened = s.run(
        "profile_transfer.open_bundled", dict(unpacked=str(staging / "dl"), profiles=[str(me3)], staging=str(staging))
    )
    assert opened.kind == "bundled" and opened.new_name == "my" and opened.names == [str(me3)]
    pre = s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name="Fresh"))
    assert pre.bundled and pre.lines
    assert s.run("profile_transfer.discard", dict(resource=opened.resource)).found
    assert not staging.exists()
    assert not s.run("profile_transfer.discard", dict(resource=opened.resource)).found
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(dst), new_name="Fresh"))
    assert e.value.code == "not_found"
    with pytest.raises(OperationError) as e:
        s.run("profile_transfer.preview", dict(resource=opened.resource, profile=str(tmp_path / "nope.me3")))
    assert e.value.code == "not_found"


def test_a_bundled_download_must_hold_its_profiles_and_sit_in_its_staging_folder(tmp_path):
    staging = tmp_path / "x" / "staging"
    (staging / "dl").mkdir(parents=True)
    me3 = make(staging / "dl")
    elsewhere = make(tmp_path / "other")
    s = session()
    for params in [
        dict(unpacked=str(staging / "dl"), profiles=[str(elsewhere)]),  # a profile outside the download
        dict(unpacked=str(staging / "dl"), profiles=[str(staging / "dl" / "mod" / "flora" / "a.dcx")]),  # not a .me3
        dict(unpacked=str(staging / "gone"), profiles=[str(me3)]),
        dict(unpacked=str(staging / "dl"), profiles=[str(me3)], staging=str(tmp_path / "other")),  # not its staging
    ]:
        with pytest.raises(OperationError) as e:
            s.run("profile_transfer.open_bundled", params)
        assert e.value.code == "invalid_params", params
    assert staging.exists() and (tmp_path / "other").exists()  # nothing was taken over, so nothing was deleted


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
