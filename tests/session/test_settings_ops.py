"""The Settings operations through Session.run / snapshot / answer: no Qt, no window."""

import pytest

from bayle.config.settings import data_dir
from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.mods.layout import Cancelled as LayoutCancelled
from bayle.mods.layout import LayoutError
from bayle.services import layout as layout_service
from bayle.services import play as play_service
from bayle.services.errors import OperationError
from bayle.services.settings import load_settings
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Refusal
from support import er


def inline(run, name=None):
    run()


def make(locations=er, **jobs_kw):
    return Session(JobManager(EventBus(), spawn=inline, **jobs_kw), plans=PlanStore(), locations=locations)


def _tree():
    root = data_dir()
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def test_reading_the_page_writes_nothing():
    s = make()
    before = _tree()
    state = s.snapshot("settings")
    s.run("settings.layout_check", {"pattern": "x-{game}"})
    assert _tree() == before
    assert state.game == "eldenring" and state.keep_from == 5 and state.layout["pattern"]
    keys = {r.key for r in state.locations}
    assert keys == {"me3_path", "game_exe", "me3_profile_dir", "saves_dir"}
    assert {"logo", "theme", "backups_keep", "play_repair_after"} <= {x.key for x in state.specs}
    assert [c.key for c in state.choices["logo"]] == ["auto", "crimson", "ice", "gold"]


def test_the_snapshot_without_a_game_still_answers():
    state = make(locations=None).snapshot("settings")
    assert state.game == "eldenring" and all(r.placeholder for r in state.locations)


def test_a_choice_a_switch_and_a_number_are_saved_and_say_what_follows():
    s = make()
    got = s.run("settings.set", {"key": "logo", "value": "ice"})
    assert (got.value, got.follow, load_settings().logo) == ("ice", "settings", "ice")
    assert s.run("settings.set", {"key": "theme", "value": "light"}).follow == "appearance"
    assert s.run("settings.set", {"key": "launcher_channel", "value": "beta"}).follow == "updates"
    assert "next start" in s.run("settings.set", {"key": "log_level", "value": "verbose"}).said
    assert s.run("settings.set", {"key": "play_boot_boost", "value": False}).stored_as == "play_boot_boost"
    assert load_settings().play_boot_boost is False
    assert s.run("settings.set", {"key": "backups_keep", "value": 9000}).value == 200
    assert load_settings().backups_keep == 200
    assert s.run("settings.set", {"key": "backups_keep", "value": 1}).value == 5


def test_bad_values_are_refused_with_codes_and_nothing_is_saved():
    s = make()
    before = _tree()
    for params, code in [
        ({"key": "logo", "value": "purple"}, "invalid_choice"),
        ({"key": "logo", "value": True}, "invalid_value"),
        ({"key": "play_boot_boost", "value": "yes"}, "invalid_value"),
        ({"key": "backups_keep", "value": True}, "invalid_value"),
        ({"key": "nope", "value": 1}, "unknown_setting"),
        ({"key": "me3_path", "value": "Z:/does/not/exist.exe"}, "path_problem"),
        ({"key": "saves_dir", "value": "Z:/does/not/exist"}, "path_problem"),
    ]:
        with pytest.raises(OperationError) as e:
            s.run("settings.set", params)
        assert e.value.code == code, params
    assert _tree() == before


def test_a_location_is_stored_per_game_or_globally(tmp_path):
    exe = tmp_path / "game.exe"
    exe.write_text("x")
    me3 = tmp_path / "me3.exe"
    me3.write_text("x")
    s = make(locations=lambda: Locations(catalog.NIGHTREIGN))
    assert "game.exe" in s.run("settings.set", {"key": "game_exe", "value": f" {exe} "}).said
    s.run("settings.set", {"key": "me3_path", "value": str(me3)})
    st = load_settings()
    assert st.games["nightreign"]["game_exe"] == str(exe) and st.game_exe == ""  # not Elden Ring's
    assert st.me3_path == str(me3)
    assert s.snapshot("settings").locations[1].value == str(exe)
    s.run("settings.set", {"key": "game_exe", "value": ""})  # blank = detect again
    assert load_settings().games["nightreign"]["game_exe"] == ""


def test_the_repair_switch_has_a_key_per_game():
    make().run("settings.set", {"key": "play_repair_after", "value": True})
    assert getattr(load_settings(), play_service.repair_key(catalog.ELDEN_RING)) is True
    got = make(locations=lambda: Locations(catalog.NIGHTREIGN)).run(
        "settings.set", {"key": "play_repair_after", "value": False}
    )
    assert got.stored_as == "play_repair_after"


def test_folders(tmp_path):
    s = make()
    assert s.run("settings.folder", {"kind": "settings"}).path == str(data_dir())
    backups = s.run("settings.folder", {"kind": "backups"}).path
    assert backups and backups.endswith("saves")  # asking made it
    with pytest.raises(OperationError) as e:
        s.run("settings.folder", {"kind": "attic"})
    assert e.value.code == "unknown_folder"


def test_the_folder_names_check():
    s = make()
    ok = s.run("settings.layout_check", {"pattern": "b-{game}", "packages": "p", "natives": "n", "shared": "s"})
    assert ok.errors == {} and ok.preview == "b-eldenring"
    bad = s.run("settings.layout_check", {"pattern": "plain", "packages": "a/b"})
    assert set(bad.errors) == {"pattern", "packages"} and bad.preview == ""


def test_renaming_offers_a_confirm_and_runs_as_a_job(monkeypatch):
    ran = []
    monkeypatch.setattr(layout_service, "rename_layout", lambda loc, **names: ran.append(names) or {})
    s = make()
    plan = s.run("settings.rename_layout", {"pattern": "x-{game}"})
    assert plan.words.title == "Rename folders?" and "x-{game}" in plan.words.changes[0]
    assert ran == []  # nothing before the answer
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert snap.state == "done" and ran == [{"pattern": "x-{game}"}]


def test_renaming_checks_the_names_first():
    s = make()
    with pytest.raises(OperationError) as e:
        s.run("settings.rename_layout", {"pattern": "plain"})
    assert e.value.code == "invalid_names" and "pattern" in e.value.details["errors"]
    with pytest.raises(OperationError) as e:
        s.run("settings.rename_layout", {})
    assert e.value.code == "nothing_to_change"


def test_a_refused_layout_change_is_a_failed_job_with_a_code(monkeypatch):
    def refuse(loc, **names):
        raise LayoutError("The game is open.")

    monkeypatch.setattr(layout_service, "_fn", lambda name: refuse)  # under the code translation
    s = make()
    snap = s.jobs.get(s.answer(s.run("settings.rename_layout", {"pattern": "x-{game}"}).id, {"ok": True}))
    assert snap.state == "failed" and snap.error.code == "layout_refused" and "game is open" in snap.error.message


def test_a_declined_plan_runs_nothing(monkeypatch):
    monkeypatch.setattr(layout_service, "rename_layout", lambda *a, **k: pytest.fail("ran"))
    s = make()
    assert s.answer(s.run("settings.rename_layout", {"pattern": "x-{game}"}).id, {"ok": False}) is None


def test_a_busy_session_or_a_running_game_refuses_the_plans():
    for kw in ({"external_busy": lambda: True}, {"game_running": lambda: True}):
        got = make(**kw).run("settings.rename_layout", {"pattern": "x-{game}"})
        assert isinstance(got, Refusal), kw


def test_moving_the_profiles_folder_confirms_with_warnings_and_can_be_cancelled(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(layout_service, "profiles_facts", lambda loc: (3, 2048))

    def relocate(loc, new, progress=None, cancel=lambda: False):
        seen["new"] = new
        s.jobs.cancel("j1")  # the player presses Cancel while it moves
        seen["cancelled"] = cancel()
        raise LayoutCancelled("stopped")

    monkeypatch.setattr(layout_service, "_fn", lambda name: relocate)
    s = make()
    plan = s.run("settings.relocate", {"folder": str(tmp_path / "OneDrive" / "Bayle")})
    assert plan.words.title.startswith("Move your profiles") and any("synced" in c for c in plan.words.changes)
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert seen["cancelled"] is True and snap.state == "cancelled"
    with pytest.raises(OperationError) as e:
        s.run("settings.relocate", {"folder": " "})
    assert e.value.code == "invalid_params"


def test_moving_every_profile_in(monkeypatch, tmp_path):
    a = tmp_path / "a.me3"
    s = make()
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [])
    nothing = s.run("settings.move_all")
    assert isinstance(nothing, Refusal) and "outside" in nothing.body
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [a])
    monkeypatch.setattr(layout_service, "move_all", lambda loc, found: len(found))
    plan = s.run("settings.move_all")
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert (snap.state, snap.result) == ("done", {"count": 1})


def test_clearing_leftovers_is_a_job_that_a_running_game_does_not_stop(monkeypatch):
    ran = []
    monkeypatch.setattr(play_service, "job_clear", lambda launch, loc: ran.append(loc.game.key))
    s = make(game_running=lambda: True)
    assert s.jobs.get(s.run("settings.clear_leftovers")).state == "done" and ran == ["eldenring"]
    busy = make(external_busy=lambda: True)
    assert busy.jobs.get(busy.run("settings.clear_leftovers")).error.code == "busy"
