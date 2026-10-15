"""The Mods presenter without Qt: the header, groups and rows with the closed tag vocabulary, the not-loaded and
loads-nothing lines, the Parameters card, the InfoBars, the Load order panel, and the words of the confirmations;
every string through tr()."""

import gettext
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from roundtable_souls.services import profile_mods
from roundtable_souls.services.profile_mods import PageFacts, Removal
from roundtable_souls.ui import text
from roundtable_souls.ui.pages.mods import load_order
from roundtable_souls.ui.pages.mods.presenter import ModsPresenter

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
    entry(3, "revive", load_after=[{"id": n} for n in ("a", "b", "c", "d")]),
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
        outside=(0,),
        shared={0: 3},
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
        "health": {"state": "current", "packs": ["revive"], "backend": "rebuild.json", "reasons": []},
        "overlaps": {
            "conflicts": [
                {
                    "path": "parts/a.partsbnd.dcx",
                    "winner": "revive",
                    "losers": [{"id": "flora", "outcome": "replaced"}],
                },
                {"path": "msg/b.msgbnd.dcx", "winner": "revive", "losers": [{"id": "flora", "outcome": "combined"}]},
            ]
        },
        "problems": [{"name": "gone.dll", "kind": "native", "problems": ["DLL missing"]}],
        "stay_last": {"name": "revive", "late": ["flora", "birds"], "can_fix": True, "problem": ""},
    }
    return {**base, **over}


def rows(state, kind="package"):
    return next(g for g in state.groups if g.kind == kind).rows


def test_importing_the_presenter_pulls_in_no_qt():
    code = (
        "import sys; import roundtable_souls.ui.pages.mods.presenter; "
        "print(sorted(m for m in sys.modules if m.split('.')[0] in ('PySide6', 'shiboken6', 'qfluentwidgets')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "[]"


def test_rows_follow_the_shown_order_and_a_folder_of_mods_is_a_line_not_a_row():
    state = ModsPresenter().page(facts(), scan())
    packages = rows(state)
    assert [(r.position, r.name) for r in packages] == [(1, "flora"), (2, "birds"), (3, "revive")]
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
    assert [t.text for t in flora.tags] == ["Clash · 1 file", "Outside the library"]
    assert flora.more.splitlines() == ["Shared · 3 profiles", "mod/flora"]
    revive = packages[2]
    assert [t.text for t in revive.tags] == ["Stays last"] and revive.locked
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
    revive = rows(ModsPresenter().page(facts(), scan()))[2]
    assert revive.status == "after 4 others"
    empty = rows(ModsPresenter().page(facts(empty={0: "empty"}, outside=(), shared={}), None))[0]
    assert empty.status.startswith("Empty for now")


def test_the_health_pill():
    p = ModsPresenter()
    assert p.page(facts(), None).health is None  # until the first scan
    assert p.page(facts(), scan()).health.__dict__ == {"text": "1 file clashes", "level": "danger"}
    calm = scan(overlaps={"conflicts": []}, health={"state": "stale", "packs": ["revive"]})
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


def test_infobars_two_at_once_and_a_closed_one_stays_closed():
    p = ModsPresenter()
    tool = SimpleNamespace(label="rebuild.json", package={"name": "Revive"})
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
    assert panel.stays_last.text == "flora, birds load after revive, which must stay last: they replace revive's files."
    assert panel.stays_last.can_fix
    assert [c.path for c in panel.clashes] == ["parts/a.partsbnd.dcx", "msg/b.msgbnd.dcx"]  # lost first
    assert panel.clashes[0].losers == "flora (replaced)" and panel.clashes[0].lost
    assert panel.clash_note == "2 files are shipped by two packages; 1 of them reach the game from one package only."
    assert [(r.name, r.why) for r in panel.refused] == [("gone.dll", "DLL missing")]
    calm = load_order.panel(scan(stay_last={"name": "revive", "late": [], "can_fix": False}, overlaps={}))
    assert calm.stays_last is not None and calm.stays_last.text == "revive loads last, as it must."
    assert calm.clash_note == "No two packages ship the same file."


def test_the_confirmations_words():
    p = ModsPresenter()
    plan = Removal("package", "flora", Path("C:/mods/mod/flora"), ("birds",), ("regulation.bin",), False)
    removal = p.removal(PROFILE, plan)
    assert removal.title == "Remove flora from the profile" and removal.option == ""
    assert removal.changes[1] == "The folder flora stays: birds still load from it"
    assert removal.changes[2].startswith("Its regulation.bin is still inside the merged mods")
    alone = p.removal(PROFILE, Removal("native", "x.dll", Path("C:/mods/natives/x"), (), (), True))
    assert alone.option == "Also move the folder x to the Recycle Bin"
    trim = p.trim([{"folder": Path("b4"), "size": 2 * 1048576}])
    assert trim.title == "Move 1 older rebuild backup to the Recycle Bin" and "The newest 3 stay" in trim.safety
    tool = SimpleNamespace(label="rebuild.json", package={"name": "Revive"}, describe=lambda: "python refresh.py")
    assert p.tool(tool).detail == "It comes with Revive and runs:\n\npython refresh.py"
    managed = p.delete_refusal(profile_mods.DELETE_MANAGED, "Nightreign Revive")
    assert managed is not None and managed.body == "Nightreign Revive is managed by its installer; delete it there."
    assert p.delete_refusal(None) is None
    assert len(p.delete_profile(PROFILE).changes) == 2
    assert p.delete_profile(PROFILE, "Nightreign Revive").changes[-1] == (
        "Nightreign Revive's shared files stay; Remove overhaul first to take them out too."
    )
    assert (
        p.holder(PROFILE, "bundle", ["revive"]).changes[-1]
        == "revive must load after it: that setting is taken out too"
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
