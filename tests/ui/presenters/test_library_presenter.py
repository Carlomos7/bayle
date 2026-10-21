"""The Library's words on the Mods page without Qt: the Shared and Separate tags, the disk hint over a gigabyte,
the confirmations, and the install dialog's choices; every string through tr()."""

from pathlib import Path

from test_mods_presenter import facts

from roundtable_souls.mods import shared_mods
from roundtable_souls.ui.pages.mods.install import InstallDraft
from roundtable_souls.ui.pages.mods.presenter import ModsPresenter

P = ModsPresenter()


def rows(**over):
    state = P.page(facts(**over))
    return {r.name: r for r in state.groups[0].rows}


def test_shared_rows_say_how_many_profiles_and_that_the_files_are_read_only():
    r = rows(shared={0: 3, 2: 1}, can_share=(3,), library_used=True)
    assert r["flora"].shared == 3 and r["flora"].tags[0].text == "Shared · 3 profiles"
    assert "read-only" in r["flora"].tags[0].tip and "Use a separate copy" in r["flora"].tags[0].tip
    assert r["birds"].tags[0].text == "Shared · 1 profile"
    assert r["example"].can_share and r["example"].tags[0].text == "Separate"


def test_nobody_who_shares_nothing_sees_a_separate_tag():
    r = rows(can_share=(0, 1), library_used=False)
    assert r["flora"].can_share and all(t.text != "Separate" for t in r["flora"].tags)


def test_the_hint_appears_only_over_a_gigabyte():
    gb = shared_mods.HINT_BYTES
    assert [n.key for n in P.page(facts(), duplicated=(2, gb)).notices] == []
    notice = P.page(facts(), duplicated=(2, gb + 1)).notices[0]
    assert notice.key == "library-hint" and notice.action == "Shared mods..."
    assert notice.text == "2 mods are in several profiles (1.0 GB). Save space by sharing"
    one = P.hint_text(1, 3 * gb // 2)
    assert one == "1 mod is in several profiles (1.5 GB). Save space by sharing"


def test_the_confirmations_use_the_agreed_words():
    assert P.share_confirm(["grass"]).title == "Share grass"
    assert "Undo" in P.share_confirm(["grass"]).safety
    sep = P.separate_confirm("grass", 5 * 1048576)
    assert sep.apply == "Use a separate copy" and "5.0 MB" in sep.changes[0]
    clean = P.clean_confirm(2, 3 * 1048576)
    assert "2 versions" in clean.changes[0] and clean.apply == "Remove"
    dup = P.duplicate_confirm("a")
    assert dup.option.startswith("Share the game-file mods") and dup.option_checked is False
    assert P.use_row("b", True, False).startswith("b (has its own copy")
    assert P.use_row("c", False, False) == "c"


def test_the_library_rows_show_the_date_and_label_but_never_the_id():
    version = shared_mods.Version("0123456789abcdef", "2026-10-21", "v2", 2048)
    info = [
        shared_mods.ModInfo(
            shared_mods.SharedMod("grass", "Grass"), [shared_mods.VersionInfo(version, ["a", "b"], False)]
        )
    ]
    out = P.library(info)
    assert out[0]["versions"][0]["title"] == "Installed 2026-10-21  ·  v2"
    assert out[0]["versions"][0]["usedBy"] == "Used by a, b" and "0123456789abcdef" not in str(out)


def install_plan(**library):
    return {
        "kind": "package",
        "name": "grass",
        "id": "grass",
        "dest": Path("p/grass"),
        "library": library,
        "contents": [],
        "size": 1,
        "assets": ["parts"],
    }


def test_the_install_choices_and_their_defaults():
    d = InstallDraft(install_plan(shared={"index": 0, "name": "Grass", "profiles": 3}), Path("p/a.me3"))
    v = d.view()["library"]
    assert [o["text"] for o in v["options"]] == ["Update here", "Update everywhere"] and v["choice"] == "here"
    d.library_choice = "everywhere"
    assert d.finish()["library_choice"] == "everywhere"
    one = InstallDraft(install_plan(shared={"index": 0, "name": "Grass", "profiles": 1}), Path("p/a.me3")).view()
    assert [o["key"] for o in one["library"]["options"]] == ["here"]
    plain = InstallDraft(install_plan(), Path("p/a.me3"))
    assert plain.view()["library"] == {"shown": False}


def test_a_shared_update_with_parameters_is_refused_with_a_reason():
    plan = install_plan(shared={"index": 0, "name": "Grass", "profiles": 2}, blocked=True)
    d = InstallDraft(plan, Path("p/a.me3"))
    view = d.view()
    assert not d.can_install() and view["noteLevel"] == "error" and "separate copy" in view["note"]
    assert view["library"] == {"shown": False}


def test_the_feature_is_called_shared_mods_in_the_ui():
    words = P.words()
    assert words["library"] == "Shared mods..." and words["libraryTitle"] == "Shared mods"
    shown = " ".join(str(v) for k, v in words.items() if k.startswith("library") or k in ("share", "useInOthers"))
    assert "Library" not in shown and "opt-in" not in shown.lower()
    assert "Library" not in " ".join(P.share_confirm(["a"]).changes)
