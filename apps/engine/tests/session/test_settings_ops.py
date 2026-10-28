"""The Settings interface (services.settings) without Qt or HTTP: its reads, one setting, the layout changes as checks
and jobs on the shared job manager, and the clean-up. The HTTP ops over it: tests/api/test_settings_routes.py."""

import dataclasses

import pytest

from bayle.adapters.system import logging as run_logging
from bayle.adapters.system.app_paths import data_dir
from bayle.errors import OperationError
from bayle.modules.games import catalog
from bayle.modules.games.locate import Locations
from bayle.modules.launch import play as play_service
from bayle.modules.mods.layout import Cancelled as LayoutCancelled
from bayle.modules.mods.layout import LayoutError
from bayle.modules.settings import locations as layout_service
from bayle.modules.settings.service import SettingsService, load_settings
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import er, tree_state


def inline(run, name=None):
    run()


def make(locations=er, **jobs_kw) -> SettingsService:
    return SettingsService(JobManager(EventBus(), spawn=inline, **jobs_kw), locations)


def code(call) -> str:
    with pytest.raises(OperationError) as e:
        call()
    return e.value.code


def _tree():
    return tree_state(data_dir())


def test_reading_the_page_writes_nothing():
    s = make()
    before = _tree()
    got = s.page()
    s.check_names({"pattern": "x-{game}"})
    assert _tree() == before
    assert got.game.key == "eldenring" and got.layout["pattern"]
    assert set(got.facts.detected) == {"me3_path", "game_exe", "me3_profile_dir", "saves_dir"}
    assert {"logo", "theme", "backups_keep", "play_repair_after"} <= set(got.specs)


def test_the_page_without_a_game_still_answers():
    got = make(locations=lambda: None).page()
    assert got.game.key == "eldenring" and all(v is None for v in got.facts.detected.values())


def test_a_choice_a_switch_and_a_number_are_saved_and_say_what_follows():
    s = make()
    got = s.set("logo", "ice")
    assert (got.value, got.follow, got.kind, load_settings().logo) == ("ice", "settings", "choice", "ice")
    assert s.set("theme", "light").follow == "appearance"
    assert s.set("launcher_channel", "beta").follow == "updates"
    assert s.set("play_boot_boost", False).stored_as == "play_boot_boost"
    assert load_settings().play_boot_boost is False
    assert s.set("backups_keep", 9000).value == 200 and load_settings().backups_keep == 200
    assert s.set("backups_keep", 1).value == 5


def test_bad_values_are_refused_with_codes_and_nothing_is_saved():
    s = make()
    before = _tree()
    for key, value, want in [
        ("logo", "purple", "invalid_choice"),
        ("logo", True, "invalid_value"),
        ("play_boot_boost", "yes", "invalid_value"),
        ("backups_keep", True, "invalid_value"),
        ("nope", 1, "unknown_setting"),
        ("me3_path", "Z:/does/not/exist.exe", "path_problem"),
        ("saves_dir", "Z:/does/not/exist", "path_problem"),
    ]:
        assert code(lambda k=key, v=value: s.set(k, v)) == want, key
    assert _tree() == before


def test_a_location_is_stored_per_game_or_globally(tmp_path):
    exe = tmp_path / "game.exe"
    exe.write_text("x")
    me3 = tmp_path / "me3.exe"
    me3.write_text("x")
    s = make(locations=lambda: Locations(catalog.NIGHTREIGN))
    assert s.set("game_exe", f" {exe} ").value == str(exe)  # trimmed
    s.set("me3_path", str(me3))
    st = load_settings()
    assert st.games["nightreign"]["game_exe"] == str(exe) and st.game_exe == ""  # not Elden Ring's
    assert st.me3_path == str(me3)
    assert s.page().facts.settings.games["nightreign"]["game_exe"] == str(exe)
    s.set("game_exe", "")  # blank = detect again
    assert load_settings().games["nightreign"]["game_exe"] == ""


def test_the_repair_switch_has_a_key_per_game():
    make().set("play_repair_after", True)
    assert getattr(load_settings(), play_service.repair_key(catalog.ELDEN_RING)) is True
    got = make(locations=lambda: Locations(catalog.NIGHTREIGN)).set("play_repair_after", False)
    assert got.stored_as == play_service.repair_key(catalog.NIGHTREIGN)


def test_folders():
    s = make()
    assert s.folder("settings") == data_dir()
    backups = s.folder("backups")
    assert backups is not None and backups.name == "saves" and backups.is_dir()  # asking made it
    assert code(lambda: s.folder("attic")) == "unknown_folder"


def test_the_folder_names_check():
    s = make()
    ok = s.check_names({"pattern": "b-{game}", "packages": "p", "natives": "n", "shared": "s"})
    assert ok.errors == {} and ok.preview == "b-eldenring"
    bad = s.check_names({"pattern": "plain", "packages": "a/b"})
    assert set(bad.errors) == {"pattern", "packages"} and bad.preview == ""


def test_renaming_checks_then_runs_as_a_job_only_when_started(monkeypatch):
    ran = []
    monkeypatch.setattr(layout_service, "rename_layout", lambda loc, **names: ran.append(names) or {})
    s = make()
    changes = s.check_rename({"pattern": "x-{game}"})
    assert list(changes) == ["pattern"] and changes["pattern"][1] == "x-{game}"
    assert ran == []  # checking runs nothing
    snap = s._jobs.get(s.rename({"pattern": "x-{game}"}, changes))
    assert snap.state == "done" and ran == [{"pattern": "x-{game}"}]


def test_renaming_checks_the_names_first():
    s = make()
    with pytest.raises(OperationError) as e:
        s.check_rename({"pattern": "plain"})
    assert e.value.code == "invalid_names" and "pattern" in e.value.details["errors"]
    assert code(lambda: s.check_rename({})) == "nothing_to_change"


def test_renaming_is_stale_when_the_changes_differ(monkeypatch):
    monkeypatch.setattr(layout_service, "rename_layout", lambda *a, **k: pytest.fail("ran"))
    s = make()
    assert code(lambda: s.rename({"pattern": "x-{game}"}, {"pattern": ("old", "x-{game}")})) == "stale"


def test_a_refused_layout_change_is_a_failed_job_with_a_code(monkeypatch):
    def refuse(loc, **names):
        raise LayoutError("The game is open.")

    monkeypatch.setattr(layout_service, "_fn", lambda name: refuse)  # under the code translation
    s = make()
    snap = s._jobs.get(s.rename({"pattern": "x-{game}"}, s.check_rename({"pattern": "x-{game}"})))
    assert snap.state == "failed" and snap.error.code == "layout_refused" and "game is open" in snap.error.message


def test_a_busy_session_or_a_running_game_refuses_the_layout_changes():
    for kw, want in (({"external_busy": lambda: True}, "busy"), ({"game_running": lambda: True}, "game_running")):
        assert code(lambda kw=kw: make(**kw).check_rename({"pattern": "x-{game}"})) == want
        assert code(lambda kw=kw: make(**kw).check_relocate("D:/x")) == want
        assert code(lambda kw=kw: make(**kw).check_move_all()) == want


def test_moving_the_profiles_folder_reports_facts_and_can_be_cancelled(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(layout_service, "profiles_facts", lambda loc: (3, 2048))
    monkeypatch.setattr(layout_service, "free_bytes", lambda p: 4096)

    def relocate(loc, new, progress=None, cancel=lambda: False):
        seen["new"] = new
        s._jobs.cancel("j1")  # the player presses Cancel while it moves
        seen["cancelled"] = cancel()
        raise LayoutCancelled("stopped")

    monkeypatch.setattr(layout_service, "_fn", lambda name: relocate)
    s = make()
    target = str(tmp_path / "OneDrive" / "Bayle")
    facts = s.check_relocate(target)
    assert (facts.folder, facts.profiles, facts.size, facts.free) == (target, 3, 2048, 4096)
    snap = s._jobs.get(s.relocate(target, str(load_settings().profiles_root or "")))
    assert seen["cancelled"] is True and snap.state == "cancelled"
    assert code(lambda: s.check_relocate(" ")) == "invalid_params"


def test_relocating_is_stale_when_the_root_changed(monkeypatch, tmp_path):
    monkeypatch.setattr(layout_service, "profiles_facts", lambda loc: (0, 0))
    monkeypatch.setattr(layout_service, "relocate", lambda *a, **k: pytest.fail("ran"))
    assert code(lambda: make().relocate(str(tmp_path / "x"), "Z:/somewhere/else")) == "stale"


def test_moving_every_profile_in(monkeypatch, tmp_path):
    a = tmp_path / "a.me3"
    s = make()
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [])
    assert code(s.check_move_all) == "nothing_to_move"
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [a])
    monkeypatch.setattr(layout_service, "move_all", lambda loc, found: len(found))
    assert s.check_move_all() == ["a"]
    snap = s._jobs.get(s.move_all(["a"]))
    assert (snap.state, snap.result) == ("done", {"count": 1})
    assert code(lambda: s.move_all(["a", "b"])) == "stale"  # the list changed since the client was asked


def test_clearing_leftovers_is_a_job_that_a_running_game_does_not_stop(monkeypatch):
    ran = []
    monkeypatch.setattr(play_service, "job_clear", lambda launch, loc: ran.append(loc.game.key))
    s = make(game_running=lambda: True)
    assert s._jobs.get(s.clear_leftovers()).state == "done" and ran == ["eldenring"]


def test_clearing_leftovers_is_refused_beside_a_writing_job():
    assert code(make(external_busy=lambda: True).clear_leftovers) == "busy"


class Store:
    def __init__(self):
        self.saved = []

    def save(self, record):
        self.saved.append(record)
        return True

    def records(self):
        return []


class Unbound:
    def save(self, record):
        raise AssertionError("the runtime's slot was used")

    records = save


def test_a_job_the_service_starts_writes_its_record_to_the_managers_store(monkeypatch, tmp_path):
    mine = Store()
    monkeypatch.setattr(layout_service, "plain_profiles", lambda loc: [tmp_path / "a.me3"])
    monkeypatch.setattr(layout_service, "move_all", lambda loc, found: len(found))
    s = SettingsService(JobManager(EventBus(), spawn=inline, store=mine), er)
    with run_logging.job_store_scope(Unbound()):  # another store in scope around the call: the manager's wins
        snap = s._jobs.get(s.move_all(s.check_move_all(), "Moving profiles..."))
    assert snap.state == "done"
    assert mine.saved and {r["title"] for r in mine.saved} == {"Moving profiles"}  # the record drops the dots
    assert mine.saved[-1]["outcome"] == "done"


def test_no_result_carries_wording(monkeypatch):
    s = make()
    monkeypatch.setattr(layout_service, "profiles_facts", lambda loc: (1, 2))
    monkeypatch.setattr(layout_service, "free_bytes", lambda p: None)
    results = [s.page(), s.set("logo", "ice"), s.check_names({"pattern": "b-{game}"}), s.check_relocate("D:/x")]
    for r in results:
        assert "said" not in {f.name for f in dataclasses.fields(r)}, r
