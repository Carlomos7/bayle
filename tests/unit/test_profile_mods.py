"""services/profile_mods.py: the Mods page's decisions below the UI (what a removal touches and the undo record it
leaves, taking out an entry for a folder of mods, the install's undo record, the keep-3 rule, the rebuild tool's
permission, and the rules for deleting a profile and changing its me3 options)."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from roundtable_souls.game import catalog as games
from roundtable_souls.mods import profile_edit
from roundtable_souls.mods import rebuild as mod_merge
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.services import profile_mods as pm
from roundtable_souls.services.mods import profile_entries
from support import er

PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    "[[packages]]\nid = \"bundle\"\npath = 'mod'\n\n"
    '[[packages]]\nid = "needs-bundle"\npath = \'mod/needs\'\nload_after = [{ id = "bundle" }]\n\n'
    "[[natives]]\npath = 'natives/SeamlessCoop/ersc.dll'\n\n"
    "[[natives]]\npath = 'natives/SeamlessCoop/second.dll'\n\n"
    "[[natives]]\npath = 'natives/other/other.dll'\n"
)


@pytest.fixture
def profile(tmp_path) -> Path:
    p = tmp_path / "my.me3"
    p.write_text(PROFILE, encoding="utf-8")
    for folder in ("mod/flora/parts", "mod/needs/parts", "natives/SeamlessCoop", "natives/other"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
    for dll in ("natives/SeamlessCoop/ersc.dll", "natives/SeamlessCoop/second.dll", "natives/other/other.dll"):
        (tmp_path / dll).write_bytes(b"d")
    return p


def entry(profile, name):
    return next(e for e in profile_entries(profile) if e["name"] == name)


@pytest.fixture
def undo_records(monkeypatch):
    got = []
    monkeypatch.setattr(run_logging, "set_undo", got.append)
    return got


def test_a_folder_other_entries_load_from_stays_and_cannot_go_to_the_bin(profile):
    plan = pm.removal(profile, entry(profile, "ersc.dll"), loc=er())
    assert plan.folder == profile.parent / "natives" / "SeamlessCoop"
    assert plan.users == ("second.dll",) and not plan.can_recycle
    alone = pm.removal(profile, entry(profile, "other.dll"), loc=er())
    assert alone.users == () and alone.can_recycle and alone.merged == ()


def test_removing_leaves_the_undo_record_activity_offers(profile, undo_records):
    plan = pm.removal(profile, entry(profile, "other.dll"), loc=er())
    lines = []
    out = pm.remove_entry(
        profile, entry(profile, "other.dll")["index"], plan, delete_folder=False, loc=er(), log=lines.append
    )
    assert "other.dll" not in [e["name"] for e in profile_entries(profile)]
    assert out["removed_folder"] is False and (profile.parent / "natives" / "other").is_dir()
    [record] = undo_records
    assert record["type"] == "remove" and record["name"] == "other.dll" and record["profile"] == str(profile)
    assert record["entry_text"] and record["merged"] is False
    assert lines == ["done: removed other.dll"]


def test_the_merged_files_come_only_for_an_elden_ring_package(profile, monkeypatch):
    monkeypatch.setattr(mod_merge, "is_elden_ring", lambda p: True)
    monkeypatch.setattr(pm.mod_overview, "merged_from", lambda p, name, scan, loc: ["regulation.bin"])
    assert pm.merged_from(profile, entry(profile, "flora"), loc=er()) == ["regulation.bin"]
    assert pm.merged_from(profile, entry(profile, "other.dll"), loc=er()) == []
    monkeypatch.setattr(pm.mod_overview, "merged_from", lambda *a, **k: (_ for _ in ()).throw(OSError("gone")))
    assert pm.merged_from(profile, entry(profile, "flora"), loc=er()) == []


def test_taking_out_an_entry_for_a_folder_of_mods_takes_the_dependency_on_it_too(profile):
    holder = entry(profile, "bundle")
    needs = pm.holder_dependents(profile, holder)
    assert needs == ["needs-bundle"]
    pm.remove_holder(profile, holder["index"], holder, needs, loc=er())
    names = [e["name"] for e in profile_entries(profile)]
    assert "bundle" not in names and "needs-bundle" in names
    assert entry(profile, "needs-bundle").get("load_after") in (None, [])
    assert (profile.parent / "mod" / "flora").is_dir()  # the folder and its mods stay


def test_an_install_leaves_install_or_update_as_its_undo_record(profile, undo_records, monkeypatch):
    monkeypatch.setattr(pm, "install_mod", lambda prof, plan, **k: {"update": True, "operation": "op-1"})
    out = pm.install_and_record(profile, {"name": "Flora", "exists": True, "merge": True}, loc=er())
    assert out["operation"] == "op-1"
    assert undo_records == [
        {"type": "update", "profile": str(profile), "name": "Flora", "operation": "op-1", "rebuild": True}
    ]


def test_the_newest_three_rebuild_backups_stay(profile, monkeypatch):
    backups = [{"folder": Path(f"b{i}"), "size": 1} for i in range(5)]
    monkeypatch.setattr(mod_merge, "tool_backups", lambda p: backups)
    assert pm.tool_backups_to_trim(profile) == backups[3:]
    kept = []
    monkeypatch.setattr(mod_merge, "trim_tool_backups", lambda p, keep: kept.append(keep) or backups[keep:])
    assert pm.trim_tool_backups(profile) == backups[3:] and kept == [pm.KEEP_TOOL_BACKUPS] == [3]


class Tool:
    label = "rebuild.json"

    def __init__(self, problem=""):
        self._problem = problem

    def problem(self):
        return self._problem


def test_a_rebuild_tool_is_offered_only_when_it_can_run_and_is_not_allowed_yet(profile, monkeypatch):
    allowed: set = set()
    monkeypatch.setattr(mod_merge, "approved", lambda tool: tool in allowed)
    monkeypatch.setattr(mod_merge, "approve", allowed.add)
    tool = Tool()
    monkeypatch.setattr(mod_merge, "find_backend", lambda p, **k: tool)
    assert pm.tool_to_offer(profile, games.ELDEN_RING, loc=er()) is tool
    assert pm.tool_to_offer(profile, games.NIGHTREIGN, loc=er()) is None
    assert not pm.tool_state(profile, loc=er()).ready
    pm.allow_tool(tool)
    assert pm.tool_to_offer(profile, games.ELDEN_RING, loc=er()) is None and pm.tool_state(profile, loc=er()).ready
    broken = Tool("its program is missing")
    monkeypatch.setattr(mod_merge, "find_backend", lambda p, **k: broken)
    state = pm.tool_state(profile, loc=er())
    assert state.problem == "its program is missing" and not state.ready
    assert pm.tool_to_offer(profile, games.ELDEN_RING, loc=er()) is None
    monkeypatch.setattr(mod_merge, "find_backend", lambda p, **k: None)
    assert pm.tool_state(profile, loc=er()).ready  # the launcher's own combine needs no permission


def test_why_a_profile_cannot_be_deleted_now(profile):
    def setup(kind="me3", path=profile):
        return SimpleNamespace(profile=str(path), kind=kind)

    assert pm.delete_refusal(None, False) == pm.DELETE_NO_PROFILE
    assert pm.delete_refusal(setup(path=profile.parent / "gone.me3"), False) == pm.DELETE_NO_PROFILE
    assert pm.delete_refusal(setup(kind="revive"), False) == pm.DELETE_MANAGED
    assert pm.delete_refusal(setup(), True) == pm.DELETE_BUSY
    assert pm.delete_refusal(setup(), False) is None


def test_me3_option_rules():
    assert pm.setting_needs_confirmation("start_online", True)
    assert not pm.setting_needs_confirmation("start_online", False)
    assert not pm.setting_needs_confirmation("mem_patch", True)
    assert pm.heap_size_applies({}) and pm.heap_size_applies({"mem_patch": True})
    assert not pm.heap_size_applies({"mem_patch": False})


def test_the_service_does_not_touch_profile_edit_rules_it_reuses():
    # the entry reference a holder is matched by is the profile editor's own
    assert pm.profile_edit is profile_edit


def test_the_page_facts_read_in_one_pass(profile):
    from roundtable_souls.config.settings import LauncherSettings

    (profile.parent / "natives" / "other" / "other.dll").unlink()  # its DLL went missing
    (profile.parent / "mod" / "flora" / "parts").rmdir()  # flora's folder is empty now
    facts = pm.page_facts(profile, loc=er(), settings=LauncherSettings())
    by_name = {e["name"]: e["index"] for e in facts.entries}
    assert facts.error == ""
    assert facts.loads_nothing == (by_name["bundle"],)  # mod/ only holds other mods
    assert by_name["other.dll"] in facts.missing
    assert facts.empty.get(by_name["flora"]) == "empty"  # an empty package folder: "Empty for now"
    assert set(facts.display["native"]) == {by_name["ersc.dll"], by_name["second.dll"], by_name["other.dll"]}
    assert facts.outside == () and facts.shared == {}  # not a library profile


def test_unreadable_page_facts_say_why(tmp_path):
    from roundtable_souls.config.settings import LauncherSettings

    facts = pm.page_facts(tmp_path / "gone.me3", loc=er(), settings=LauncherSettings())
    assert facts.error and facts.entries == ()
