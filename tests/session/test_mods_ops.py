"""The Mods page's snapshot and read operations through Session.snapshot / run: no Qt, no window."""

import pytest

from bayle.config.settings import data_dir
from bayle.services import mods as mod_service
from bayle.services import shared_mods as library_service
from bayle.services.errors import OperationError
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from support import er, mods_profile, tree_state


def inline(run, name=None):
    run()


def make(**jobs_kw) -> Session:
    return Session(JobManager(EventBus(), spawn=inline, **jobs_kw), plans=PlanStore(), locations=er)


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


def test_the_snapshot_shows_the_rows_the_load_order_and_the_header(profile):
    view = make().snapshot("mods", profile=str(profile))
    assert view.has_profile and view.profile == str(profile) and view.state.title == "main"
    assert [[r.name for r in g.rows] for g in view.state.groups] == [["flora", "cloud"], ["a.dll"]]
    assert view.state.counts == "2 packages  ·  1 native"
    assert [e["name"] for e in view.entries] == ["flora", "cloud", "a.dll"]
    assert view.load_order.clash_total == 0 and view.rebuild_undo is None
    assert view.overhaul.visible is False and view.overhaul_info is None


def test_reading_the_page_writes_nothing(profile):
    s = make()
    before = tree_state(profile.parent, data_dir())
    s.snapshot("mods", profile=str(profile))
    s.snapshot("mods", profile=str(profile), kind="me3", source="", no_profiles=True)
    s.run("mods.library_hint", {"profile": str(profile)})
    s.run("mods.drag", {"profile": str(profile), "index": 1})
    assert tree_state(profile.parent, data_dir()) == before


def test_no_profile_and_an_unreadable_one_say_why():
    s = make()
    assert s.snapshot("mods").state.empty == "Pick a profile first."
    assert "no profile yet" in s.snapshot("mods", no_profiles=True).state.empty
    assert not s.snapshot("mods", profile="C:/nowhere/x.me3").has_profile


def test_an_interrupted_change_put_right_is_remembered_as_a_notice(profile, monkeypatch):
    calls = []

    def recover(prof, timeout=30.0):
        calls.append(str(prof))
        return ["the removal of flora was undone"]

    monkeypatch.setattr(mod_service, "recover_interrupted", recover)
    s = make()
    assert s.run("mods.recover", {"profile": str(profile)}).lines == ["the removal of flora was undone"]
    keys = [n.key for n in s.snapshot("mods", profile=str(profile)).state.notices]
    assert "recovered" in keys
    other = mods_profile(profile.parent.parent / "q")
    assert "recovered" not in [n.key for n in s.snapshot("mods", profile=str(other)).state.notices]  # its own lines
    assert len(calls) == 1


def test_nothing_is_looked_at_while_a_job_holds_the_folder(profile, monkeypatch):
    monkeypatch.setattr(mod_service, "recover_interrupted", lambda *a, **k: pytest.fail("looked"))
    assert make(external_busy=lambda: True).run("mods.recover", {"profile": str(profile)}).lines == []


def test_a_closed_notice_stays_closed_for_the_profile(profile, monkeypatch):
    monkeypatch.setattr(mod_service, "recover_interrupted", lambda *a, **k: ["x"])
    s = make()
    s.run("mods.recover", {"profile": str(profile)})
    assert "recovered" in [n.key for n in s.snapshot("mods", profile=str(profile)).state.notices]
    s.run("mods.close_notice", {"profile": str(profile), "key": "recovered"})
    assert "recovered" not in [n.key for n in s.snapshot("mods", profile=str(profile)).state.notices]


def test_the_library_hint_waits_for_enough_wasted_space(profile, monkeypatch):
    from bayle.mods import shared_mods

    s = make()
    monkeypatch.setattr(library_service, "duplicates", lambda loc: (1, 10))
    assert s.run("mods.library_hint", {"profile": str(profile)}).notice is None
    monkeypatch.setattr(library_service, "duplicates", lambda loc: (3, shared_mods.HINT_BYTES + 1))
    hint = s.run("mods.library_hint", {"profile": str(profile)})
    assert (hint.mods, hint.notice.key) == (3, "library-hint")
    s.run("mods.close_notice", {"profile": str(profile), "key": "library-hint"})
    assert s.run("mods.library_hint", {"profile": str(profile)}).notice is None


def test_the_drag_table_ships_a_reason_for_every_drop_spot(profile):
    table = make().run("mods.drag", {"profile": str(profile), "index": 1})
    assert table.kind == "package"
    assert table.reasons == {0: "cloud must load after flora (set in its options)", 1: ""}
    with pytest.raises(OperationError) as e:
        make().run("mods.drag", {"profile": str(profile), "index": 99})
    assert e.value.code == "not_found"
