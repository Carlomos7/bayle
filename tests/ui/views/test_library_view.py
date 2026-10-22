"""The Mods page over a real Library (temporary folders only): Shared rows carry their tag, Share / Use in other
profiles / Use a separate copy run the Library's operations after their confirm, the Library dialog lists versions,
and the duplicates hint appears. Renders go to RS_VIEW_SHOTS when it is set."""

import shutil
from pathlib import Path

import pytest
from test_mods_view import Host, closed, opened, settle

from bayle.game import catalog
from bayle.game.locate import Locations, Overrides
from bayle.mods import shared_mods
from bayle.platform import trash
from bayle.services.mods import profile_entries

HEAD = 'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n'


def make(root: Path, name: str, mods: dict[str, bytes]) -> Path:
    entries = ""
    for mod, data in mods.items():
        (root / name / "packages" / mod / "parts").mkdir(parents=True)
        (root / name / "packages" / mod / "parts" / f"{mod}.dcx").write_bytes(data)
        entries += f"\n[[packages]]\nid = '{mod}'\npath = 'packages/{mod}'\n"
    profile = root / name / f"{name}.me3"
    profile.write_bytes((HEAD + entries).encode())
    return profile


class LibraryHost(Host):
    def __init__(self, profile: Path, loc: Locations):
        super().__init__(profile)
        self.locations = loc


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "profiles"
    root = home / "b-eldenring"
    a = make(root, "a", {"grass": b"same", "sky": b"only a"})
    b = make(root, "b", {"grass": b"same"})
    loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(home)))
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    monkeypatch.setattr(trash, "available", lambda: True)
    monkeypatch.setattr(trash, "send", lambda p: shutil.rmtree(p) or {})
    monkeypatch.setattr(trash, "exists", lambda r: False)
    return loc, a, b


def run_ask(w, host, act):
    asked: list = []
    w.notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
    act()
    token, words = asked[-1]
    w.notifier.answerWith(token, True, False)
    job, _done = host.ran
    job(None, host.locations)
    return words


def index_of(profile: Path, name: str) -> int:
    return next(e["index"] for e in profile_entries(profile) if e["name"] == name)


def test_share_use_and_separate_from_the_page(qt_app, world, shots):
    loc, a, b = world
    host = LibraryHost(a, loc)
    w = opened(host)
    try:
        rows = {r.name: r for r in w.adapter.state().groups[0].rows}
        assert rows["grass"].shared == 0 and rows["grass"].can_share
        assert [t.text for t in rows["grass"].tags] == []  # nobody shares yet: no Separate tag either
        words = run_ask(w, host, lambda: w.adapter.share(index_of(a, "grass")))
        assert words["title"] == "Share grass"
        w.adapter.refresh()
        settle()
        rows = {r.name: r for r in w.adapter.state().groups[0].rows}
        assert rows["grass"].shared == 1 and rows["grass"].tags[0].text == "Shared · 1 profile"
        assert [t.text for t in rows["sky"].tags] == ["Separate"]
        w.window.grabWindow().save(str(shots / "library-mods-page.png"))
        # b has its own copy of the same files: it is offered, and ticking it replaces the copy
        picks: list = []
        w.adapter.pickRequested.connect(lambda key, words, rows_: picks.append((key, words, rows_)))
        w.adapter.useInOthers(index_of(a, "grass"))
        key, pick_words, pick_rows = picks[-1]
        assert pick_rows == ["b (has its own copy; ticking replaces it)"]
        w.adapter.picked(key, [0])
        job, _ = host.ran
        job(None, loc)
        assert shared_mods.shared_count(loc, b, index_of(b, "grass")) == 2
        w.adapter.refresh()
        settle()
        rows = {r.name: r for r in w.adapter.state().groups[0].rows}
        assert rows["grass"].tags[0].text == "Shared · 2 profiles"
        run_ask(w, host, lambda: w.adapter.separate(index_of(a, "grass")))
        assert (a.parent / "packages" / "grass" / "parts" / "grass.dcx").read_bytes() == b"same"
        assert shared_mods.shared_count(loc, b, index_of(b, "grass")) == 1
    finally:
        closed(w)


def test_the_library_dialog_lists_versions_and_removes_unused_ones(qt_app, world, shots):
    loc, a, b = world
    shared_mods.share(a, [index_of(a, "grass")], loc=loc)
    shared_mods.share(b, [index_of(b, "grass")], loc=loc)
    new = a.parent.parent.parent.parent / "dl" / "grass"
    (new / "parts").mkdir(parents=True)
    (new / "parts" / "grass.dcx").write_bytes(b"v2")
    shared_mods.update(a, index_of(a, "grass"), new, everywhere=True, loc=loc, label="v2")
    host = LibraryHost(a, loc)
    w = opened(host)
    try:
        rows = w.adapter.libraryList()
        assert [r["name"] for r in rows] == ["grass"] and len(rows[0]["versions"]) == 2
        assert [v["unused"] for v in rows[0]["versions"]] == [True, False]
        assert rows[0]["versions"][1]["title"].endswith("v2") and rows[0]["versions"][1]["usedBy"] == "Used by a, b"
        w.adapter.dialogRequested.emit("library", -1)
        settle(300)
        w.window.grabWindow().save(str(shots / "library-dialog.png"))
        words = run_ask(w, host, w.adapter.removeUnused)
        assert words["title"] == "Remove unused versions" and "1 version" in words["changes"][0]
        assert [len(v["versions"]) for v in w.adapter.libraryList()] == [1]
    finally:
        closed(w)


def test_the_duplicates_hint_shows_over_a_gigabyte_and_opens_the_library(qt_app, world, monkeypatch, shots):
    loc, a, b = world
    host = LibraryHost(a, loc)
    monkeypatch.setattr(shared_mods, "HINT_BYTES", 1)  # a gigabyte of test files is not needed
    w = opened(host)
    try:
        notices = w.adapter.state().notices
        assert [n.key for n in notices] == ["library-hint"]
        assert notices[0].text.startswith("1 mod is in several profiles") and notices[0].text.endswith(
            "Save space by sharing"
        )
        w.window.grabWindow().save(str(shots / "library-hint.png"))
    finally:
        closed(w)


def test_duplicate_asks_and_can_share_with_the_original(qt_app, world):
    loc, a, b = world
    host = LibraryHost(a, loc)
    w = opened(host)
    try:
        asked: list = []
        w.notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
        w.adapter.duplicateProfile()
        token, words = asked[-1]
        assert words["option"].startswith("Share the game-file mods")
        w.notifier.answerWith(token, True, True)  # the option ticked: share them with the original
        job, _ = host.ran
        job(None, loc)
        copy = a.parent.parent / "a copy" / "a copy.me3"
        assert copy.is_file() and not (copy.parent / "packages" / "grass").exists()
        assert (
            shared_mods.shared_count(loc, a, index_of(a, "grass")) == 2
            and shared_mods.shared_count(loc, a, index_of(a, "sky")) == 2
        )
    finally:
        closed(w)


def test_the_install_dialog_offers_keep_separate_or_share_for_identical_files(qt_app, world, tmp_path, shots):
    from bayle.services import mods as mod_service
    from bayle.views.mod_install import InstallDraft

    loc, a, b = world
    c = make(a.parent.parent, "c", {"sky": b"only c"})
    src = tmp_path / "dl" / "grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.dcx").write_bytes(b"same")
    plan = mod_service.plan_mod_install(c, src, loc=loc)
    assert plan["library"]["identical"] == ["a", "b"]
    host = LibraryHost(c, loc)
    w = opened(host)
    try:
        draft = InstallDraft(plan, c)
        view = draft.view()["library"]
        assert [o["text"] for o in view["options"]] == ["Keep separate", "Share"] and view["choice"] == "separate"
        assert draft.finish()["library_choice"] == "separate"
        draft.library_choice = "share"
        assert draft.finish()["library_choice"] == "share"
        installer = w.adapter.installer
        installer._draft = draft
        installer.viewChanged.emit()
        installer.openRequested.emit()
        settle(400)
        w.window.grabWindow().save(str(shots / "library-install-identical.png"))
    finally:
        closed(w)
