"""The overhaul operations of the Mods page (install from a download, remove, take over, installer leftovers) through
Session.run / answer, with the overhaul services faked: no Qt, no window, nothing installed."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from bayle.mods.overhaul_takeover import EntryChoice
from bayle.services import mods as mod_service
from bayle.services.errors import OperationError
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm, Refusal
from support import er, mods_profile


def make(**jobs_kw) -> Session:
    return Session(
        JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs_kw), plans=PlanStore(), locations=er
    )


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


class Effect:
    entry = "ersc.dll"


def preview(ok=True, lines=("toy.me3 loses Toy's entries",), asked=(Effect(),), refusals=()):
    return SimpleNamespace(
        ok=ok, lines=list(lines), asked=list(asked), refusals=list(refusals), label="Toy", update=False, notes=[]
    )


@pytest.fixture
def fakes(monkeypatch):
    calls: dict = {"previews": [], "removed": [], "installed": []}
    state = {"overhaul": {"label": "Toy", "short_label": "Toy", "legacy": True, "takeover": True}}

    def removal(profile, *, loc, revert_asked=False, legacy_choices=()):
        calls["previews"].append((revert_asked, list(legacy_choices)))
        return preview(ok=not (revert_asked and state.get("refuse_switch_back")))

    monkeypatch.setattr(mod_service, "profile_overhaul", lambda p, loc: state["overhaul"])
    monkeypatch.setattr(
        mod_service, "legacy_overhaul_choices", lambda p, loc: [("start_online: back to on", "E1"), ("x", "E2")]
    )
    monkeypatch.setattr(mod_service, "preview_overhaul_removal", removal)
    monkeypatch.setattr(mod_service, "remove_overhaul", lambda p: calls["removed"].append(p))
    monkeypatch.setattr(mod_service, "preview_overhaul_install", lambda p, f, loc: preview(asked=()))
    monkeypatch.setattr(mod_service, "install_overhaul", lambda p, loc: calls["installed"].append(p) or {})
    return calls, state


def test_what_an_installer_changed_is_offered_unticked_and_a_plain_overhaul_offers_nothing(profile, fakes):
    _calls, state = fakes
    got = make().run("mods.overhaul_remove_choices", {"profile": str(profile)})
    assert got.label == "Toy" and got.prompt["kind"] == "pick" and got.prompt["ticked"] == []
    assert (
        got.prompt["rows"] == ["start_online: back to on", "x"]
        and got.prompt["title"] == "Put back what Toy's installer changed?"
    )
    state["overhaul"] = {"label": "Toy", "short_label": "Toy", "legacy": False}
    assert make().run("mods.overhaul_remove_choices", {"profile": str(profile)}).prompt is None
    state["overhaul"] = None
    with pytest.raises(OperationError) as e:
        make().run("mods.overhaul_remove_choices", {"profile": str(profile)})
    assert e.value.code == "no_overhaul"


def test_removing_previews_with_the_ticked_changes_and_the_switch_back_is_previewed_again(profile, fakes):
    calls, _state = fakes
    s = make()
    plan = s.run(
        "mods.overhaul_remove", {"profile": str(profile), "chosen": [0, 7]}
    )  # an index out of range is ignored
    assert isinstance(plan.words, Confirm) and plan.words.title == "Remove Toy from main.me3"
    assert plan.words.option == "Also switch ersc.dll back off, as it was before the install"
    assert calls["previews"] == [(False, ["E1"])] and calls["removed"] == []
    snap = s.jobs.get(s.answer(plan.id, {"ok": True, "option": True}))
    assert (snap.state, snap.title) == ("done", "Removing Toy...")
    assert calls["previews"][-1] == (True, ["E1"]) and len(calls["removed"]) == 1


def test_a_switch_back_the_overhaul_refuses_is_said_and_removes_nothing(profile, fakes):
    calls, state = fakes
    state["refuse_switch_back"] = True
    s = make()
    plan = s.run("mods.overhaul_remove", {"profile": str(profile)})
    with pytest.raises(OperationError) as e:
        s.answer(plan.id, {"ok": True, "option": True})
    assert e.value.code == "overhaul_not_removed" and calls["removed"] == []


def test_a_removal_that_does_not_preview_is_a_refusal(profile, fakes, monkeypatch):
    def boom(*a, **k):
        raise ValueError("not an overhaul I know")

    monkeypatch.setattr(mod_service, "preview_overhaul_removal", boom)
    got = make().run("mods.overhaul_remove", {"profile": str(profile)})
    assert isinstance(got, Refusal) and got.title == "Can't remove Toy" and got.body == "not an overhaul I know"


def test_take_over_ticks_the_entries_the_installer_copied_and_runs_one_job(profile, fakes, monkeypatch):
    calls, state = fakes
    choices = [EntryChoice("native", "a.dll", False), EntryChoice("native", "toy.dll", True)]
    monkeypatch.setattr(mod_service, "take_over_choices", lambda p, loc: choices)
    taken = []
    monkeypatch.setattr(
        mod_service,
        "preview_take_over",
        lambda p, *, loc, chosen=(), revert_asked=False: taken.append(list(chosen)) or preview(),
    )
    s = make()
    offer = s.run("mods.takeover_choices", {"profile": str(profile)})
    assert offer.prompt["ticked"] == [1] and "copied by the installer" in offer.prompt["rows"][1]
    plan = s.run("mods.takeover", {"profile": str(profile), "chosen": [1]})
    assert plan.words.title == "Take over Toy in main.me3" and taken == [[choices[1]]]
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert (snap.state, snap.title) == ("done", "Taking over Toy...") and len(calls["removed"]) == 1
    state["overhaul"] = {"label": "Toy", "short_label": "Toy", "legacy": True, "takeover": False}
    with pytest.raises(OperationError) as e:
        s.run("mods.takeover_choices", {"profile": str(profile)})
    assert e.value.code == "no_takeover"


def test_installing_an_overhaul_previews_asks_and_runs_a_logged_job(profile, fakes, tmp_path):
    calls, _state = fakes
    s = make()
    plan = s.run("mods.overhaul_install", {"profile": str(profile), "folder": str(tmp_path / "dl")})
    assert plan.words.title == "Install Toy in main.me3" and calls["installed"] == []
    snap = s.jobs.get(s.answer(plan.id, {"ok": True}))
    assert (snap.state, snap.title) == ("done", "Installing Toy...") and len(calls["installed"]) == 1


def test_a_download_that_is_not_an_overhaul_is_a_refusal_naming_the_folder(profile, fakes, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise ValueError("no overhaul in here")

    monkeypatch.setattr(mod_service, "preview_overhaul_install", boom)
    got = make().run("mods.overhaul_install", {"profile": str(profile), "folder": str(tmp_path / "dl")})
    assert isinstance(got, Refusal) and got.title == "Can't install from dl" and got.body == "no overhaul in here"


def test_installer_leftovers_are_listed_with_their_backups_asked_last_and_cleaned_by_index(profile, monkeypatch):
    left = [
        SimpleNamespace(path=Path("C:/x/Old Mod"), label="Old Mod (3 MB)", backups=False),
        SimpleNamespace(path=Path("C:/x/Old Backups"), label="Old Backups (2 MB)", backups=True),
    ]
    monkeypatch.setattr(mod_service, "overhaul_leftovers", lambda p, loc: left)
    removed: list = []
    monkeypatch.setattr(mod_service, "remove_overhaul_leftovers", lambda paths: removed.append(list(paths)) or [])
    s = make()
    got = s.run("mods.leftovers", {"profile": str(profile)})
    assert got.folders["rows"] == ["Old Mod (3 MB)"] and got.folders["none"] == "Next"  # backups are asked next
    assert [b["title"] for b in got.backups] == ["Also remove Old Backups?"]
    with pytest.raises(OperationError) as e:
        s.run("mods.leftovers_clean", {"profile": str(profile)})
    assert e.value.code == "nothing_chosen"
    snap = s.jobs.get(s.run("mods.leftovers_clean", {"profile": str(profile), "folders": [0], "backups": [0]}))
    assert (snap.state, snap.title) == ("done", "Moving leftovers to the Recycle Bin...")
    assert removed == [[Path("C:/x/Old Mod"), Path("C:/x/Old Backups")]]
