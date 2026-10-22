"""The Mods page's operations on a profile's entries through Session.run / answer: no Qt, no window."""

import pytest

from bayle.services.errors import OperationError
from bayle.services.mods import profile_entries
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm
from support import MODS_PROFILE, er, mods_profile


def inline(run, name=None):
    run()


def make(**jobs_kw) -> Session:
    return Session(JobManager(EventBus(), spawn=inline, **jobs_kw), plans=PlanStore(), locations=er)


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


def entry(profile, name):
    return next(e for e in profile_entries(profile) if e["name"] == name)


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


def test_an_entry_goes_off_and_the_last_change_is_taken_back(profile):
    s, ref = make(), {"profile": str(profile)}
    got = s.run("mods.set_enabled", {**ref, "index": entry(profile, "flora")["index"], "enabled": False})
    assert (got.note, got.name) == ("profile: flora off", "flora")
    assert entry(profile, "flora")["enabled"] is False
    s.run("mods.undo_change", ref)
    assert entry(profile, "flora")["enabled"] is True


def test_a_change_waits_for_a_running_job_and_an_entry_that_is_gone_is_said(profile):
    ref = {"profile": str(profile), "index": 0, "enabled": False}
    assert refused(make(external_busy=lambda: True), "mods.set_enabled", ref).code == "busy"
    assert refused(make(), "mods.set_enabled", {**ref, "index": 99}).code == "not_found"
    assert entry(profile, "flora").get("enabled", True) is not False


def test_removing_an_entry_undo_brings_back_runs_at_once_and_its_record_undoes_it_byte_exact(profile):
    s, before = make(), profile.read_bytes()
    a = entry(profile, "a.dll")["index"]
    job = s.run("mods.remove", {"profile": str(profile), "index": a, "name": "a.dll"})
    snap = s.jobs.get(job)
    assert (snap.state, snap.title) == ("done", "Removing a.dll...")
    assert profile.read_bytes() != before and not (profile.parent / "natives").exists()
    undo = snap.result["undo"]
    assert undo["type"] == "remove"
    assert s.run("mods.undo_removal", {"undo": undo}).note == "profile: restored a.dll"
    assert profile.read_bytes() == before and (profile.parent / "natives" / "a.dll").read_bytes() == b"d"


def test_removing_a_folder_another_entry_uses_asks_first_with_the_words_in_the_error(profile):
    mods_profile(profile.parent, MODS_PROFILE + "[[natives]]\npath = 'natives/b.dll'\n")
    (profile.parent / "natives" / "b.dll").write_bytes(b"d")
    s, a = make(), entry(profile, "a.dll")["index"]
    params = {"profile": str(profile), "index": a, "name": "a.dll"}
    asked = refused(s, "mods.remove", params)
    assert asked.code == "needs_confirmation" and asked.details["prompt"]["title"] == "Remove a.dll from the profile"
    assert entry(profile, "a.dll")  # nothing was removed
    job = s.run("mods.remove", {**params, "confirmed": True, "delete_folder": False})
    assert s.jobs.get(job).state == "done" and not [e for e in profile_entries(profile) if e["name"] == "a.dll"]


def test_a_removal_of_an_entry_that_changed_is_refused_as_stale(profile):
    err = refused(make(), "mods.remove", {"profile": str(profile), "index": 0, "name": "cloud"})
    assert err.code == "stale"


def test_a_removal_that_fails_is_a_failed_job_with_its_reason(profile, monkeypatch):
    from bayle.services import profile_mods

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(profile_mods, "remove_entry", boom)
    s = make()
    snap = s.jobs.get(s.run("mods.remove", {"profile": str(profile), "index": 2, "name": "a.dll", "confirmed": True}))
    assert snap.state == "failed" and snap.error is not None and "disk full" in snap.error.message


def test_a_move_the_dependencies_would_undo_is_returned_with_the_entry_that_decides(profile):
    s, cloud = make(), entry(profile, "cloud")["index"]
    got = s.run("mods.move", {"profile": str(profile), "index": cloud, "to": 0})
    assert (got.moved, got.problem, got.decided_by) == (
        False,
        "cloud must load after flora (set in its options)",
        cloud,
    )
    assert [e["name"] for e in profile_entries(profile)][:2] == ["flora", "cloud"]


def test_a_move_that_is_allowed_is_written_and_a_busy_session_refuses(profile):
    s = make()
    mods_profile(profile.parent, MODS_PROFILE + "[[natives]]\npath = 'natives/b.dll'\n")
    (profile.parent / "natives" / "b.dll").write_bytes(b"d")
    b = entry(profile, "b.dll")["index"]
    assert s.run("mods.move", {"profile": str(profile), "index": b, "to": 0}).moved
    assert [e["name"] for e in profile_entries(profile) if e["kind"] == "native"] == ["b.dll", "a.dll"]
    busy = make(external_busy=lambda: True)
    assert refused(busy, "mods.move", {"profile": str(profile), "index": b, "to": 1}).code == "busy"


def test_mod_options_are_read_and_saved_as_a_typed_record(profile):
    s, cloud = make(), entry(profile, "cloud")["index"]
    view = s.run("mods.options", {"profile": str(profile), "index": cloud})
    assert [(d.id, d.optional) for d in view.load_after] == [("flora", False)] and view.others == ["flora"]
    saved = s.run("mods.save_options", {"profile": str(profile), "index": cloud, "id": "cloud2", "load_after": []})
    assert saved.note == "profile: options saved for cloud"
    assert entry(profile, "cloud2")["load_after"] == []


def test_a_wait_that_is_not_a_number_is_refused_with_a_code(profile):
    a = entry(profile, "a.dll")["index"]
    bad = {"profile": str(profile), "index": a, "init_kind": 2, "init_value": "soon"}
    assert refused(make(), "mods.save_options", bad).code == "invalid_wait"
    ok = make().run("mods.save_options", {**bad, "init_value": "250"})
    assert entry(profile, "a.dll")["initializer"] == {"delay": {"ms": 250}} and ok.name == "a.dll"


def test_the_profile_text_is_edited_with_a_parse_gate_and_its_line_ends_kept(profile):
    s = make()
    shown = s.run("mods.text", {"profile": str(profile)})
    assert shown.crlf is False and 'id = "flora"' in shown.text
    assert s.run("mods.check_text", {"text": shown.text}).problem == ""
    assert s.run("mods.check_text", {"text": "profileVersion = "}).problem.startswith("Does not parse as a profile")
    assert refused(s, "mods.save_text", {"profile": str(profile), "text": "profileVersion = "}).code == "invalid_toml"
    s.run("mods.save_text", {"profile": str(profile), "text": shown.text + "# a note\n", "crlf": True})
    assert b"# a note\r\n" in profile.read_bytes()
    assert s.run("mods.text", {"profile": str(profile)}).crlf is True


def test_versions_are_listed_restored_and_a_copy_that_is_not_one_is_refused(profile):
    s, ref = make(), {"profile": str(profile)}
    s.run("mods.set_enabled", {**ref, "index": 0, "enabled": False})
    listed = s.run("mods.versions", ref).versions
    assert listed and listed[0].when[:4].isdigit()
    restored = s.run("mods.restore_version", {**ref, "path": listed[0].path})
    assert entry(profile, "flora").get("enabled", True) is not False and restored.before is not None
    assert refused(s, "mods.restore_version", {**ref, "path": str(profile.parent / "no.me3")}).code == "unknown_version"


def test_mod_folders_no_entry_loads_are_listed_and_added(profile):
    (profile.parent / "mod" / "extra" / "parts").mkdir(parents=True)
    (profile.parent / "mod" / "extra" / "parts" / "x.partsbnd.dcx").write_bytes(b"x")
    s, ref = make(), {"profile": str(profile), "kind": "package"}
    folders = s.run("mods.unlisted", ref).folders
    assert [f["label"] for f in folders] == ["extra"]
    added = s.run("mods.add_existing", {**ref, "paths": [folders[0]["path"]]})
    assert added.names and added.loose_dlls is False
    assert "extra" in [e["name"] for e in profile_entries(profile)]


def test_renaming_a_mod_previews_and_runs_as_a_job(profile):
    s, cloud = make(), entry(profile, "cloud")["index"]
    pre = s.run("mods.rename_preview", {"profile": str(profile), "index": cloud, "name": "cloud2"})
    assert pre.ok and pre.refusals == []
    assert s.run("mods.rename_start", {"profile": str(profile), "index": cloud}).name == "cloud"
    job = s.run("mods.rename", {"profile": str(profile), "index": cloud, "name": "cloud2"})
    assert s.jobs.get(job).state == "done" and (profile.parent / "mod" / "cloud2").is_dir()
    assert refused(s, "mods.rename", {"profile": str(profile), "index": 99, "name": "x"}).code == "not_found"


def test_a_holder_entry_is_removed_through_a_plan(profile):
    mods_profile(profile.parent, MODS_PROFILE + "[[packages]]\nid = \"all\"\npath = 'mod'\n")
    s = make()
    holder = entry(profile, "all")["index"]
    plan = s.run("mods.remove_holder", {"profile": str(profile), "index": holder})
    assert isinstance(plan.words, Confirm) and plan.words.title == "Remove 'all' from the profile"
    assert entry(profile, "all")  # nothing before the answer
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert snap.state == "done" and snap.result["note"] == "profile: removed all (a folder of mods)"
    assert not [e for e in profile_entries(profile) if e["name"] == "all"]
