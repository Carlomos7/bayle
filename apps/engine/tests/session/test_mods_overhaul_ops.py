"""The overhaul operations of the Mods page (install from a download, remove, take over, installer leftovers) through
Session.run on the real ModInstallService, with the overhaul services faked: no Qt, no window, nothing installed."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from bayle.errors import OperationError
from bayle.modules.mods import service as mod_service
from bayle.modules.mods.mod_install import ModInstallService
from bayle.modules.mods.overhaul_takeover import EntryChoice
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import ServiceCalls, er, mods_profile


def make(**jobs_kw) -> ServiceCalls:
    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs_kw)
    return ServiceCalls(jobs, mod_install=ModInstallService(jobs, er))


@pytest.fixture
def profile(tmp_path):
    return mods_profile(tmp_path / "p")


class Effect:
    entry = "ersc.dll"


def preview(ok=True, lines=("toy.me3 loses Toy's entries",), asked=(Effect(),), refusals=()):
    return SimpleNamespace(
        ok=ok, lines=list(lines), asked=list(asked), refusals=list(refusals), label="Toy", update=False, notes=[]
    )


def refused(session, name, params) -> OperationError:
    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


@pytest.fixture
def fakes(monkeypatch):
    calls: dict = {"previews": [], "removed": [], "installed": []}
    state = {"overhaul": {"label": "Toy", "short_label": "Toy", "legacy": True, "takeover": True}}

    def removal(profile, *, loc, revert_asked=False, legacy_choices=()):
        calls["previews"].append((revert_asked, list(legacy_choices)))
        refusing = revert_asked and state.get("refuse_switch_back")
        return preview(ok=not refusing, refusals=("cannot switch back",) if refusing else ())

    monkeypatch.setattr(mod_service, "profile_overhaul", lambda p, loc: state["overhaul"])
    monkeypatch.setattr(
        mod_service, "legacy_overhaul_choices", lambda p, loc: [("start_online: back to on", "E1"), ("x", "E2")]
    )
    monkeypatch.setattr(mod_service, "preview_overhaul_removal", removal)
    monkeypatch.setattr(mod_service, "remove_overhaul", lambda p: calls["removed"].append(p))
    monkeypatch.setattr(mod_service, "preview_overhaul_install", lambda p, f, loc: preview(asked=()))
    monkeypatch.setattr(mod_service, "install_overhaul", lambda p, loc: calls["installed"].append(p) or {})
    return calls, state


def test_what_an_installer_changed_is_offered_and_a_plain_overhaul_offers_nothing(profile, fakes):
    _calls, state = fakes
    got = make().run("mods.overhaul_remove_choices", {"profile": str(profile)})
    assert got.label == "Toy" and got.rows == ["start_online: back to on", "x"] and got.ticked == []
    state["overhaul"] = {"label": "Toy", "short_label": "Toy", "legacy": False}
    assert make().run("mods.overhaul_remove_choices", {"profile": str(profile)}).rows == []
    state["overhaul"] = None
    assert refused(make(), "mods.overhaul_remove_choices", {"profile": str(profile)}).code == "no_overhaul"


def test_removing_is_checked_with_the_ticked_changes_and_started_with_the_stamp(profile, fakes):
    calls, _state = fakes
    s = make()
    plan = s.run("mods.check_overhaul_remove", {"profile": str(profile), "chosen": [0, 7]})  # 7: out of range, ignored
    assert plan.label == "Toy" and plan.asked == ["ersc.dll"] and plan.refusals == []
    assert plan.lines == ["toy.me3 loses Toy's entries"] and plan.stamp
    assert calls["previews"] == [(False, ["E1"])] and calls["removed"] == []
    start = {"profile": str(profile), "chosen": [0], "revert": True, "expect": list(plan.stamp)}
    snap = s.jobs.get(s.run("mods.overhaul_remove", start).job_id)
    assert (snap.state, snap.title) == ("done", "Removing Toy...")
    assert calls["previews"][-1] == (True, ["E1"]) and len(calls["removed"]) == 1


def test_a_stale_removal_or_a_switch_back_the_overhaul_refuses_removes_nothing(profile, fakes):
    calls, state = fakes
    s = make()
    plan = s.run("mods.check_overhaul_remove", {"profile": str(profile)})
    profile.write_bytes(profile.read_bytes() + b"\n# edited\n")
    start = {"profile": str(profile), "expect": list(plan.stamp)}
    assert refused(s, "mods.overhaul_remove", start).code == "stale"
    state["refuse_switch_back"] = True
    again = refused(s, "mods.overhaul_remove", {**start, "revert": True})
    assert again.code == "cannot_remove" and again.details["refusals"] == ["cannot switch back"]
    assert calls["removed"] == []


def test_a_removal_that_does_not_preview_is_a_refusal_with_a_code(profile, fakes, monkeypatch):
    def boom(*a, **k):
        raise ValueError("not an overhaul I know")

    monkeypatch.setattr(mod_service, "preview_overhaul_removal", boom)
    got = refused(make(), "mods.check_overhaul_remove", {"profile": str(profile)})
    assert got.code == "cannot_remove" and got.message == "not an overhaul I know" and got.details["label"] == "Toy"


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
    assert offer.ticked == [1] and "copied by the installer" in offer.rows[1]
    plan = s.run("mods.check_takeover", {"profile": str(profile), "chosen": [1]})
    assert plan.label == "Toy" and taken == [[choices[1]]]
    snap = s.jobs.get(
        s.run("mods.takeover", {"profile": str(profile), "chosen": [1], "expect": list(plan.stamp)}).job_id
    )
    assert (snap.state, snap.title) == ("done", "Taking over Toy...") and len(calls["removed"]) == 1
    state["overhaul"] = {"label": "Toy", "short_label": "Toy", "legacy": True, "takeover": False}
    assert refused(s, "mods.takeover_choices", {"profile": str(profile)}).code == "no_takeover"


def test_installing_an_overhaul_is_checked_then_started_as_a_logged_job(profile, fakes, tmp_path):
    calls, _state = fakes
    folder = tmp_path / "dl"
    folder.mkdir()
    s = make()
    plan = s.run("mods.check_overhaul_install", {"profile": str(profile), "folder": str(folder)})
    assert plan.label == "Toy" and plan.update is False and calls["installed"] == []
    start = {"profile": str(profile), "folder": str(folder), "expect": list(plan.stamp)}
    snap = s.jobs.get(s.run("mods.overhaul_install", start).job_id)
    assert (snap.state, snap.title) == ("done", "Installing Toy...") and len(calls["installed"]) == 1
    assert refused(s, "mods.overhaul_install", {**start, "folder": str(tmp_path / "gone")}).code == "not_found"


def test_a_download_that_is_not_an_overhaul_is_a_refusal_naming_the_folder(profile, fakes, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise ValueError("no overhaul in here")

    folder = tmp_path / "dl"
    folder.mkdir()
    monkeypatch.setattr(mod_service, "preview_overhaul_install", boom)
    got = refused(make(), "mods.check_overhaul_install", {"profile": str(profile), "folder": str(folder)})
    assert got.code == "unreadable" and got.message == "no overhaul in here" and got.details["name"] == "dl"


def test_installer_leftovers_are_listed_with_their_backups_apart_and_only_those_are_cleaned(profile, monkeypatch):
    left = [
        SimpleNamespace(path=Path("C:/x/Old Mod"), label="Old Mod (3 MB)", size=3, backups=False),
        SimpleNamespace(path=Path("C:/x/Old Backups"), label="Old Backups (2 MB)", size=2, backups=True),
    ]
    monkeypatch.setattr(mod_service, "overhaul_leftovers", lambda p, loc: left)
    removed: list = []
    monkeypatch.setattr(mod_service, "remove_overhaul_leftovers", lambda paths: removed.append(list(paths)) or [])
    s = make()
    got = s.run("mods.leftovers", {"profile": str(profile)})
    assert [x.label for x in got.folders] == ["Old Mod (3 MB)"] and [x.size for x in got.backups] == [2]
    assert refused(s, "mods.leftovers_clean", {"profile": str(profile), "paths": []}).code == "nothing_chosen"
    assert refused(s, "mods.leftovers_clean", {"profile": str(profile), "paths": ["C:/Windows"]}).code == "not_found"
    assert removed == []
    paths = [got.folders[0].path, got.backups[0].path]
    snap = s.jobs.get(s.run("mods.leftovers_clean", {"profile": str(profile), "paths": paths}).job_id)
    assert (snap.state, snap.title) == ("done", "Moving leftovers to the Recycle Bin...")
    assert removed == [[Path("C:/x/Old Mod"), Path("C:/x/Old Backups")]]
