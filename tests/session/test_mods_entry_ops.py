"""The Mods page's operations on a profile's entries through the route functions: no Qt, no window. A refused write changes
nothing; a job's id is read back from the session's JobManager."""

import pytest

from bayle.services import profile_mods
from bayle.services.mods import profile_entries
from support import MODS_PROFILE, mods_profile, mods_session, refused

make = mods_session


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


def entry(profile, name):
    return next(e for e in profile_entries(profile) if e["name"] == name)


def job(s, got):
    snap = s.jobs.get(got.job_id)
    assert snap is not None
    return snap


def test_an_entry_goes_off_and_the_last_change_is_taken_back(profile):
    s, ref = make(), {"profile": str(profile)}
    got = s.run("mods.set_enabled", {**ref, "index": entry(profile, "flora")["index"], "enabled": False})
    assert got.name == "flora" and entry(profile, "flora")["enabled"] is False
    assert s.run("mods.undo_change", ref).restored is True
    assert entry(profile, "flora")["enabled"] is True


def test_a_refused_write_changes_nothing(profile):
    ref = {"profile": str(profile), "index": 0, "enabled": False}
    before = profile.read_bytes()
    assert refused(make(external_busy=lambda: True), "mods.set_enabled", ref).code == "busy"
    assert refused(make(), "mods.set_enabled", {**ref, "index": 99}).code == "not_found"
    assert refused(make(), "mods.set_enabled", {**ref, "expect": "cloud"}).code == "stale"
    assert refused(make(), "mods.set_enabled", {**ref, "profile": str(profile.parent / "no.me3")}).code == "not_found"
    assert profile.read_bytes() == before
    gone = {"profile": str(profile), "index": 2, "name": "a.dll", "confirmed": True}
    assert refused(make(game_running=lambda: True), "mods.remove", gone).code == "busy"  # the job's own guard
    assert profile.read_bytes() == before and (profile.parent / "natives" / "a.dll").is_file()


def test_removing_an_entry_undo_brings_back_runs_at_once_and_its_record_undoes_it_byte_exact(profile):
    s, before = make(), profile.read_bytes()
    a = entry(profile, "a.dll")["index"]
    snap = job(s, s.run("mods.remove", {"profile": str(profile), "index": a, "name": "a.dll"}))
    assert (snap.state, snap.title) == ("done", "Removing a.dll...")
    assert profile.read_bytes() != before and not (profile.parent / "natives").exists()
    undo = snap.result["undo"]
    assert snap.result["name"] == "a.dll" and undo["type"] == "remove"
    assert s.run("mods.undo_removal", {"undo": undo}).name == "a.dll"
    assert profile.read_bytes() == before and (profile.parent / "natives" / "a.dll").read_bytes() == b"d"


def test_removing_a_folder_another_entry_uses_asks_first_with_the_facts_in_the_error(profile):
    mods_profile(profile.parent, MODS_PROFILE + "[[natives]]\npath = 'natives/b.dll'\n")
    (profile.parent / "natives" / "b.dll").write_bytes(b"d")
    s, a = make(), entry(profile, "a.dll")["index"]
    params = {"profile": str(profile), "index": a, "name": "a.dll"}
    asked = refused(s, "mods.remove", params)
    assert asked.code == "needs_confirmation" and asked.details["reason"] == "removal"
    assert asked.details["users"] == ["b.dll"] and asked.details["can_recycle"] is False
    assert entry(profile, "a.dll")  # nothing was removed
    snap = job(s, s.run("mods.remove", {**params, "confirmed": True, "delete_folder": False}))
    assert snap.state == "done" and not [e for e in profile_entries(profile) if e["name"] == "a.dll"]


def test_a_removal_of_an_entry_that_changed_is_refused_as_stale(profile):
    err = refused(make(), "mods.remove", {"profile": str(profile), "index": 0, "name": "cloud"})
    assert err.code == "stale" and entry(profile, "flora")


def test_a_removal_that_fails_is_a_failed_job_with_a_code_and_its_reason(profile, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(profile_mods, "remove_entry", boom)
    s = make()
    snap = job(s, s.run("mods.remove", {"profile": str(profile), "index": 2, "name": "a.dll", "confirmed": True}))
    assert snap.state == "failed" and snap.error is not None
    assert (snap.error.code, snap.error.details) == ("remove_failed", {"name": "a.dll"})
    assert "disk full" in snap.error.message


def test_an_undo_record_that_is_not_a_removal_of_a_profile_here_is_not_found(profile, tmp_path):
    s = make()
    assert refused(s, "mods.undo_removal", {"undo": {"type": "rename", "profile": str(profile)}}).code == "not_found"
    ghost = {"type": "remove", "profile": str(tmp_path / "ghost.me3"), "name": "x"}
    assert refused(s, "mods.undo_removal", {"undo": ghost}).code == "not_found"
    assert refused(s, "mods.undo_removal", {"undo": {**ghost, "profile": str(profile)}}).code == "undo_failed"


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
    before = profile.read_bytes()
    busy = make(external_busy=lambda: True)
    assert refused(busy, "mods.move", {"profile": str(profile), "index": b, "to": 1}).code == "busy"
    assert refused(make(), "mods.move", {"profile": str(profile), "index": b, "to": 1, "expect": "x"}).code == "stale"
    assert profile.read_bytes() == before


def test_fixing_the_order_waits_for_a_running_job_and_has_nothing_to_report_when_it_is_right(profile):
    ref = {"profile": str(profile)}
    assert refused(make(external_busy=lambda: True), "mods.fix_order", ref).code == "busy"
    before = profile.read_bytes()
    make().run("mods.fix_order", ref)
    assert profile.read_bytes() == before


def test_mod_options_are_read_and_saved_as_a_typed_record(profile):
    s, cloud = make(), entry(profile, "cloud")["index"]
    view = s.run("mods.options", {"profile": str(profile), "index": cloud})
    assert [(d.id, d.optional) for d in view.load_after] == [("flora", False)] and view.others == ("flora",)
    assert view.overlay is False  # an Elden Ring package: the overlay applies and is not set
    saved = s.run("mods.save_options", {"profile": str(profile), "index": cloud, "id": "cloud2", "load_after": []})
    assert saved.name == "cloud"
    assert entry(profile, "cloud2")["load_after"] == []


def test_a_wait_that_is_not_a_number_is_refused_with_a_code(profile):
    a = entry(profile, "a.dll")["index"]
    bad = {"profile": str(profile), "index": a, "init_kind": 2, "init_value": "soon"}
    before = profile.read_bytes()
    assert refused(make(), "mods.save_options", bad).code == "invalid_wait" and profile.read_bytes() == before
    ok = make().run("mods.save_options", {**bad, "init_value": "250"})
    assert entry(profile, "a.dll")["initializer"] == {"delay": {"ms": 250}} and ok.name == "a.dll"


def test_the_profile_text_is_edited_with_a_parse_gate_and_its_line_ends_kept(profile):
    s = make()
    shown = s.run("mods.text", {"profile": str(profile)})
    assert shown.crlf is False and 'id = "flora"' in shown.text
    assert s.run("mods.check_text", {"text": shown.text}).problem == ""
    assert s.run("mods.check_text", {"text": "profileVersion = "}).problem
    before = profile.read_bytes()
    bad = refused(s, "mods.save_text", {"profile": str(profile), "text": "profileVersion = "})
    assert bad.code == "invalid_toml" and bad.details["why"] and profile.read_bytes() == before
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
    assert refused(s, "mods.restore_version", {**ref, "path": str(profile.parent / "no.me3")}).code == "not_found"


def test_mod_folders_no_entry_loads_are_listed_and_only_those_are_added(profile, tmp_path):
    (profile.parent / "mod" / "extra" / "parts").mkdir(parents=True)
    (profile.parent / "mod" / "extra" / "parts" / "x.partsbnd.dcx").write_bytes(b"x")
    s, ref = make(), {"profile": str(profile), "kind": "package"}
    folders = s.run("mods.unlisted", ref).folders
    assert [f.label for f in folders] == ["extra"]
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    assert refused(s, "mods.add_existing", {**ref, "paths": [str(outside)]}).code == "not_found"
    assert refused(s, "mods.unlisted", {**ref, "kind": "other"}).code == "invalid_params"
    added = s.run("mods.add_existing", {**ref, "paths": [folders[0].path]})
    assert added.names and added.loose_dlls is False
    assert "extra" in [e["name"] for e in profile_entries(profile)]


def test_renaming_a_mod_previews_and_runs_as_a_job(profile):
    s, cloud = make(), entry(profile, "cloud")["index"]
    pre = s.run("mods.rename_preview", {"profile": str(profile), "index": cloud, "name": "cloud2"})
    assert pre.ok and pre.refusals == ()
    assert s.run("mods.rename_start", {"profile": str(profile), "index": cloud}).name == "cloud"
    snap = job(s, s.run("mods.rename", {"profile": str(profile), "index": cloud, "name": "cloud2"}))
    assert snap.state == "done" and snap.result == {"name": "cloud", "to": "cloud2"}
    assert (profile.parent / "mod" / "cloud2").is_dir()
    assert refused(s, "mods.rename", {"profile": str(profile), "index": 99, "name": "x"}).code == "not_found"
    assert refused(s, "mods.rename_start", {"profile": str(profile), "index": 99}).code == "not_found"


def test_a_rename_the_mod_layer_refuses_is_a_failed_job_with_a_code(profile):
    s = make()
    snap = job(s, s.run("mods.rename", {"profile": str(profile), "index": 1, "name": "flora"}))  # taken
    assert snap.state == "failed" and snap.error.code == "rename_failed"
    assert (profile.parent / "mod" / "cloud").is_dir()


def test_a_holder_entry_is_checked_then_removed_with_the_stamp_it_was_checked_at(profile):
    mods_profile(profile.parent, MODS_PROFILE + "[[packages]]\nid = \"all\"\npath = 'mod'\n")
    s = make()
    holder = entry(profile, "all")["index"]
    ref = {"profile": str(profile), "index": holder}
    plan = s.run("mods.check_remove_holder", ref)
    assert plan.name == "all" and plan.needs == () and plan.stamp is not None
    profile.write_bytes(profile.read_bytes() + b"# edited elsewhere\n")
    assert refused(s, "mods.remove_holder", {**ref, "expect": plan.stamp}).code == "stale"
    assert entry(profile, "all")  # nothing was removed
    fresh = s.run("mods.check_remove_holder", ref)
    snap = job(s, s.run("mods.remove_holder", {**ref, "expect": fresh.stamp}))
    assert snap.state == "done" and snap.result == {"name": "all"}
    assert not [e for e in profile_entries(profile) if e["name"] == "all"]
