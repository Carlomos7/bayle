"""The Mod Configs engine interface (ModConfigsService) through the session's operations and directly: no Qt, no
window, every fixture in the test's own folder."""

from pathlib import Path

import pytest
from test_overhaul_install import PROFILE, World, mixed_mod, set_up

from bayle.api.routers import mod_configs as mod_configs_router
from bayle.errors import OperationError
from bayle.mods import configs, overhaul_install
from bayle.services import mod_configs
from bayle.services import mods as mod_service
from bayle.services.mod_configs import ModConfigsService, SetupValues
from bayle.services.settings import load_settings
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from support import Direct


def inline(run, name=None):
    run()


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def make(world, **jobs_kw):
    jobs = JobManager(EventBus(), spawn=inline, **jobs_kw)
    service = ModConfigsService(jobs, lambda: world.loc)
    return Direct(mod_configs_router, "mod_configs", service, jobs)


def ini_of(world) -> Path:
    ini = world.base / "natives/SeamlessCoop/ersc_settings.ini"
    ini.write_text("[PASSWORD]\ncooppassword = room\n[GAMEPLAY]\nallow_invaders = 1\n", encoding="utf-8")
    return ini


def other_of(world) -> Path:
    """A second DLL of the profile with a settings file of its own (listed in the tree)."""
    folder = world.base / "natives/Other"
    folder.mkdir(parents=True)
    (folder / "other.dll").write_bytes(b"d")
    (folder / "other.ini").write_bytes(b"[a]\r\nb = 1\r\nc = 2\r\n")
    world.profile.write_text(PROFILE + "\n[[natives]]\npath = 'natives/Other/other.dll'\n", encoding="utf-8")
    return folder / "other.ini"


def tree_of(root: Path) -> dict:
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for p in [root, *root.rglob("*")]}


def job(s, job_id):
    snap = s.jobs.get(job_id)
    assert snap is not None
    return snap


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


def test_open_reads_a_listed_file_and_the_stamp_tells_a_change(world):
    ini = ini_of(world)
    s = make(world)
    p = str(world.profile)
    got = s.run("mod_configs.open", {"path": str(ini), "seamless": True, "profile": p})
    assert got.text.startswith("[PASSWORD]") and got.seamless is not None and got.seamless.password == "room"
    assert got.regulation == "regulation.bin"
    assert got.stamp == s.run("mod_configs.stamp", {"path": str(ini), "profile": p}).stamp
    ini.write_text(got.text + "x = 1\n", encoding="utf-8")
    assert s.run("mod_configs.stamp", {"path": str(ini), "profile": p}).stamp != got.stamp
    ini.unlink()  # still listed by the tree? a gone file is not
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.open", {"path": str(ini), "profile": p})
    assert e.value.code in ("not_found", "unreadable")


def test_a_file_the_tree_does_not_list_is_not_found(world):
    ini_of(world)
    secret = world.tmp / "secret.ini"
    secret.write_text("[a]\nkey = 1\n", encoding="utf-8")
    s = make(world)
    p = str(world.profile)
    for name, params in (
        ("mod_configs.open", {"path": str(secret), "profile": p}),
        ("mod_configs.stamp", {"path": str(secret), "profile": p}),
        ("mod_configs.save", {"path": str(secret), "profile": p, "expect": "x", "kind": "text", "text": "y"}),
        ("mod_configs.share", {"ini": str(secret), "profile": p}),
        ("mod_configs.export_share", {"ini": str(secret), "to": str(world.tmp / "out.ini"), "profile": p}),
        ("mod_configs.check_paste", {"ini": str(secret), "profile": p, "text": "key = 2"}),
        (
            "mod_configs.open",
            {"path": str(world.base / "natives/SeamlessCoop/ersc_settings.ini"), "profile": "nope.me3"},
        ),
    ):
        with pytest.raises(OperationError) as e:
            s.run(name, params)
        assert e.value.code == "not_found", name
    assert secret.read_text(encoding="utf-8") == "[a]\nkey = 1\n" and not (world.tmp / "out.ini").exists()


def test_save_writes_by_kind_and_refuses_a_file_that_changed(world):
    ini = ini_of(world)
    other = other_of(world)
    s = make(world)
    p = str(world.profile)
    read = s.run("mod_configs.open", {"path": str(other), "profile": p})
    edit = [{"section": "a", "key": "b", "value": "9"}]
    done = s.run(
        "mod_configs.save",
        {"path": str(other), "profile": p, "expect": read.sha, "kind": "values", "edits": edit},
    )
    assert (done.saved, done.missing) == (1, ()) and other.read_bytes() == b"[a]\r\nb = 9\r\nc = 2\r\n"
    with pytest.raises(OperationError) as e:  # read before the change above
        s.run("mod_configs.save", {"path": str(other), "profile": p, "expect": read.sha, "kind": "text", "text": "x"})
    assert e.value.code == "stale" and e.value.details["name"] == "other.ini"
    assert other.read_bytes() == b"[a]\r\nb = 9\r\nc = 2\r\n"  # a refused save writes nothing
    fresh = s.run("mod_configs.open", {"path": str(other), "profile": p})
    s.run(
        "mod_configs.save",
        {"path": str(other), "profile": p, "expect": fresh.sha, "kind": "text", "text": "[a]\nb = 3\n"},
    )
    assert configs.read(other)["text"] == "[a]\nb = 3\n"
    sha = s.run("mod_configs.open", {"path": str(other), "profile": p}).sha
    with pytest.raises(OperationError) as e:  # a setting the file does not have
        s.run(
            "mod_configs.save",
            {"path": str(other), "profile": p, "expect": sha, "kind": "values",
             "edits": [{"section": "a", "key": "zzz", "value": "1"}]},
        )  # fmt: skip
    assert e.value.code == "not_saved"
    sha = s.run("mod_configs.open", {"path": str(ini), "profile": p}).sha
    done = s.run(
        "mod_configs.save",
        {"path": str(ini), "profile": p, "expect": sha, "kind": "seamless",
         "edits": [{"key": "cooppassword", "value": "new"}, {"key": "nope", "value": "1"}]},
    )  # fmt: skip
    assert (done.saved, done.missing) == (1, ("nope",)) and "cooppassword = new" in ini.read_text(encoding="utf-8")
    with pytest.raises(OperationError) as e:  # Seamless is held to the same fingerprint
        s.run(
            "mod_configs.save",
            {
                "path": str(ini),
                "profile": p,
                "expect": "old",
                "kind": "seamless",
                "edits": [{"key": "a", "value": "1"}],
            },
        )
    assert e.value.code == "stale"
    with pytest.raises(OperationError) as e:
        s.run(
            "mod_configs.save",
            {
                "path": str(ini),
                "profile": p,
                "expect": "",
                "kind": "seamless",
                "edits": [{"key": "cooppassword", "value": " "}],
            },
        )
    assert e.value.code == "password_empty"


def test_attach_and_detach_keep_the_tie_in_the_launchers_settings(world):
    other_of(world)
    dll = world.base / "natives/Other/other.dll"
    extra = world.tmp / "extra.txt"
    extra.write_text("x", encoding="utf-8")
    s = make(world)
    p = str(world.profile)
    s.run("mod_configs.attach", {"profile": p, "target": str(dll), "file": str(extra)})
    assert configs.key_for(extra) in [
        configs.key_for(Path(f)) for v in load_settings().native_configs.values() for f in v
    ]
    s.run("mod_configs.detach", {"profile": p, "target": str(dll), "file": str(extra)})
    assert load_settings().native_configs == {}
    with pytest.raises(OperationError) as e:  # a mod the profile does not have
        s.run("mod_configs.attach", {"profile": p, "target": str(world.tmp / "x.dll"), "file": str(extra)})
    assert e.value.code == "not_found" and load_settings().native_configs == {}


def test_sharing_exports_as_a_job_and_pasting_checks_then_writes(world):
    ini = ini_of(world)
    s = make(world)
    p = str(world.profile)
    text = s.run("mod_configs.share", {"ini": str(ini), "profile": p}).text
    assert "cooppassword = room" in text
    out = world.tmp / "friend.ini"
    snap = job(s, s.run("mod_configs.export_share", {"ini": str(ini), "to": str(out), "profile": p}).job_id)
    assert snap.state == "done" and snap.result == {"path": str(out)} and out.read_text(encoding="utf-8") == text
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.check_paste", {"ini": str(ini), "profile": p, "text": "nothing like settings"})
    assert e.value.code == "not_settings"
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.check_paste", {"ini": str(ini), "profile": p, "text": text})
    assert e.value.code == "nothing_to_change"
    before = ini.read_bytes()
    body = {"ini": str(ini), "profile": p, "text": "cooppassword = new\nallow_invaders = 0\nmade_up = 1\n"}
    plan = s.run("mod_configs.check_paste", body)
    assert set(plan.changes) == {"cooppassword", "allow_invaders"} and plan.unknown == ("made_up",)
    assert ini.read_bytes() == before  # nothing before the start
    assert s.run("mod_configs.paste", {**body, "expect": plan.stamp}).saved == 2
    now = ini.read_text(encoding="utf-8")
    assert "cooppassword = new" in now and "allow_invaders = 0" in now
    body = {"ini": str(ini), "profile": p, "text": "cooppassword = other\n"}
    plan = s.run("mod_configs.check_paste", body)
    ini.write_text(now + "\n", encoding="utf-8")  # changed since the question
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.paste", {**body, "expect": plan.stamp})
    assert e.value.code == "stale" and ini.read_text(encoding="utf-8") == now + "\n"
    body = {"ini": str(ini), "profile": p, "text": "cooppassword = \n"}
    plan = s.run("mod_configs.check_paste", body)
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.paste", {**body, "expect": plan.stamp})
    assert e.value.code == "password_empty"


def test_an_export_that_cannot_be_written_fails_with_its_code_and_leaves_nothing_behind(world):
    ini = ini_of(world)
    s = make(world)
    p = str(world.profile)
    dest = world.tmp / "a folder"
    dest.mkdir()  # a folder where the file should go
    snap = job(s, s.run("mod_configs.export_share", {"ini": str(ini), "to": str(dest), "profile": p}).job_id)
    assert snap.state == "failed" and snap.error.code == "not_saved" and snap.error.details["path"] == str(dest)
    assert [x.name for x in world.tmp.iterdir() if x.name.startswith(".") or x.suffix == ".tmp"] == []
    with pytest.raises(OperationError) as e:  # not over the file it was read from
        s.run("mod_configs.export_share", {"ini": str(ini), "to": str(ini), "profile": p})
    assert e.value.code == "invalid_params"


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
    assert e.value.code == "stale"
    saved = s.run("mod_configs.save_setup", {**params, "expect": form.setup["sha"]})
    assert (saved.name, saved.overhaul_id) == ("mixed-mod.toml", "mixed-mod")
    assert "initializer" not in world.text()  # saving the file alone leaves the profile as it was
    snap = job(s, s.run("mod_configs.apply_setup", {"profile": profile, "overhaul_id": "mixed-mod"}).job_id)
    assert snap.state == "done" and snap.result == {"profiles": ["my.me3"]}
    assert snap.title.startswith("Applying the overhaul setup")
    assert world.data()["natives"][-1]["initializer"] == {"function": "Boot"}


def test_a_setup_is_saved_only_at_the_profiles_own_file_and_as_text_it_must_be_a_setup(world):
    _folder, toml, _out = set_up(world)
    s = make(world)
    profile = str(world.profile)
    sha = s.run("mod_configs.overhaul_form", {"profile": profile}).setup["sha"]
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.save_setup", {"profile": profile, "path": str(toml), "expect": sha, "text": "id = 1 ["})
    assert e.value.code == "invalid_setup"
    elsewhere = world.tmp / "elsewhere.toml"
    with pytest.raises(OperationError) as e:  # not the file the profile's setup lives in
        s.run("mod_configs.save_setup", {"profile": profile, "path": str(elsewhere), "expect": sha, "text": "id='x'"})
    assert e.value.code == "not_found" and not elsewhere.exists()
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.save_setup", {"profile": profile, "path": str(toml), "expect": sha})
    assert e.value.code == "invalid_params"


def _candidate(world, folder: Path | None = None) -> Path:
    """The mixed mod as a mod of the profile (an overhaul can only be made from one)."""
    folder = folder or mixed_mod(world)
    inside = world.base / "Mixed Mod"
    folder.rename(inside)
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = 'mixed'\npath = 'Mixed Mod'\n", encoding="utf-8")
    return inside


def test_a_new_setup_is_installed_through_a_check_and_a_start_and_turned_off_the_same_way(world):
    folder = _candidate(world)
    s = make(world)
    profile = str(world.profile)
    cands = s.run("mod_configs.setup_candidates", {"profile": profile}).mods
    assert str(folder) in [c.folder for c in cands]
    form = s.run("mod_configs.overhaul_form", {"profile": profile, "folder": str(folder), "name": "Mixed Mod"})
    assert form.new and form.setup["path"] is None and form.values["natives"]
    params = {"profile": profile, "folder": str(folder), "name": "Mixed Mod", "form": _form(form.values)}
    before = world.profile.read_bytes()
    plan = s.run("mod_configs.check_install_setup", params)
    assert plan.refusals == () and plan.lines and world.profile.read_bytes() == before  # a check writes nothing
    world.profile.write_bytes(before + b"\n# edited meanwhile\n")
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.install_setup", {**params, "expect": plan.stamp})
    assert e.value.code == "stale"
    plan = s.run("mod_configs.check_install_setup", params)
    snap = job(s, s.run("mod_configs.install_setup", {**params, "expect": plan.stamp}).job_id)
    assert snap.state == "done" and snap.result["name"]
    assert "mixed-mod" in world.text()
    assert mod_configs.OVERHAUL in [n.kind for n in s.snapshot("mod_configs", profile=profile).nodes]
    off = s.run("mod_configs.check_turn_off", {"profile": profile})
    assert off.refusals == () and off.label and off.lines
    assert job(s, s.run("mod_configs.turn_off", {"profile": profile, "expect": off.stamp}).job_id).state == "done"
    assert mod_configs.OVERHAUL not in [n.kind for n in s.snapshot("mod_configs", profile=profile).nodes]
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.check_turn_off", {"profile": profile})  # nothing to turn off now
    assert e.value.code == "cannot_turn_off"


def test_a_new_setup_only_comes_from_a_mod_of_the_profile(world):
    folder = mixed_mod(world)  # in Downloads, not in the profile
    s = make(world)
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.overhaul_form", {"profile": str(world.profile), "folder": str(folder), "name": "X"})
    assert e.value.code == "not_found"
    inside = _candidate(world, folder)
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.overhaul_form", {"profile": str(world.profile), "folder": str(inside / "chr"), "name": "X"})
    assert e.value.code == "not_found"


def test_a_failing_install_job_carries_its_code_and_leaves_the_profile_as_it_was(world, monkeypatch):
    folder = _candidate(world)
    s = make(world)
    profile = str(world.profile)
    form = s.run("mod_configs.overhaul_form", {"profile": profile, "folder": str(folder), "name": "Mixed Mod"})
    params = {"profile": profile, "folder": str(folder), "name": "Mixed Mod", "form": _form(form.values)}
    plan = s.run("mod_configs.check_install_setup", params)

    def refuses(preview, *, loc):
        raise overhaul_install.OverhaulError("The profile is busy.")

    monkeypatch.setattr(mod_service, "install_overhaul_setup", refuses)
    before = world.profile.read_bytes()
    snap = job(s, s.run("mod_configs.install_setup", {**params, "expect": plan.stamp}).job_id)
    assert snap.state == "failed" and snap.error.code == "cannot_set_up" and snap.error.details["label"]
    assert world.profile.read_bytes() == before


def test_busy_gates_the_jobs(world):
    folder = _candidate(world)
    s = make(world, external_busy=lambda: True)
    profile = str(world.profile)
    form = s.run("mod_configs.overhaul_form", {"profile": profile, "folder": str(folder), "name": "Mixed Mod"})
    params = {"profile": profile, "folder": str(folder), "name": "Mixed Mod", "form": _form(form.values)}
    plan = s.run("mod_configs.check_install_setup", params)
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.install_setup", {**params, "expect": plan.stamp})
    assert e.value.code == "busy"
    with pytest.raises(OperationError) as e:
        s.run("mod_configs.apply_setup", {"profile": profile, "overhaul_id": "x"})
    assert e.value.code == "busy"


def test_the_service_takes_the_settings_it_is_given(world):
    other_of(world)
    service = ModConfigsService(JobManager(EventBus(), spawn=inline), lambda: world.loc)
    dll = world.base / "natives/Other/other.dll"
    extra = world.tmp / "extra.txt"
    extra.write_text("x", encoding="utf-8")
    settings = load_settings()
    service.attach(str(world.profile), dll, extra, settings)
    assert settings.native_configs  # the object the client gave is the one updated
    state = service.page(str(world.profile), settings)
    other = next(n for n in state.nodes if n.name == "other.dll")
    assert [(f.path.name, f.how) for f in other.files if f.how == "attached"] == [("extra.txt", "attached")]
    assert SetupValues([], {}, {}).health is None
