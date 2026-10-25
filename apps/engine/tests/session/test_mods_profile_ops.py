"""The Mods page's operations on the profile as a whole through the route functions: no Qt, no window. A plan is a check and a
start with the stamp the check gave; a refused write changes nothing."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from bayle.adapters.system.app_paths import data_dir
from bayle.modules.mods import profile_mods
from bayle.modules.mods.service import profile_entries, read_profile_settings
from support import mods_profile, mods_session, refused, tree_state

make = mods_session


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


def job(s, got):
    snap = s.jobs.get(got.job_id)
    assert snap is not None
    return snap


def test_the_me3_settings_are_read_and_written_with_the_online_one_asking_first(profile):
    s, ref = make(), {"profile": str(profile)}
    assert s.run("mods.settings", ref).start_online == 0
    got = s.run("mods.set_setting", {**ref, "key": "disable_arxan", "value": 1})
    assert (got.changed, got.key) == (True, "disable_arxan")
    assert "disable_arxan = true" in profile.read_text(encoding="utf-8")
    assert s.run("mods.settings", ref).disable_arxan == 1
    asked = refused(s, "mods.set_setting", {**ref, "key": "start_online", "value": 1})
    assert (asked.code, asked.details) == ("needs_confirmation", {"reason": "online"})
    assert read_profile_settings(profile).get("start_online") is not True
    assert s.run("mods.set_setting", {**ref, "key": "start_online", "value": 1, "confirmed": True}).changed
    assert s.run("mods.set_setting", {**ref, "key": "disable_arxan", "value": 1}).changed is False  # as it was
    assert refused(s, "mods.set_setting", {**ref, "key": "nope", "value": 1}).code == "unknown_setting"


def test_a_refused_setting_changes_nothing(profile, tmp_path):
    ref, before = {"profile": str(profile)}, profile.read_bytes()
    busy = refused(make(external_busy=lambda: True), "mods.set_setting", {**ref, "key": "mem_patch", "value": 2})
    assert busy.code == "busy" and profile.read_bytes() == before
    ghost = {"profile": str(tmp_path / "ghost.me3"), "key": "mem_patch", "value": 2}
    assert refused(make(), "mods.set_setting", ghost).code == "not_found"


def test_a_rebuild_is_refused_with_a_code_before_any_job_starts(profile):
    ref = {"profile": str(profile)}
    err = refused(make(game_running=lambda: True), "mods.rebuild", ref)
    assert err.code == "rebuild_game_running"
    s = make()
    assert refused(s, "mods.rebuild", ref).code in ("nothing_to_rebuild", "rebuild_blocked")
    assert s.jobs.get("j1") is None  # nothing started


def test_a_rebuild_tool_that_is_not_allowed_yet_asks_with_its_facts_and_runs_once_allowed(profile, monkeypatch):
    tool = SimpleNamespace(
        label="Merge tool", package={"name": "Big Pack"}, describe=lambda: "runs merge.exe", approval_key=lambda: "k1"
    )
    state = {"allowed": False}
    monkeypatch.setattr(profile_mods, "rebuild_refusal", lambda *a, **k: None)
    monkeypatch.setattr(profile_mods, "tool_state", lambda *a, **k: profile_mods.ToolState(tool, "", state["allowed"]))
    monkeypatch.setattr(profile_mods, "allow_tool", lambda t: state.update(allowed=True))
    monkeypatch.setattr(profile_mods, "rebuild_job", lambda p, combine: lambda launch, loc: None)
    s, ref = make(), {"profile": str(profile)}
    asked = refused(s, "mods.rebuild", ref)
    assert (asked.code, asked.details["reason"], asked.details["tool"]["label"]) == (
        "needs_confirmation",
        "allow_tool",
        "Merge tool",
    )
    assert state["allowed"] is False
    snap = job(s, s.run("mods.rebuild", {**ref, "allow": True}))
    assert snap.state == "done" and state["allowed"] is True


def test_allowing_a_tool_is_checked_then_remembered_for_the_version_that_was_shown(profile, monkeypatch):
    s, ref = make(), {"profile": str(profile)}
    assert refused(s, "mods.check_allow_tool", ref).code == "no_tool"
    tool = SimpleNamespace(
        label="Merge tool", package={"name": "Big Pack"}, describe=lambda: "runs merge.exe", approval_key=lambda: "k1"
    )
    allowed = []
    monkeypatch.setattr(profile_mods, "tool_state", lambda *a, **k: profile_mods.ToolState(tool, "", False))
    monkeypatch.setattr(profile_mods, "allow_tool", allowed.append)
    info = s.run("mods.check_allow_tool", ref)
    assert (info.label, info.package, info.what, info.key) == ("Merge tool", "Big Pack", "runs merge.exe", "k1")
    assert refused(s, "mods.allow_tool", {**ref, "expect": "k0"}).code == "stale" and allowed == []
    s.run("mods.allow_tool", {**ref, "expect": "k1"})
    assert allowed == [tool]


def test_trimming_says_when_there_is_nothing_to_trim(profile):
    err = refused(make(), "mods.check_trim_backups", {"profile": str(profile)})
    assert (err.code, err.details) == ("nothing_to_trim", {"keep": 3})


def test_trimming_is_checked_then_moves_the_older_backups_in_a_job(profile, monkeypatch):
    extra = [{"folder": Path("b1"), "size": 2_000_000}]
    monkeypatch.setattr(profile_mods, "tool_backups_to_trim", lambda p: extra)
    monkeypatch.setattr(profile_mods, "trim_tool_backups", lambda p: list(extra))
    s, ref = make(), {"profile": str(profile)}
    plan = s.run("mods.check_trim_backups", ref)
    assert (plan.count, plan.size, plan.keep) == (1, 2_000_000, 3)
    assert refused(s, "mods.trim_backups", {**ref, "expect": 2}).code == "stale"
    snap = job(s, s.run("mods.trim_backups", {**ref, "expect": 1}))
    assert (snap.state, snap.result) == ("done", {"moved": 1})


def test_loose_dlls_get_folders_after_a_check_and_a_start_with_its_stamp(profile):
    s, ref = make(), {"profile": str(profile)}
    plan = s.run("mods.check_dll_folders", ref)
    assert (plan.refusals, plan.moves, plan.stamp is not None) == ((), 1, True)
    assert (profile.parent / "natives" / "a.dll").is_file()  # nothing before the start
    profile.write_bytes(profile.read_bytes() + b"# edited elsewhere\n")
    assert refused(s, "mods.dll_folders", {**ref, "expect": plan.stamp}).code == "stale"
    assert (profile.parent / "natives" / "a.dll").is_file()
    fresh = s.run("mods.check_dll_folders", ref)
    assert job(s, s.run("mods.dll_folders", {**ref, "expect": fresh.stamp})).state == "done"
    assert not (profile.parent / "natives" / "a.dll").exists()
    again = s.run("mods.check_dll_folders", ref)
    assert again.refusals == ("Every DLL is in its own folder.",)
    assert refused(s, "mods.dll_folders", {**ref, "expect": again.stamp}).code == "cannot_move"


def test_the_profile_folder_fixes_are_refused_when_there_is_nothing_to_fix(profile):
    s, ref = make(), {"profile": str(profile)}
    assert refused(s, "mods.rename_folder", ref).code == "folder_refused"
    plan = s.run("mods.check_split_folder", ref)
    assert plan.refusals and not (plan.moves or plan.copies)
    assert refused(s, "mods.split_folder", {**ref, "expect": plan.stamp}).code == "cannot_split"


def test_seamless_coop_is_offered_only_when_it_sits_in_the_game_folder(profile):
    ref = {"profile": str(profile)}
    assert refused(make(), "mods.check_seamless", ref).code == "nothing_to_do"
    assert refused(make(external_busy=lambda: True), "mods.check_seamless", ref).code == "busy"
    assert refused(make(game_running=lambda: True), "mods.seamless", {**ref, "expect": ["move", 1]}).code == "busy"


def test_a_seamless_move_is_checked_then_started_for_what_was_shown(profile, monkeypatch):
    from bayle.modules.coop import service as coop_service

    found = SimpleNamespace(kind="move", folder=Path("g/SeamlessCoop"), files=["a", "b"], launcher=Path("launcher.exe"))
    moved = []
    monkeypatch.setattr(coop_service, "game_folder_seamless", lambda launch: found)
    monkeypatch.setattr(coop_service, "move_seamless_into_profile", lambda *a: moved.append(a))
    s, ref = make(), {"profile": str(profile)}
    plan = s.run("mods.check_seamless", ref)
    assert (plan.kind, plan.files, plan.launcher) == ("move", 2, "launcher.exe")
    assert refused(s, "mods.seamless", {**ref, "expect": ["move", 3]}).code == "stale" and moved == []
    snap = job(s, s.run("mods.seamless", {**ref, "expect": ["move", 2]}))
    assert (snap.state, snap.result, len(moved)) == ("done", {"kind": "move"}, 1)


def test_renaming_the_profile_checks_the_name_and_runs_as_a_job(profile):
    s, ref = make(), {"profile": str(profile)}
    assert s.run("mods.profile_block", ref).reason == ""
    assert s.run("mods.profile_name_check", {**ref, "name": "  "}).code == "empty"
    bad = s.run("mods.profile_name_check", {**ref, "name": "x:y"})
    assert bad.code == "invalid" and bad.reason.endswith("Windows doesn't allow : in a name.")
    err = refused(s, "mods.rename_profile", {**ref, "name": "x:y"})
    assert (err.code, err.details["code"]) == ("invalid_name", "invalid")
    blocked = refused(make(external_busy=lambda: True), "mods.rename_profile", {**ref, "name": "ok"})
    assert (blocked.code, blocked.details) == ("profile_blocked", {"reason": "busy"})
    assert profile.is_file()
    snap = job(s, s.run("mods.rename_profile", {**ref, "name": "Renamed"}))
    assert (snap.state, snap.title) == ("done", "Renaming main...")
    assert Path(snap.result["profile"]).is_file() and not profile.exists()


def test_the_profile_block_names_why_in_codes(profile, tmp_path):
    ref = {"profile": str(profile)}
    assert make(game_running=lambda: True).run("mods.profile_block", ref).reason == "game-running"
    assert make(external_busy=lambda: True).run("mods.profile_block", ref).reason == "busy"
    assert make().run("mods.profile_block", {"profile": str(tmp_path / "x.me3")}).reason == "no-profile"
    managed = {**ref, "kind": "manifest", "source": str(tmp_path / "installation.json")}
    assert make().run("mods.profile_block", managed).reason == "managed"


def test_copying_the_profile_asks_only_when_its_packages_could_be_shared(profile, monkeypatch):
    from bayle.modules.mods import shared_mods_page as library_service

    s, ref = make(), {"profile": str(profile)}
    snap = job(s, s.run("mods.duplicate_profile", ref))
    assert snap.state == "done" and snap.title == "Copying main..."
    assert Path(snap.result["profile"]).is_file() and profile.is_file()
    monkeypatch.setattr(library_service, "separate_copies", lambda *a, **k: ["x"])
    asked = refused(s, "mods.duplicate_profile", ref)
    assert (asked.code, asked.details["reason"]) == ("needs_confirmation", "share")
    assert job(s, s.run("mods.duplicate_profile", {**ref, "share": False})).state == "done"


def test_moving_a_profile_into_bayles_folder_is_checked_and_a_stale_stamp_moves_nothing(profile):
    s, ref = make(), {"profile": str(profile)}
    plan = s.run("mods.check_move_in", ref)
    assert plan.stamp is not None
    profile.write_bytes(profile.read_bytes() + b"# edited elsewhere\n")
    stale = refused(s, "mods.move_in", {**ref, "expect": plan.stamp})
    assert stale.code == "stale" and profile.is_file()
    assert refused(make(external_busy=lambda: True), "mods.check_move_in", ref).code == "profile_blocked"


def test_deleting_the_profile_is_checked_then_a_job_moves_it_to_deleted_profiles(profile):
    s, ref = make(), {"profile": str(profile)}
    plan = s.run("mods.check_delete_profile", ref)
    assert (plan.name, plan.keeps) == ("main", "") and plan.stamp is not None
    assert profile.is_file()  # nothing before the start
    profile.write_bytes(profile.read_bytes() + b"# edited elsewhere\n")
    assert refused(s, "mods.delete_profile", {**ref, "expect": plan.stamp}).code == "stale"
    assert profile.is_file()
    fresh = s.run("mods.check_delete_profile", ref)
    snap = job(s, s.run("mods.delete_profile", {**ref, "expect": fresh.stamp}))
    assert snap.state == "done" and not profile.exists() and Path(snap.result["moved_to"]).is_file()
    assert refused(s, "mods.check_delete_profile", ref).code == "no_profile"


def test_a_profile_an_installer_manages_or_a_busy_session_cannot_be_deleted_here(profile):
    ref = {"profile": str(profile)}
    managed = {**ref, "kind": "manifest", "source": "x/installation.json"}
    assert refused(make(), "mods.check_delete_profile", managed).code == "managed"
    assert refused(make(external_busy=lambda: True), "mods.check_delete_profile", ref).code == "busy"
    stale = {**ref, "expect": None}
    assert refused(make(external_busy=lambda: True), "mods.delete_profile", stale).code == "busy"
    assert profile.is_file()


def test_the_profile_operations_write_only_inside_the_test_folders(profile):
    before = tree_state(data_dir())
    make().run("mods.profile_block", {"profile": str(profile)})
    assert tree_state(data_dir()) == before
    assert len(profile_entries(profile)) == 3
