"""The Library operations of the Mods page (share, separate, use in other profiles, list, remove unused) through
Session.run on the real ModLibraryService, over a real Library in temporary folders: no Qt, no window."""

import shutil
from pathlib import Path

import pytest

from bayle.errors import OperationError
from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.mods import shared_mods
from bayle.platform import trash
from bayle.services.mods import profile_entries
from bayle.services.shared_mods import ModLibraryService
from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore

HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


def make_profile(root: Path, name: str, mods: dict[str, bytes]) -> Path:
    entries = ""
    for mod, data in mods.items():
        (root / name / "packages" / mod / "parts").mkdir(parents=True)
        (root / name / "packages" / mod / "parts" / f"{mod}.dcx").write_bytes(data)
        entries += f"\n[[packages]]\nid = '{mod}'\npath = 'packages/{mod}'\n"
    profile = root / name / f"{name}.me3"
    profile.write_bytes((HEAD + entries).encode())
    return profile


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "profiles"
    root = home / "b-eldenring"
    a = make_profile(root, "a", {"grass": b"same", "sky": b"only a"})
    b = make_profile(root, "b", {"grass": b"same"})
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    monkeypatch.setattr(trash, "exists", lambda r: False)
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
    session = Session(
        jobs, plans=PlanStore(), locations=lambda: loc, services={"mod_library": ModLibraryService(jobs, lambda: loc)}
    )
    return session, loc, a, b


def index_of(profile: Path, name: str) -> int:
    return next(e["index"] for e in profile_entries(profile) if e["name"] == name)


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


def share(s, ref):
    plan = s.run("mods.check_share", ref)
    return s.jobs.get(s.run("mods.share", {**ref, "expect": list(plan.stamp)}).job_id)


def test_sharing_is_checked_then_started_with_the_stamp_and_the_page_shows_it(world):
    s, loc, a, _b = world
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    plan = s.run("mods.check_share", grass)
    assert plan.name == "grass" and plan.stamp
    assert shared_mods.shared_count(loc, a, grass["index"]) == 0  # nothing before the start
    snap = s.jobs.get(s.run("mods.share", {**grass, "expect": list(plan.stamp)}).job_id)
    assert (snap.state, snap.title) == ("done", "Sharing grass...")
    assert shared_mods.shared_count(loc, a, grass["index"]) == 1
    rows = {r.name: r for r in s.snapshot("mods", profile=str(a)).state.groups[0].rows}
    assert rows["grass"].shared == 1 and rows["grass"].tags[0].text == "Shared · 1 profile"


def test_a_profile_that_changed_since_the_check_is_stale_and_nothing_is_shared(world):
    s, loc, a, _b = world
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    plan = s.run("mods.check_share", grass)
    a.write_bytes(a.read_bytes() + b"\n# edited\n")
    assert refused(s, "mods.share", {**grass, "expect": list(plan.stamp)}).code == "stale"
    assert refused(s, "mods.share", {"profile": str(a), "index": 99, "expect": None}).code == "not_found"
    assert shared_mods.shared_count(loc, a, grass["index"]) == 0


def test_another_profile_with_the_same_files_is_offered_and_ticking_replaces_its_copy(world):
    s, loc, a, b = world
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    assert share(s, grass).state == "done"
    offer = s.run("mods.library_use_choices", grass)
    assert offer.name == "grass" and [(p.name, p.has_copy, p.uses) for p in offer.profiles] == [("b", True, False)]
    assert refused(s, "mods.library_use", {**grass, "targets": []}).code == "nothing_chosen"
    outside = refused(s, "mods.library_use", {**grass, "targets": [str(a)]})  # not one the Library lists
    assert outside.code == "not_found"
    snap = s.jobs.get(s.run("mods.library_use", {**grass, "targets": [offer.profiles[0].profile]}).job_id)
    assert (snap.state, snap.title) == ("done", "Linking grass...")
    assert shared_mods.shared_count(loc, b, index_of(b, "grass")) == 2


def test_a_separate_package_is_not_shared_and_a_shared_one_can_get_its_own_copy(world):
    s, loc, a, b = world
    sky = {"profile": str(a), "index": index_of(a, "sky")}
    assert refused(s, "mods.check_separate", sky).code == "not_shared"
    assert refused(s, "mods.library_use_choices", sky).code == "not_shared"
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    share(s, grass)
    offer = s.run("mods.library_use_choices", grass)
    s.run("mods.library_use", {**grass, "targets": [offer.profiles[0].profile]})
    plan = s.run("mods.check_separate", grass)
    assert plan.name == "grass" and plan.size > 0
    snap = s.jobs.get(s.run("mods.separate", {**grass, "expect": list(plan.stamp)}).job_id)
    assert (snap.state, snap.title) == ("done", "Copying grass...")
    assert (a.parent / "packages" / "grass" / "parts" / "grass.dcx").read_bytes() == b"same"
    assert shared_mods.shared_count(loc, b, index_of(b, "grass")) == 1


def test_the_library_lists_versions_and_unused_ones_are_removed_after_a_check(world, tmp_path):
    s, loc, a, b = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    shared_mods.share(b, [index_of(b, "grass")], loc=loc)
    new = tmp_path / "dl" / "grass"
    (new / "parts").mkdir(parents=True)
    (new / "parts" / "grass.dcx").write_bytes(b"v2")
    shared_mods.update(a, index_of(a, "grass"), new, everywhere=True, loc=loc, label="v2")
    mods = s.run("mods.library", {"profile": str(a)}).mods
    assert [m.name for m in mods] == ["grass"] and [v.unused for v in mods[0].versions] == [True, False]
    plan = s.run("mods.check_remove_unused", {})
    assert len(plan.versions) == 1 and plan.size == plan.versions[0].size
    assert refused(s, "mods.remove_unused", {"expect": []}).code == "stale"
    assert s.jobs.get(s.run("mods.remove_unused", {"expect": plan.token}).job_id).state == "done"
    assert [len(m.versions) for m in s.run("mods.library", {"profile": str(a)}).mods] == [1]
    assert refused(s, "mods.check_remove_unused", {}).code == "nothing_unused"


def test_the_library_job_gives_its_reason_when_the_library_refuses(world, monkeypatch):
    from bayle.services import shared_mods as library_service

    s, _loc, a, _b = world

    def refuse(*args, **kw):
        raise library_service.Error("the Library is read-only here")

    monkeypatch.setattr(library_service, "share", refuse)
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    snap = share(s, grass)
    assert snap.state == "failed" and snap.error is not None and snap.error.code == "library_refused"
    assert "read-only" in snap.error.message
