"""Drag and drop on the Saves page goes through the SAME rules and the SAME adapter slots as the menu twins: every drop
maps to exactly the call its menu entry makes (which then confirms, backs up, re-signs and reads back), and every
refusal is said in words. Nothing here writes a save: the twins' slots are recorded, never run."""

from pathlib import Path

import pytest

from bayle.ui.notifications import Notifier
from bayle.ui.pages.mods.presenter import Refusal
from bayle.ui.pages.saves.adapter import SavesAdapter
from bayle.ui.pages.saves.presenter import Drop, SavesPresenter
from support import er

CHAR = {"type": "character", "path": "A.sl2", "slot": 2}
LIVE = {"type": "live", "path": "A.sl2"}
COPY = {"type": "copy", "folder": "lib", "id": "c1", "missing": False}
BACKUP = {"type": "backup", "path": "x.bak"}
SLOT = {"type": "slot", "path": "B.co2", "slot": 3}
CARD = {"type": "card", "path": "B.co2", "free": [4, 5]}


class Host:
    busy = False
    game_running = False
    locations = er()

    def run_job(self, job, status):
        raise AssertionError("a drop only calls the twin's slot")

    def run_in_background(self, work, on_result):
        raise AssertionError("a drop only calls the twin's slot")

    def pick_file(self, title, filters):
        raise AssertionError("no file picker on a drop")

    def open_path(self, path):
        pass

    def saves_in_use(self):
        return {}


def adapter(host=None):
    notifier, told = Notifier(), []
    notifier.toastRequested.connect(lambda text, error: told.append((text, error)))
    a = SavesAdapter(host or Host(), notifier)
    calls = []
    for name in ("copyCharacter", "copyFromLibrary", "replaceFromLibrary", "restoreBackup", "backUpNow"):
        setattr(a, name, lambda *args, _n=name: calls.append((_n, args)))
    a.nameAsked.connect(lambda mode, path: calls.append(("nameAsked", (mode, path))))
    return a, calls, told


TWINS = [  # (source, target, the call the menu twin makes)
    (CHAR, SLOT, ("copyCharacter", ("A.sl2", 2, "B.co2", 3))),  # character row > slot (copyTo menu)
    (CHAR, CARD, ("copyCharacter", ("A.sl2", 2, "B.co2", 4))),  # onto the card body: the first free slot
    (COPY, {"type": "card", "path": "B.co2"}, ("replaceFromLibrary", ("lib", "c1", "B.co2"))),
    (BACKUP, {"type": "card", "path": "B.co2"}, ("restoreBackup", ("x.bak", "B.co2"))),
    (
        {"type": "copychar", "folder": "lib", "id": "c1", "slot": 2},
        SLOT,
        ("copyFromLibrary", ("lib", "c1", 2, "B.co2", 3)),
    ),  # one character out of a Library copy (Ctrl+C on its row, Ctrl+V on the slot)
    (LIVE, {"type": "library"}, ("nameAsked", ("copy", "A.sl2"))),  # Save a copy asks for a name, as its menu does
    (LIVE, {"type": "backups"}, ("backUpNow", ("A.sl2",))),
]


@pytest.mark.parametrize(("source", "target", "call"), TWINS)
def test_every_drop_is_the_call_its_menu_twin_makes(source, target, call):
    a, calls, told = adapter()
    assert a.dropReason(source, target) == ""
    a.drop(source, target)
    assert calls == [call] and told == []


WRITES = [t for t in TWINS if t[:2] != (LIVE, {"type": "library"})]  # Save a copy only reads the live save


def test_save_a_copy_is_allowed_while_the_game_runs():
    host = Host()
    host.game_running = True
    a, calls, told = adapter(host)
    assert a.dropReason(LIVE, {"type": "library"}) == ""
    a.drop(LIVE, {"type": "library"})
    assert calls == [("nameAsked", ("copy", "A.sl2"))] and told == []


@pytest.mark.parametrize(("source", "target", "call"), WRITES)
def test_while_the_game_runs_every_write_drop_is_refused_in_words(source, target, call, monkeypatch):
    host = Host()
    host.game_running = True
    a, calls, told = adapter(host)
    assert "Close" in a.dropReason(source, target)
    a.drop(source, target)
    assert calls == [] and len(told) == 1 and told[0][1] and "Close" in told[0][0]


def test_a_running_job_refuses_a_drop_too():
    host = Host()
    host.busy = True
    a, calls, told = adapter(host)
    a.drop(CHAR, SLOT)
    assert calls == [] and "job" in told[0][0]


@pytest.mark.parametrize(
    ("source", "target", "words"),
    [
        (CHAR, {"type": "slot", "path": "A.sl2", "slot": 2}, "same slot"),
        (CHAR, {"type": "card", "path": "B.co2", "free": []}, "Every slot"),
        (CHAR, {"type": "library"}, "slot of a live save"),
        ({**COPY, "missing": True}, {"type": "card", "path": "B.co2"}, "missing"),
        (LIVE, {"type": "card", "path": "B.co2"}, "replace it"),
        (COPY, {"type": "library"}, "already in the Library"),
        (BACKUP, {"type": "backups"}, "already in the Backups"),
        ({"type": "mystery"}, SLOT, "Drop a character on a slot"),
        (COPY, SLOT, "restore it"),
        (BACKUP, SLOT, "restore it"),
        (COPY, {"type": "backups"}, "Back up now"),
        (BACKUP, {"type": "library"}, "Keep it"),
        (LIVE, SLOT, "replace it"),
    ],
)
def test_a_refusal_says_why(source, target, words):
    plan = SavesPresenter().drop(source, target, game="Elden Ring", running=False, busy=False, encrypted=False)
    assert isinstance(plan, Refusal) and words in plan.body


def test_a_nightreign_card_refuses_a_character():
    plan = SavesPresenter().drop(CHAR, SLOT, game="Nightreign", running=False, busy=False, encrypted=True)
    assert isinstance(plan, Refusal) and "whole files" in plan.body


def test_the_drop_rules_read_nothing_from_disk(monkeypatch):
    import builtins

    monkeypatch.setattr(builtins, "open", lambda *a, **k: pytest.fail("a drag spot read a file"))
    plan = SavesPresenter().drop(CHAR, SLOT, game="x", running=False, busy=False, encrypted=False)
    assert isinstance(plan, Drop)


def test_ctrl_c_then_ctrl_v_is_the_same_copy_as_the_drop():
    a, calls, told = adapter()
    a.pasteInto(SLOT)  # nothing copied yet
    assert calls == [] and told and told[0][1]
    a.copyCharacterKey("A.sl2", 2)
    a.pasteInto(SLOT)
    assert calls == [("copyCharacter", ("A.sl2", 2, "B.co2", 3))]
    calls.clear()
    a.copyLibraryCharacterKey("lib", "c1", 2)
    a.pasteInto(SLOT)
    assert calls == [("copyFromLibrary", ("lib", "c1", 2, "B.co2", 3))]


def test_import_of_several_files_imports_each_and_names_the_skipped(tmp_path, monkeypatch):
    from bayle.ui.pages.saves import adapter as mod

    a, calls, told = adapter()
    jobs, added = [], []
    a.host.run_job = lambda job, status: jobs.append(status)
    a._libs = {str(tmp_path): {}}
    monkeypatch.setattr(mod.save_library, "add", lambda folder, src, name, game, action: added.append(src.name) or {})
    monkeypatch.setattr(mod.save_library, "default_name", lambda src, game: src.stem)
    a._game = lambda: None
    a._import_many([tmp_path / "a.sl2", tmp_path / "b.co2"])
    assert jobs == ["Importing 2 files..."]
    a.dropFiles([str(tmp_path / "a.sl2"), str(tmp_path / "x.txt")])  # one save file: asks for its name
    assert told and "x.txt" in told[0][0]


def test_import_is_allowed_while_the_game_runs():
    host = Host()
    host.game_running = True
    a, calls, told = adapter(host)
    a._offer_import(Path("A.sl2"))
    assert told == []
