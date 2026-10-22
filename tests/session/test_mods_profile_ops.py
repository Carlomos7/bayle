"""The Mods page's operations on the profile as a whole through Session.run / answer: no Qt, no window."""

from pathlib import Path

import pytest

from bayle.config.settings import data_dir
from bayle.services import profile_mods
from bayle.services.errors import OperationError
from bayle.services.mods import profile_entries, read_profile_settings
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm, Refusal
from support import er, mods_profile, tree_state


def inline(run, name=None):
    run()


def make(**jobs_kw) -> Session:
    return Session(JobManager(EventBus(), spawn=inline, **jobs_kw), plans=PlanStore(), locations=er)


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


def test_the_me3_settings_are_read_and_written_with_the_online_one_asking_first(profile):
    s, ref = make(), {"profile": str(profile)}
    assert s.run("mods.settings", ref).start_online == 0
    got = s.run("mods.set_setting", {**ref, "key": "disable_arxan", "value": 1})
    assert (got.changed, got.note) == (True, "profile: disable_arxan = True")
    assert "disable_arxan = true" in profile.read_text(encoding="utf-8")
    assert s.run("mods.settings", ref).disable_arxan == 1
    asked = refused(s, "mods.set_setting", {**ref, "key": "start_online", "value": 1})
    assert asked.code == "needs_confirmation" and asked.details["prompt"]["title"] == "Turn online matchmaking on"
    assert read_profile_settings(profile).get("start_online") is not True
    assert s.run("mods.set_setting", {**ref, "key": "start_online", "value": 1, "confirmed": True}).changed
    assert s.run("mods.set_setting", {**ref, "key": "disable_arxan", "value": 1}).changed is False  # as it was
    assert refused(s, "mods.set_setting", {**ref, "key": "nope", "value": 1}).code == "unknown_setting"
    assert (
        refused(make(external_busy=lambda: True), "mods.set_setting", {**ref, "key": "mem_patch", "value": 2}).code
        == "busy"
    )


def test_a_rebuild_is_refused_with_a_code_before_any_job_starts(profile):
    ref = {"profile": str(profile)}
    err = refused(make(game_running=lambda: True), "mods.rebuild", ref)
    assert err.code == "rebuild_game_running" and "Close the game first" in err.message
    s = make()
    assert refused(s, "mods.rebuild", ref).code in ("nothing_to_rebuild", "rebuild_blocked")
    assert s.jobs.get("j1") is None  # nothing started


def test_trimming_the_rebuild_backups_says_when_there_is_nothing_to_trim(profile):
    got = make().run("mods.trim_backups", {"profile": str(profile)})
    assert isinstance(got, Refusal) and got.info and "3 or fewer backups" in got.body


def test_trimming_asks_then_moves_the_older_backups_in_a_job(profile, monkeypatch):
    extra = [{"folder": Path("b1"), "size": 2_000_000}]
    monkeypatch.setattr(profile_mods, "tool_backups_to_trim", lambda p: extra)
    monkeypatch.setattr(profile_mods, "trim_tool_backups", lambda p: list(extra))
    s = make()
    plan = s.run("mods.trim_backups", {"profile": str(profile)})
    assert isinstance(plan.words, Confirm) and plan.words.title == "Move 1 older rebuild backup to the Recycle Bin"
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert (snap.state, snap.result) == ("done", {"moved": 1})


def test_the_allow_tool_plan_refuses_without_a_tool(profile):
    assert isinstance(make().run("mods.allow_tool", {"profile": str(profile)}), Refusal)


def test_loose_dlls_get_folders_after_a_confirmation(profile):
    s = make()
    plan = s.run("mods.dll_folders", {"profile": str(profile)})
    assert isinstance(plan.words, Confirm) and plan.words.title == "Put DLL mods in their own folders?"
    assert (profile.parent / "natives" / "a.dll").is_file()  # nothing before the answer
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert snap.state == "done" and not (profile.parent / "natives" / "a.dll").exists()
    again = s.run("mods.dll_folders", {"profile": str(profile)})
    assert isinstance(again, Refusal) and again.body == "Every DLL is in its own folder."


def test_a_plan_made_before_the_profile_changed_is_refused(profile):
    from bayle.session import PlanError

    s = make()
    plan = s.run("mods.dll_folders", {"profile": str(profile)})
    profile.write_bytes(profile.read_bytes() + b"# edited elsewhere\n")
    with pytest.raises(PlanError) as e:
        s.answer(plan.id, {"ok": True})
    assert e.value.code == "plan_stale"


def test_the_profile_folder_fixes_are_refused_when_there_is_nothing_to_fix(profile):
    s, ref = make(), {"profile": str(profile)}
    assert refused(s, "mods.rename_folder", ref).code == "folder_refused"
    assert isinstance(s.run("mods.split_folder", ref), Refusal)


def test_seamless_coop_is_offered_only_when_it_sits_in_the_game_folder(profile):
    got = make().run("mods.seamless", {"profile": str(profile)})
    assert isinstance(got, Refusal) and got.title == "Nothing to do"
    busy = make(external_busy=lambda: True).run("mods.seamless", {"profile": str(profile)})
    assert isinstance(busy, Refusal) and busy.title == "Not now"


def test_renaming_the_profile_checks_the_name_and_runs_as_a_job(profile):
    s, ref = make(), {"profile": str(profile)}
    assert s.run("mods.profile_block", ref).reason == ""
    assert s.run("mods.profile_name_check", {**ref, "name": "  "}).problem == "Type a new name."
    assert s.run("mods.profile_name_check", {**ref, "name": "x:y"}).problem.endswith(
        "Windows doesn't allow : in a name."
    )
    assert refused(s, "mods.rename_profile", {**ref, "name": "x:y"}).code == "invalid_name"
    assert (
        refused(make(external_busy=lambda: True), "mods.rename_profile", {**ref, "name": "ok"}).code
        == "profile_blocked"
    )
    snap = s.jobs.get(s.run("mods.rename_profile", {**ref, "name": "Renamed"}))
    assert (snap.state, snap.title) == ("done", "Renaming main...")
    assert Path(snap.result["profile"]).is_file() and not profile.exists()


def test_copying_the_profile_asks_only_when_its_packages_could_be_shared(profile):
    s, ref = make(), {"profile": str(profile)}
    snap = s.jobs.get(s.run("mods.duplicate_profile", ref))
    assert snap.state == "done" and snap.title == "Copying main..."
    assert Path(snap.result["profile"]).is_file() and profile.is_file()


def test_moving_a_profile_into_bayles_folder_asks_and_a_declined_answer_moves_nothing(profile):
    s = make()
    plan = s.run("mods.move_in", {"profile": str(profile)})
    assert isinstance(plan.words, Confirm) and plan.words.title == "Move main into Bayle's folder?"
    assert s.answer(plan.id, {"ok": False}) is None and profile.is_file()
    busy = make(external_busy=lambda: True).run("mods.move_in", {"profile": str(profile)})
    assert isinstance(busy, Refusal) and busy.body == "Wait for the current job to finish."


def test_deleting_the_profile_is_a_plan_whose_job_moves_it_to_deleted_profiles(profile):
    s = make()
    plan = s.run("mods.delete_profile", {"profile": str(profile)})
    assert isinstance(plan.words, Confirm) and plan.words.title == "Delete profile main?"
    assert profile.is_file()  # nothing before the answer
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert snap.state == "done" and not profile.exists() and Path(snap.result["moved_to"]).is_file()
    gone = s.run("mods.delete_profile", {"profile": str(profile)})
    assert isinstance(gone, Refusal) and gone.title == "No profile"


def test_a_profile_an_installer_manages_cannot_be_deleted_here(profile):
    managed = make().run(
        "mods.delete_profile", {"profile": str(profile), "kind": "manifest", "source": "x/installation.json"}
    )
    assert isinstance(managed, Refusal) and managed.title == "Not this one"


def test_the_profile_operations_write_only_inside_the_test_folders(profile):
    before = tree_state(data_dir())
    make().run("mods.profile_block", {"profile": str(profile)})
    assert tree_state(data_dir()) == before
    assert len(profile_entries(profile)) == 3
