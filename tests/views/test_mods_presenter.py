"""The Mods presenter without Qt: the header, groups and rows with the closed tag vocabulary, the not-loaded and
loads-nothing lines, the Parameters card, the InfoBars, the Load order panel, and the words of the confirmations;
every string through tr()."""

import gettext
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from bayle.platform import text
from bayle.services import profile_mods
from bayle.services.profile_mods import PageFacts, Removal
from bayle.views import load_order
from bayle.views.mods import ModsPresenter

PROFILE = Path("C:/mods/eldenring-mods/main.me3")


def entry(index, name, kind="package", **more):
    return {
        "index": index,
        "name": name,
        "kind": kind,
        "id": name if kind == "package" else "",
        "path": f"mod/{name}" if kind == "package" else f"natives/{name}",
        "enabled": True,
        "load_after": [],
        "load_before": [],
        **more,
    }


ENTRIES = (
    entry(0, "flora"),
    entry(1, "bundle"),
    entry(2, "birds", enabled=False, optional=True),
    entry(3, "example", load_after=[{"id": n} for n in ("a", "b", "c", "d")]),
    entry(4, "ersc.dll", "native", load_early=True, initializer={"function": "ERRInit"}),
    entry(5, "gone.dll", "native"),
)


def facts(**over) -> PageFacts:
    base = dict(
        profile=PROFILE,
        entries=ENTRIES,
        display={"package": (0, 2, 1, 3), "native": (4, 5)},
        problems={5: ("DLL missing",)},
        loads_nothing=(1,),
        stays_last=(3,),
        missing=(5,),
        empty={},
        configs={4: ("ersc_settings.ini",)},
        not_loaded={"package": 2, "native": 0},
    )
    return PageFacts(**{**base, **over})


def scan(**over):
    base = {
        "profile": str(PROFILE),
        "health": {"state": "current", "packs": ["example"], "backend": "rebuild.json", "reasons": []},
        "overlaps": {
            "conflicts": [
                {
                    "path": "parts/a.partsbnd.dcx",
                    "winner": "example",
                    "losers": [{"id": "flora", "outcome": "replaced"}],
                },
                {"path": "msg/b.msgbnd.dcx", "winner": "example", "losers": [{"id": "flora", "outcome": "combined"}]},
            ]
        },
        "problems": [{"name": "gone.dll", "kind": "native", "problems": ["DLL missing"]}],
        "stay_last": {"name": "example", "late": ["flora", "birds"], "can_fix": True, "problem": ""},
    }
    return {**base, **over}


def rows(state, kind="package"):
    return next(g for g in state.groups if g.kind == kind).rows


def test_importing_the_presenter_pulls_in_no_qt():
    code = (
        "import sys; import bayle.views.mods; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_rows_follow_the_shown_order_and_a_folder_of_mods_is_a_line_not_a_row():
    state = ModsPresenter().page(facts(), scan())
    packages = rows(state)
    assert [(r.position, r.name) for r in packages] == [(1, "flora"), (2, "birds"), (3, "example")]
    group = state.groups[0]
    assert group.title == "Packages" and group.count == "2 loaded, 1 off"
    assert [(line.text, line.action, line.index) for line in group.lines] == [
        ("2 folders in this profile are not loaded", "Add...", -1),
        ("bundle loads nothing: it points at a folder of mods", "Remove", 1),
    ]
    assert state.title == "main" and state.counts == "3 packages  ·  2 natives"


def test_tags_come_from_the_closed_list_two_at_most_the_rest_in_the_tooltip():
    packages = rows(ModsPresenter().page(facts(), scan()))
    flora = packages[0]
    assert [t.text for t in flora.tags] == ["Clash · 1 file"]
    assert flora.more.splitlines() == ["mod/flora"]
    example = packages[2]
    assert [t.text for t in example.tags] == ["Stays last"] and example.locked
    birds = packages[1]
    assert not birds.enabled and [t.text for t in birds.tags] == ["Optional"]
    natives = rows(ModsPresenter().page(facts(), scan()), "native")
    assert [t.text for t in natives[0].tags] == ["Loads early"] and natives[0].has_configs
    assert natives[0].configs_tip == "ersc_settings.ini"
    assert [t.text for t in natives[1].tags] == ["Missing"]


def test_the_status_line_names_dependencies_and_an_initializer_and_a_problem_wins():
    natives = rows(ModsPresenter().page(facts(), scan()), "native")
    assert natives[0].status == "calls ERRInit" and not natives[0].status_error
    assert natives[1].status == "DLL missing" and natives[1].status_error
    example = rows(ModsPresenter().page(facts(), scan()))[2]
    assert example.status == "after 4 others"
    empty = rows(ModsPresenter().page(facts(empty={0: "empty"}), None))[0]
    assert empty.status.startswith("Empty.")


def test_the_health_pill():
    p = ModsPresenter()
    assert p.page(facts(), None).health is None  # until the first scan
    assert p.page(facts(), scan()).health.__dict__ == {"text": "1 file clashes", "level": "danger"}
    calm = scan(overlaps={"conflicts": []}, health={"state": "stale", "packs": ["example"]})
    calm_health = p.page(facts(), calm).health
    assert calm_health is not None and calm_health.text == "Rebuild needed"
    fine = scan(overlaps={"conflicts": []})
    assert p.page(facts(), fine).health.__dict__ == {"text": "All mods apply", "level": "success"}
    other = scan(profile="C:/elsewhere/other.me3")
    assert p.page(facts(), other).health is None  # an answer for another profile is dropped


def test_the_parameters_card():
    p = ModsPresenter()
    assert not p.parameters({"state": "single", "packs": []}, False).visible  # no package ships parameters
    current = p.parameters({"state": "current", "packs": ["a", "b"], "backend": "rebuild.json"}, False)
    assert (current.visible, current.pill, current.level, current.action) == (
        True,
        "Combined, up to date (rebuild.json)",
        "success",
        "Rebuild",
    )
    stacked = p.parameters({"state": "stacked", "packs": ["a", "b"], "winner": "b", "can_combine": True}, False)
    assert stacked.pill == "Stacked: b's regulation.bin wins, others ignored" and stacked.action == "Combine"
    assert p.parameters({"state": "single", "packs": ["a"]}, False).pill == "One pack, used as is"
    assert p.parameters({"state": "failed", "packs": ["a"], "backend": "t"}, False).level == "danger"
    assert (
        p.parameters({"state": "stale", "packs": ["a"], "backend": "t"}, True).blocked == "Blocked while the game runs"
    )


def test_the_online_warning_comes_first_and_the_fingerprint_is_on_the_card():
    from bayle.services.game_checks import Fingerprint

    p = ModsPresenter()
    stale = {"state": "stale", "packs": ["a"], "backend": "t", "reasons": []}
    tool = SimpleNamespace(label="rebuild.json", package={"name": "Example"})
    state = p.page(facts(online_with="flora", fingerprint=Fingerprint("1A2B3C4D", 9, "flora")), scan(health=stale))
    online = state.notices[0]
    assert (online.key, online.severity, online.action, online.closable) == (
        "online",
        "warning",
        "Launch Offline",
        True,
    )
    assert online.text == (
        "This profile goes online with changed parameters (flora's regulation.bin). FromSoftware's servers can see "
        "the change."
    )
    assert [n.key for n in p.notices(stale, tool, (), "flora")] == ["online", "stale"]  # two at most
    assert state.parameters.fingerprint == "Parameters fingerprint: 1A2B3C4D (flora's regulation.bin)"
    assert state.parameters.fingerprint_note.startswith("Co-op partners need the same parameters.")
    own = p.parameters(stale, False, Fingerprint("00FF00FF", 9, ""))
    assert own.fingerprint == "Parameters fingerprint: 00FF00FF (the game's own regulation.bin)"
    assert p.parameters(stale, False).fingerprint == "" and p.page(facts(), None).notices == ()


def test_the_overhaul_words():
    p = ModsPresenter()
    menu = p.overhaul_menu(True, None, False)
    assert (menu.visible, menu.remove, menu.can_remove, menu.can_clean) == (True, "Remove overhaul...", False, False)
    assert p.overhaul_menu(False, {"label": "Toy"}, True).remove == "Remove Toy..."
    found = SimpleNamespace(ok=True, update=False, label="Toy", lines=["a line"], notes=["a note"], refusals=[])
    install = p.overhaul_install(PROFILE, found)
    assert install.title == "Install Toy in main.me3" and install.changes == ("a line", "a note")
    assert install.apply == "Install" and "installer does not run." in install.safety
    assert p.overhaul_installing(found) == "Installing Toy..."
    update = p.overhaul_install(PROFILE, SimpleNamespace(**{**found.__dict__, "update": True}))
    assert update.title == "Update Toy in main.me3" and update.apply == "Update"
    refused = p.overhaul_install(PROFILE, SimpleNamespace(**{**found.__dict__, "ok": False, "refusals": ["No."]}))
    assert (refused.title, refused.body) == ("Toy can't be installed here", "No.")
    removal = SimpleNamespace(ok=True, lines=["out"], refusals=[], asked=[SimpleNamespace(entry="ersc.dll")])
    remove = p.overhaul_remove(PROFILE, "Toy", removal)
    assert remove.title == "Remove Toy from main.me3" and not remove.option_checked
    assert remove.option == "Also switch ersc.dll back off, as it was before the install"
    assert p.overhaul_remove(PROFILE, "Toy", SimpleNamespace(**{**removal.__dict__, "asked": []})).option == ""
    assert p.overhaul_put_back("Toy").none == "Leave them"
    assert p.leftovers(True).none == "Next" and p.leftovers(False).none == ""
    backups = p.leftover_backups(SimpleNamespace(path=Path("C:/x/Example Backups"), label="Example Backups (2 MB)"))
    assert backups.title == "Also remove Example Backups?"
    assert backups.changes == ("Example Backups (2 MB) goes to the Recycle Bin",)


def test_infobars_two_at_once_and_a_closed_one_stays_closed():
    p = ModsPresenter()
    tool = SimpleNamespace(label="rebuild.json", package={"name": "Example"})
    stale = {"state": "stale", "packs": ["a"], "reasons": ["a new pack loads before it"]}
    notices = p.notices(stale, tool, ("the install of X was taken back",))
    assert [n.key for n in notices] == ["stale", "allow-tool"]
    assert notices[0].text == "Combined parameters are out of date: a new pack loads before it"
    assert notices[1].action == "Allow..."
    p.close_notice("allow-tool")
    assert [n.key for n in p.notices(stale, tool, ("x",))] == ["stale", "recovered"]


def test_the_load_order_panel():
    panel = load_order.panel(scan())
    assert panel.stays_last is not None
    assert (
        panel.stays_last.text == "flora, birds load after example, which must stay last: they replace example's files."
    )
    assert panel.stays_last.can_fix
    assert [c.path for c in panel.clashes] == ["parts/a.partsbnd.dcx", "msg/b.msgbnd.dcx"]  # lost first
    assert panel.clashes[0].losers == "flora (replaced)" and panel.clashes[0].lost
    assert panel.clash_note == "2 files are shipped by two packages; 1 of them reach the game from one package only."
    assert [(r.name, r.why) for r in panel.refused] == [("gone.dll", "DLL missing")]
    calm = load_order.panel(scan(stay_last={"name": "example", "late": [], "can_fix": False}, overlaps={}))
    assert calm.stays_last is not None and calm.stays_last.text == "example loads last, as it must."
    assert calm.clash_note == "No two packages ship the same file."


def test_the_confirmations_words():
    p = ModsPresenter()
    plan = Removal("package", "flora", Path("C:/mods/mod/flora"), ("birds",), ("regulation.bin",), False)
    removal = p.removal(PROFILE, plan)
    assert removal.title == "Remove flora from the profile" and removal.option == ""
    assert removal.changes[1].startswith("Its regulation.bin is still in the merged mods")
    alone = p.removal(PROFILE, Removal("native", "x.dll", Path("C:/mods/natives/x"), (), (), True))
    assert alone.option == "Also move the folder x to the Recycle Bin"
    trim = p.trim([{"folder": Path("b4"), "size": 2 * 1048576}])
    assert trim.title == "Move 1 older rebuild backup to the Recycle Bin" and "The newest 3 stay" in trim.safety
    tool = SimpleNamespace(label="rebuild.json", package={"name": "Example"}, describe=lambda: "python refresh.py")
    assert p.tool(tool).detail == "It comes with Example and runs:\n\npython refresh.py"
    managed = p.delete_refusal(profile_mods.DELETE_MANAGED, "Example Overhaul")
    assert managed is not None and managed.body == "Example Overhaul is managed by its installer. Delete it there."
    assert p.delete_refusal(None) is None
    assert len(p.delete_profile(PROFILE).changes) == 2
    assert p.delete_profile(PROFILE, "Example Overhaul").changes[-1] == (
        "Example Overhaul's shared files stay; Remove overhaul first to take them out too."
    )
    assert (
        p.holder(PROFILE, "bundle", ["example"]).changes[-1]
        == "example must load after it: that setting is taken out too"
    )


def test_every_string_goes_through_tr():
    class Shout(gettext.NullTranslations):
        def gettext(self, message):
            return re.sub(
                r"\{[^}]*\}|[^{]+", lambda m: m.group(0) if m.group(0)[0] == "{" else m.group(0).upper(), message
            )

        def ngettext(self, msgid1, msgid2, n):
            return self.gettext(msgid1 if n == 1 else msgid2)

    text.install(Shout())
    try:
        state = ModsPresenter().page(facts(), scan())
        assert state.groups[0].title == "PACKAGES" and state.counts == "3 PACKAGES  ·  2 NATIVES"
        assert state.health is not None and state.health.text == "1 FILE CLASHES"
        assert ModsPresenter().open_window_text == "OPEN NEW MODS WINDOW"
    finally:
        text.install(None)


def test_a_misnamed_or_crowded_folder_gets_one_plain_notice():
    check = profile_mods.folder_check
    mis = ModsPresenter().page(facts(folder=check.FolderCheck(check.MISNAMED, "old", (PROFILE,))), scan())
    note = next(n for n in mis.notices if n.key == "folder")
    assert note.text == "This profile's folder is named 'old'. Rename it to match the profile?"
    assert note.action == "Rename folder"
    crowd = ModsPresenter().page(facts(folder=check.FolderCheck(check.CROWDED, "pack", (PROFILE, PROFILE))), scan())
    note = next(n for n in crowd.notices if n.key == "folder")
    assert note.text == "This folder holds 2 profiles. Each profile needs its own folder."
    assert note.action == "Split into folders"
    for kind in (check.OK, check.OUTSIDE):  # nothing to say
        assert not [
            n for n in ModsPresenter().page(facts(folder=check.FolderCheck(kind)), scan()).notices if n.key == "folder"
        ]
    c = ModsPresenter.split_confirm(3, 2, 1)
    changes, safety, button = c.changes, c.safety, c.apply
    assert changes == ("3 profiles, 2 mods copied, 1 moved.",) and safety == "Undo in Activity." and button == "Split"


def test_a_profile_outside_bayles_folder_gets_a_move_in_notice():
    note = next(n for n in ModsPresenter().page(facts(outside=True), scan()).notices if n.key == "outside")
    assert note.text == "This profile is outside Bayle's folder, so Bayle can't manage its layout."
    assert note.action == "Move in..."
    assert not [n for n in ModsPresenter().page(facts(), scan()).notices if n.key == "outside"]


def test_loose_dlls_get_one_notice_with_counts_and_a_tag():
    page = ModsPresenter().page(facts(loose_dlls=(4, 5)), scan())
    note = next(n for n in page.notices if n.key == "dll-folders")
    assert note.text == "2 DLL mods aren't in their own folders." and note.action == "Put in folders"
    one = ModsPresenter().page(facts(loose_dlls=(4,)), scan())
    assert next(n for n in one.notices if n.key == "dll-folders").text == "1 DLL mod isn't in its own folder."
    natives = next(g for g in one.groups if g.kind == "native")
    assert [t.text for r in natives.rows if r.index == 4 for t in r.tags] == ["Loads early", "No folder"]
    assert not [n for n in ModsPresenter().page(facts(), scan()).notices if n.key == "dll-folders"]
    c = ModsPresenter.dll_folders_confirm(2, 5, 1)
    changes, safety, button = c.changes, c.safety, c.apply
    assert changes[0] == "2 DLLs get a folder in natives." and "1 settings file is copied" in changes[2]
    assert safety == "Undo in Activity." and button == "Put in folders"
