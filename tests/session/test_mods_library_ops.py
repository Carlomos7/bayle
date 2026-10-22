"""The Library operations of the Mods page (share, separate, use in other profiles, list, remove unused) through
Session.run / answer, over a real Library in temporary folders: no Qt, no window."""

import shutil
from pathlib import Path

import pytest

from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.mods import shared_mods
from bayle.platform import trash
from bayle.services.errors import OperationError
from bayle.services.mods import profile_entries
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm, Refusal

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
    session = Session(
        JobManager(EventBus(), spawn=lambda run, name=None: run()), plans=PlanStore(), locations=lambda: loc
    )
    return session, loc, a, b


def index_of(profile: Path, name: str) -> int:
    return next(e["index"] for e in profile_entries(profile) if e["name"] == name)


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


def test_sharing_asks_then_shares_in_a_job_and_the_page_shows_it(world):
    s, loc, a, _b = world
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    plan = s.run("mods.share", grass)
    assert isinstance(plan.words, Confirm) and plan.words.title == "Share grass"
    assert shared_mods.shared_count(loc, a, grass["index"]) == 0  # nothing before the answer
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert (snap.state, snap.title) == ("done", "Sharing grass...")
    assert shared_mods.shared_count(loc, a, grass["index"]) == 1
    rows = {r.name: r for r in s.snapshot("mods", profile=str(a)).state.groups[0].rows}
    assert rows["grass"].shared == 1 and rows["grass"].tags[0].text == "Shared · 1 profile"


def test_another_profile_with_the_same_files_is_offered_and_ticking_replaces_its_copy(world):
    s, loc, a, b = world
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    s.answer(s.run("mods.share", grass).id, {"ok": True})
    offer = s.run("mods.library_use_choices", grass)
    assert offer.prompt["kind"] == "pick" and offer.prompt["rows"] == ["b (has its own copy; ticking replaces it)"]
    assert offer.prompt["title"] == "Use grass in other profiles"
    assert refused(s, "mods.library_use", {**grass, "targets": []}).code == "nothing_chosen"
    snap = s.jobs.get(s.run("mods.library_use", {**grass, "targets": [0]}))
    assert (snap.state, snap.title) == ("done", "Linking grass...")
    assert shared_mods.shared_count(loc, b, index_of(b, "grass")) == 2


def test_a_separate_package_is_not_shared_and_a_shared_one_can_get_its_own_copy(world):
    s, loc, a, b = world
    sky = {"profile": str(a), "index": index_of(a, "sky")}
    got = s.run("mods.separate", sky)
    assert isinstance(got, Refusal) and got.body == "This mod is not shared."
    assert refused(s, "mods.library_use_choices", sky).code == "not_shared"
    grass = {"profile": str(a), "index": index_of(a, "grass")}
    s.answer(s.run("mods.share", grass).id, {"ok": True})
    s.run("mods.library_use", {**grass, "targets": [0]})
    plan = s.run("mods.separate", grass)
    assert isinstance(plan.words, Confirm) and plan.words.title == "Use a separate copy of grass"
    assert s.jobs.get(s.answer(plan.id, {"ok": True})).state == "done"
    assert (a.parent / "packages" / "grass" / "parts" / "grass.dcx").read_bytes() == b"same"
    assert shared_mods.shared_count(loc, b, index_of(b, "grass")) == 1


def test_the_library_lists_versions_and_unused_ones_are_removed_after_a_confirm(world, tmp_path):
    s, loc, a, b = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    shared_mods.share(b, [index_of(b, "grass")], loc=loc)
    new = tmp_path / "dl" / "grass"
    (new / "parts").mkdir(parents=True)
    (new / "parts" / "grass.dcx").write_bytes(b"v2")
    shared_mods.update(a, index_of(a, "grass"), new, everywhere=True, loc=loc, label="v2")
    rows = s.run("mods.library", {"profile": str(a)}).rows
    assert [r["name"] for r in rows] == ["grass"] and [v["unused"] for v in rows[0]["versions"]] == [True, False]
    plan = s.run("mods.remove_unused", {"profile": str(a)})
    assert plan.words.title == "Remove unused versions" and "1 version" in plan.words.changes[0]
    assert s.jobs.get(s.answer(plan.id, {"ok": True})).state == "done"
    assert [len(r["versions"]) for r in s.run("mods.library", {"profile": str(a)}).rows] == [1]
    nothing = s.run("mods.remove_unused", {"profile": str(a)})
    assert isinstance(nothing, Refusal) and nothing.info and nothing.body == "Every shared version is in use."


def test_the_library_job_gives_its_reason_when_the_library_refuses(world, monkeypatch):
    from bayle.services import shared_mods as library_service

    s, _loc, a, _b = world

    def refuse(*args, **kw):
        raise library_service.Error("the Library is read-only here")

    monkeypatch.setattr(library_service, "share", refuse)
    plan = s.run("mods.share", {"profile": str(a), "index": index_of(a, "grass")})
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert snap.state == "failed" and snap.error is not None and "read-only" in snap.error.message
