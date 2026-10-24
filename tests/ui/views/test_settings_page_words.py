"""The Settings page's words: rows from the engine's facts, the sentences for a saved setting, the three confirms with
their path cautions, and one refusal text per engine error code."""

import pytest

from bayle.errors import OperationError
from bayle.services import settings as engine
from bayle.services.settings import Changed, NameCheck, RelocateFacts
from bayle.ui.pages.settings import presenter as view
from bayle.work.prompts import Confirm


def test_the_switch_table_is_the_engines_list_in_the_same_order():
    assert tuple(s.key for s in view.switches()) == engine.SWITCH_KEYS


def test_the_page_rows_come_from_the_engines_facts():
    state = view.build(engine.SettingsService(_jobs(), lambda: None).page())
    assert [r.key for r in state.locations] == list(view.LOCATION_WORDS)
    assert {r.key for r in state.switches} == set(engine.SWITCH_KEYS)
    assert state.layout.keys() == view.LAYOUT_LABELS.keys()
    assert set(state.labels) == set(view.CHOICE_LABELS)


def _jobs():
    from bayle.work.events import EventBus
    from bayle.work.jobs import JobManager

    return JobManager(EventBus())


def test_name_problems_are_worded_per_field():
    assert view.name_errors(NameCheck({"pattern": "Use {game} once."}, "")) == {"pattern": "Use {game} once."}


def test_saving_a_setting_says_what_changed():
    assert view.said(Changed("game_exe", r"D:\g\eldenring.exe", "game_exe", "settings", "location")) == (
        "Location updated eldenring.exe"
    )
    assert view.said(Changed("saves_dir", "", "saves_dir", "settings", "location")) == (
        "Location updated Detecting again."
    )
    assert view.said(Changed("log_level", "verbose", "log_level", "settings", "choice")) == view.LOG_LEVEL_SAID
    assert view.said(Changed("theme", "dark", "theme", "appearance", "choice")) == ""


def test_path_cautions():
    gb = 1024**3
    assert view.path_warnings(r"D:\Games\Bayle", gb, 10 * gb) == []
    assert len(view.path_warnings(r"C:\Users\me\OneDrive\Bayle", gb, 10 * gb)) == 1
    assert "not enough free space" in view.path_warnings(r"D:\x", 2 * gb, gb)[0]
    assert "very long" in view.path_warnings("D:\\" + "a" * 250, gb, 10 * gb)[0]
    assert view.path_warnings(r"D:\x", gb, None) == []


def test_the_confirms_say_what_moves_and_where_the_undo_is():
    c = view.relocate_confirm(RelocateFacts(r"D:\Bayle", 3, 2048, 10**12))
    assert c.title == r"Move your profiles and mods to D:\Bayle?"
    assert c.changes == ("3 profiles, 2.0 KB.",) and c.safety == "Undo in Activity." and c.apply == "Move"
    assert view.relocate_confirm(RelocateFacts("D:/x", 1, 10, 10**12)).changes == ("1 profile, 10 B.",)
    c = view.rename_confirm({"pattern": ("b-{game}", "x-{game}")})
    assert c.changes == ("Game folder: b-{game} becomes x-{game}.",) and c.apply == "Rename"
    c = view.move_all_confirm(["a", "b"])
    assert c.changes == ("2 profiles move: a, b.",) and c.apply == "Move all"
    assert view.move_all_confirm(["a"]).changes == ("1 profile moves: a.",)
    assert isinstance(view.move_all_confirm(["a"]), Confirm)


@pytest.mark.parametrize(
    ("code", "line"),
    [
        ("busy", "Wait for the current job.. Another job is running."),
        ("game_running", "The game is running.. Close it first."),
        ("nothing_to_move", "Nothing to move. No profiles are outside Bayle's folder."),
        ("nothing_to_change", "The names are the ones in use already."),
        ("invalid_params", "Pick a folder."),
        ("stale", "Things changed since you were asked. Ask again."),
        ("invalid_names", "engine sentence"),
        ("path_problem", "engine sentence"),
    ],
)
def test_every_refusal_has_its_words(code, line):
    assert view.refusal_line(OperationError(code, "engine sentence")) == line


def test_a_quiet_refusal_is_the_body_alone():
    assert view.refusal_line(OperationError("nothing_to_move", "x"), body_only=True) == (
        "No profiles are outside Bayle's folder."
    )
    assert view.refusal_line(OperationError("unknown_setting", "x", {"key": "k"})) == "There is no setting called k."
