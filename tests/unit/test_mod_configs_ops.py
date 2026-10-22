"""The Mod Configs operations through Session.run / snapshot / answer: no Qt, no window."""

from pathlib import Path

import pytest
from test_overhaul_install import World, mixed_mod, set_up

from bayle.mods import configs
from bayle.services import mod_configs
from bayle.services.errors import OperationError
from bayle.services.settings import load_settings
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.views.common import Confirm


def inline(run, name=None):
    run()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def make(world, **jobs_kw):
    return Session(JobManager(EventBus(), spawn=inline, **jobs_kw), plans=PlanStore(), locations=lambda: world.loc)


def ini_of(world) -> Path:
    ini = world.base / "natives/SeamlessCoop/ersc_settings.ini"
    ini.write_text("[PASSWORD]\ncooppassword = room\n[GAMEPLAY]\nallow_invaders = 1\n", encoding="utf-8")
    return ini


def tree_of(root: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def test_the_snapshot_lists_the_mods_with_settings_and_writes_nothing(world):
    ini = ini_of(world)
    s = make(world)
    before = tree_of(world.tmp)
    state = s.snapshot("mod_configs", profile=str(world.profile))
    assert state.profile == str(world.profile)
    assert [n.kind for n in state.nodes][0] == mod_configs.SEAMLESS
    assert state.nodes[0].files[0].path == ini
    assert tree_of(world.tmp) == before
    assert s.snapshot("mod_configs").nodes == ()  # no profile: nothing
    assert s.snapshot("mod_configs", profile=str(world.base / "gone.me3")).profile == ""


def test_open_reads_a_file_and_the_stamp_tells_a_change(world):
    ini = ini_of(world)
    s = make(world)
    got = s.run("mod_configs.open", {"path": str(ini), "seamless": True, "profile": str(world.profile)})
    assert got.text.startswith("[PASSWORD]") and got.seamless is not None and got.seamless.password == "room"
    assert got.stamp == s.run("mod_configs.stamp", {"path": str(ini)}).stamp
    ini.write_text(got.text + "x = 1\n", encoding="utf-8")
    assert s.run("mod_configs.stamp", {"path": str(ini)}).stamp != got.stamp
    assert s.run("mod_configs.stamp", {"path": str(world.base / "none.ini")}).stamp is None
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.open", {"path": str(world.base / "none.ini")})
    assert e.value.code == "unreadable"


def test_save_writes_by_kind_and_refuses_a_file_that_changed(world):
    ini = ini_of(world)
    other = world.base / "natives/SeamlessCoop/other.ini"
    other.write_bytes(b"[a]\r\nb = 1\r\nc = 2\r\n")
    s = make(world)
    read = s.run("mod_configs.open", {"path": str(other)})
    done = s.run(
        "mod_configs.save",
        {
            "path": str(other),
            "expect": read.sha,
            "kind": "values",
            "edits": [{"section": "a", "key": "b", "value": "9"}],
        },
    )
    assert (done.saved, done.missing) == (1, ()) and other.read_bytes() == b"[a]\r\nb = 9\r\nc = 2\r\n"
    with pytest.raises(OperationError) as e:  # read before the change above
        s.run("mod_configs.save", {"path": str(other), "expect": read.sha, "kind": "text", "text": "x"})
    assert e.value.code == "file_changed"
    fresh = s.run("mod_configs.open", {"path": str(other)})
    s.run("mod_configs.save", {"path": str(other), "expect": fresh.sha, "kind": "text", "text": "[a]\nb = 3\n"})
    assert configs.read(other)["text"] == "[a]\nb = 3\n"
    with pytest.raises(OperationError) as e:  # a setting the file does not have
        s.run(
            "mod_configs.save",
            {"path": str(other), "expect": s.run("mod_configs.open", {"path": str(other)}).sha, "kind": "values",
             "edits": [{"section": "a", "key": "zzz", "value": "1"}]},
        )  # fmt: skip
    assert e.value.code == "not_saved"
    done = s.run(
        "mod_configs.save",
        {"path": str(ini), "expect": "", "kind": "seamless",
         "edits": [{"key": "cooppassword", "value": "new"}, {"key": "nope", "value": "1"}]},
    )  # fmt: skip
    assert (done.saved, done.missing) == (1, ("nope",)) and "cooppassword = new" in ini.read_text(encoding="utf-8")
    with pytest.raises(OperationError) as e:
        s.run(
            "mod_configs.save",
            {"path": str(ini), "expect": "", "kind": "seamless", "edits": [{"key": "cooppassword", "value": " "}]},
        )
    assert e.value.code == "password_empty"


def test_attach_and_detach_keep_the_tie_in_the_launchers_settings(world):
    dll = world.base / "natives/SeamlessCoop/ersc.dll"
    extra = world.tmp / "extra.txt"
    extra.write_text("x", encoding="utf-8")
    s = make(world)
    s.run("mod_configs.attach", {"target": str(dll), "file": str(extra)})
    assert configs.key_for(extra) in [
        configs.key_for(Path(f)) for v in load_settings().native_configs.values() for f in v
    ]
    s.run("mod_configs.detach", {"target": str(dll), "file": str(extra)})
    assert load_settings().native_configs == {}


def test_sharing_settings_gives_and_takes_text_and_asks_before_writing(world):
    ini = ini_of(world)
    s = make(world)
    text = s.run("mod_configs.share", {"ini": str(ini)}).text
    assert "cooppassword = room" in text
    out = world.tmp / "friend.ini"
    s.run("mod_configs.export_share", {"ini": str(ini), "to": str(out)})
    assert out.read_text(encoding="utf-8") == text
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.paste", {"ini": str(ini), "text": "nothing like settings"})
    assert e.value.code == "not_settings"
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.paste", {"ini": str(ini), "text": text})
    assert e.value.code == "nothing_to_change"
    before = ini.read_bytes()
    plan = s.run(
        "mod_configs.paste", {"ini": str(ini), "text": "cooppassword = new\nallow_invaders = 0\nmade_up = 1\n"}
    )
    assert isinstance(plan.words, Confirm) and len(plan.words.changes) == 2
    assert ini.read_bytes() == before  # nothing before the answer
    s.answer(plan.id, {"ok": True})
    now = ini.read_text(encoding="utf-8")
    assert "cooppassword = new" in now and "allow_invaders = 0" in now
    plan = s.run("mod_configs.paste", {"ini": str(ini), "text": "cooppassword = other\n"})
    ini.write_text(now + "\n", encoding="utf-8")  # changed since the question
    with pytest.raises(OperationError) as e:
        s.answer(plan.id, {"ok": True})
    assert e.value.code == "plan_stale"
    plan = s.run("mod_configs.paste", {"ini": str(ini), "text": "cooppassword = \n"})
    with pytest.raises(OperationError) as e:
        s.answer(plan.id, {"ok": True})
    assert e.value.code == "password_empty"


def test_the_setup_form_patches_are_typed():
    values = {
        "natives": [{"file": "a.dll", "load_early": False, "after_others": True, "initializer": None}],
        "files": {"x.bin": "keep"},
        "tables": {},
        "health": {"log": "", "fail": "", "ok": ""},
    }
    for key, value in (("early:a.dll", "true"), ("after:a.dll", "false"), ("init:a.dll", " Boot "), ("table:t.json", "T"),
                       ("target:x.bin", " mod/x.bin "), ("health:fail", "bad")):  # fmt: skip
        patch = mod_configs.FormPatch.of(key, value)
        assert patch is not None and mod_configs.patch_values(values, patch)
    assert values["natives"][0] == {"file": "a.dll", "load_early": True, "after_others": False, "initializer": "Boot"}
    assert values["tables"] == {"t.json": "T"} and values["health"]["fail"] == "bad" and values["health_touched"]
    assert values["files"]["x.bin"] == "place:mod/x.bin"
    assert mod_configs.FormPatch.of("nonsense:a", "1") is None
    assert not mod_configs.patch_values(values, mod_configs.FormPatch("early", "missing.dll", "true"))


def _form(values) -> dict:
    return {
        "natives": values["natives"],
        "files": values["files"],
        "tables": values["tables"],
        "health": values["health"] if values.get("health_touched") else None,
    }


def test_saving_the_setup_then_applying_it_is_one_job_with_one_undo(world):
    _folder, toml, _out = set_up(world)
    s = make(world)
    profile = str(world.profile)
    form = s.run("mod_configs.overhaul_form", {"profile": profile})
    assert (
        not form.new and form.setup["path"] == toml and [n["file"] for n in form.choices["natives"]] == ["MixedMod.dll"]
    )
    mod_configs.patch_values(form.values, mod_configs.FormPatch("init", "MixedMod.dll", "Boot"))
    params = {"profile": profile, "path": str(toml), "expect": "stale", "form": _form(form.values)}
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.save_setup", params)
    assert e.value.code == "file_changed"
    saved = s.run("mod_configs.save_setup", {**params, "expect": form.setup["sha"]})
    assert (saved.name, saved.overhaul_id) == ("mixed-mod.toml", "mixed-mod")
    assert "initializer" not in world.text()  # saving the file alone leaves the profile as it was
    job = s.run("mod_configs.apply_setup", {"profile": profile, "overhaul_id": "mixed-mod"})
    snap = s.jobs.get(job)
    assert snap.state == "done" and snap.result == {"profiles": ["my.me3"]}
    assert snap.title.startswith("Applying the overhaul setup")
    assert world.data()["natives"][-1]["initializer"] == {"function": "Boot"}


def test_a_setup_saved_as_text_must_be_a_setup(world):
    _folder, toml, _out = set_up(world)
    s = make(world)
    sha = s.run("mod_configs.open", {"path": str(toml)}).sha
    with pytest.raises(OperationError) as e:
        s.run(
            "mod_configs.save_setup",
            {"profile": str(world.profile), "path": str(toml), "expect": sha, "text": "id = 1 ["},
        )
    assert e.value.code == "invalid_setup"


def test_a_new_setup_is_installed_through_a_plan_and_turned_off_through_another(world):
    folder = mixed_mod(world)
    s = make(world)
    profile = str(world.profile)
    before = world.profile.read_bytes()
    form = s.run("mod_configs.overhaul_form", {"profile": profile, "folder": str(folder), "name": "Mixed Mod"})
    assert form.new and form.setup["path"] is None and form.values["natives"]
    params = {"profile": profile, "folder": str(folder), "name": "Mixed Mod", "form": _form(form.values)}
    plan = s.run("mod_configs.install_setup", params)
    assert isinstance(plan.words, Confirm) and world.profile.read_bytes() == before
    job = s.answer(plan.id, {"ok": True})
    snap = s.jobs.get(job)
    assert snap.state == "done" and "mixed-mod" in world.text()
    assert mod_configs.OVERHAUL in [n.kind for n in s.snapshot("mod_configs", profile=profile).nodes]
    off = s.run("mod_configs.turn_off", {"profile": profile})
    assert isinstance(off.words, Confirm)
    assert s.jobs.get(s.answer(off.id, {"ok": True})).state == "done"
    assert mod_configs.OVERHAUL not in [n.kind for n in s.snapshot("mod_configs", profile=profile).nodes]
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.turn_off", {"profile": profile})  # nothing to turn off now
    assert e.value.code == "cannot_turn_off"
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.overhaul_form", {"profile": profile, "folder": str(world.tmp / "nowhere"), "name": "X"})
    assert e.value.code == "cannot_set_up"


def test_busy_gates_the_install_job(world):
    folder = mixed_mod(world)
    s = make(world, external_busy=lambda: True)
    form = s.run(
        "mod_configs.overhaul_form", {"profile": str(world.profile), "folder": str(folder), "name": "Mixed Mod"}
    )
    plan = s.run(
        "mod_configs.install_setup",
        {"profile": str(world.profile), "folder": str(folder), "name": "Mixed Mod", "form": _form(form.values)},
    )
    with pytest.raises(OperationError) as e:
        s.answer(plan.id, {"ok": True})
    assert e.value.code == "busy"
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.apply_setup", {"profile": str(world.profile), "overhaul_id": "x"})
    assert e.value.code == "busy"
