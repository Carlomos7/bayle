"""Installing an overhaul with the launcher (preview), removing it, and an overhaul installer's leftovers
(mods.overhaul_install): synthetic profiles, a synthetic Example-like download built like test_engine's, a fake game,
a fake Recycle Bin. Any program started fails the test: nothing of the mod's runs."""

import json
import subprocess
import tomllib
from pathlib import Path

import fakegame
import pytest
from fakegame import bnd, dcx, fmg
from test_engine import ARCHIVES, GAME_CLIPS, PAYLOAD, game_files
from test_param_merge import pack, set_word, vanilla

from roundtable_souls import overhauls
from roundtable_souls.game import catalog, locate
from roundtable_souls.game.locate import Locations, Overrides
from roundtable_souls.merging import build as B
from roundtable_souls.mods import library, operations, overhaul_install, records, undo
from roundtable_souls.mods import rebuild as merge
from roundtable_souls.mods.overhaul_install import OverhaulError
from roundtable_souls.platform import paths as common
from roundtable_souls.platform import trash as real_trash

PROFILE = """profileVersion = "v1"
start_online = true

# my mods
[[packages]]
id = "body"
path = 'mod/body'

[[packages]]
id = "anims"
path = 'mod/anims'

[[natives]]
path = 'natives/SeamlessCoop/ersc.dll'
load_early = true
"""


class Crash(BaseException):
    """The process dying: nothing after it runs, not even the undo."""


class Bin:
    """A Recycle Bin in a temporary folder: send moves an item there, restore puts it back."""

    TrashError = real_trash.TrashError

    def __init__(self, root: Path):
        self.root = root
        self.n = 0

    def available(self) -> bool:
        return True

    def send(self, path: Path) -> dict:
        self.n += 1
        item = self.root / f"R{self.n}"
        self.root.mkdir(parents=True, exist_ok=True)
        Path(path).replace(item)
        return {"kind": "test", "item": str(item), "original": str(path)}

    def exists(self, record) -> bool:
        return bool(record) and Path(record["item"]).exists()

    def restore(self, record) -> Path:
        Path(record["original"]).parent.mkdir(parents=True, exist_ok=True)  # as platform.trash.restore does
        Path(record["item"]).replace(record["original"])
        return Path(record["original"])


class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.tmp = tmp_path
        self.profiles = tmp_path / "me3" / "profiles"
        self.base = self.profiles / "eldenring-mods"
        self.game = tmp_path / "Game"
        self.game.mkdir(parents=True)
        (self.game / "regulation.bin").write_bytes(vanilla())
        (self.game / "eldenring.exe").write_bytes(b"x")
        fakegame.game(monkeypatch, game_files())
        monkeypatch.setattr(locate, "installed_dir", lambda _game: self.game)
        monkeypatch.setattr(common, "exe_running", lambda _exe: False)
        self.loc = Locations(catalog.ELDEN_RING, Overrides(profiles_dir=str(self.profiles)))
        self.download = self.make_download(tmp_path / "Downloads" / "ExampleOverhaul-LITE-0.1.33-rc3")
        body = self.base / "mod" / "body"
        (body / "parts").mkdir(parents=True)
        anims = self.base / "mod" / "anims"
        (anims / "chr").mkdir(parents=True)
        (anims / "chr/c0000_a00_hi.anibnd.dcx").write_bytes(dcx(bnd({"a000_000.hkx": b"sekiro walk"})))
        (anims / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(1000, 0, 55)}))
        (self.base / "natives/SeamlessCoop").mkdir(parents=True)
        (self.base / "natives/SeamlessCoop/ersc.dll").write_bytes(b"d")
        self.profile = self.base / "my.me3"
        self.profile.write_text(PROFILE, encoding="utf-8")
        self.own = self.base / "ExampleOverhaul"
        self.bin = Bin(tmp_path / "bin")
        monkeypatch.setattr(overhaul_install, "trash", self.bin)

        def no_programs(*args, **kwargs):
            raise AssertionError(f"a program was started: {args[0] if args else kwargs}")

        monkeypatch.setattr(subprocess, "run", no_programs)
        monkeypatch.setattr(subprocess, "Popen", no_programs)

    @staticmethod
    def make_download(top: Path, version: str = "0.1.33-rc3", edition: str = "LITE") -> Path:
        """Example's download as its archive unpacks: a folder named after the edition inside."""
        d = top / f"ExampleOverhaul-{edition}"
        for f in PAYLOAD:
            (d / f).parent.mkdir(parents=True, exist_ok=True)
            (d / f).write_bytes(f"{version} {f}".encode())
        (d / "payload/ExamplePrototype.ini").write_text("[Coop]\nEnabled=1\n")
        for rel in ARCHIVES:
            (d / "payload/mod" / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / "payload/mod" / rel).write_bytes(dcx(bnd({**GAME_CLIPS, "example.hkx": b"example"})))
        (d / "payload/mod/regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(2000, 1, 77)}))
        (d / "payload/settings/engus.json").write_text('{"99002000": "Example: session settings"}')
        (d / "payload/settings/rusru.json").write_text('{"99002000": "Example ru"}', encoding="utf-8")
        for lang in ("engus", "rusru"):  # the game's text per language, a fallback the text step names
            (d / f"payload/settings/vanilla/msg/{lang}").mkdir(parents=True)
            (d / f"payload/settings/vanilla/msg/{lang}/menu_dlc02.msgbnd.dcx").write_bytes(
                dcx(bnd({"EventTextForTalk.fmg": fmg({1000: "Rest"})}))
            )
        (d / "payload/settings/vanilla/script/talk").mkdir(parents=True)
        (d / "payload/settings/vanilla/script/talk/m00.bin").write_bytes(b"unused")
        (d / "payload/mod/action/script").mkdir(parents=True)
        (d / "payload/mod/action/script/c0000.hks").write_text(
            "-- vanilla\nfunction Update() end\n-- Wrap the current mod's Update;\nexample stock wrapper\n"
        )
        (d / "installer").mkdir()
        (d / "installer/example.hks").write_text("-- example extension\n")
        (d / "installer/setup.py").write_text("# the mod's installer")
        (d / "tools/python").mkdir(parents=True)
        (d / "tools/python/python.exe").write_bytes(b"py")
        (d / "licenses").mkdir()
        (d / "licenses/lupa.txt").write_text("MIT")
        (d / "Install.cmd").write_text("@echo off")
        (d / "edition.json").write_text(json.dumps({"version": version, "edition": edition}))
        return d

    def preview(self, download=None, **kw):
        return overhaul_install.preview_install(self.profile, download or self.download.parent, loc=self.loc, **kw)

    def install(self, download=None):
        p = self.preview(download)
        assert p.ok, p.refusals
        return overhaul_install.install(p, loc=self.loc)

    def text(self) -> str:
        return self.profile.read_text(encoding="utf-8")

    def data(self) -> dict:
        return tomllib.loads(self.text())

    @property
    def library(self) -> Path:
        return library.ProfileFolder.of(self.profile).root


def files(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes()
        for p in Path(folder).rglob("*")
        if p.is_file()
        and not p.relative_to(folder).as_posix().startswith((".bayle", ".roundtable"))
        and ".bak" not in p.suffixes
        and "history" not in p.parts
    }


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


# ----------------------------------------------------------------------------- recognising a download
def test_a_download_is_recognised_from_its_folder_or_the_one_inside(world):
    for picked in (world.download, world.download.parent):
        found = overhaul_install.find_download(picked, "eldenring")
        assert found.folder == world.download and found.label == "Example Overhaul 0.1.33-rc3"


def test_downloads_the_launcher_does_not_install_are_refused_in_plain_words(world, tmp_path):
    other = World.make_download(tmp_path / "s", edition="STANDALONE")
    with pytest.raises(OverhaulError, match="Example Overhaul STANDALONE is not installed by the launcher"):
        overhaul_install.find_download(other, "eldenring")
    newer = World.make_download(tmp_path / "n", version="0.2.0")
    with pytest.raises(OverhaulError, match="0.2.0 is newer than the launcher knows.*own installer"):
        overhaul_install.find_download(newer, "eldenring")
    (tmp_path / "x").mkdir()
    with pytest.raises(OverhaulError, match="doesn't know x as an overhaul"):
        overhaul_install.find_download(tmp_path / "x", "eldenring")
    with pytest.raises(OverhaulError, match="is a mod for Elden Ring"):
        overhaul_install.find_download(world.download, "nightreign")


# ----------------------------------------------------------------------------- installing
def test_a_fresh_install_is_previewed_then_applied_with_relative_paths(world):
    before = files(world.base)
    p = world.preview()
    assert p.ok and not p.update and files(world.base) == before  # a preview writes nothing
    said = "\n".join(p.lines)
    assert "files its build needs" in said and "builds" in said
    assert (
        "gets its entries, loading after your mods: ExampleHudBootstrap.dll, ExamplePrototype.dll, example-overhaul"
        in said
    )
    assert "start_online: on becomes off" in said
    out = overhaul_install.install(p, loc=world.loc)
    assert not out["update"]
    data = world.data()
    assert data["start_online"] is False
    assert [n["path"] for n in data["natives"]] == [
        "natives/SeamlessCoop/ersc.dll",
        "ExampleOverhaul/ExampleHudBootstrap.dll",
        "ExampleOverhaul/ExamplePrototype.dll",
    ]
    assert data["natives"][2]["load_after"] == [{"id": "ersc.dll", "optional": True}]
    assert data["packages"][-1] == {
        "id": "example-overhaul",
        "path": "ExampleOverhaul/mod",
        "load_after": [{"id": "body", "optional": True}, {"id": "anims", "optional": True}],
    }
    assert "# my mods" in world.text()  # the player's own text kept
    # the launcher's build, in today's folder, with the player's settings file and the licences
    assert (world.own / "mod/regulation.bin").is_file() and (world.own / "ExamplePrototype.dll").is_file()
    assert (world.own / "ExamplePrototype.ini").read_text() == "[Coop]\nEnabled=1\n"
    manifest = json.loads((world.own / "installation.json").read_text())
    sources = world.library / "builds" / "example-overhaul" / "sources"
    assert manifest["installedBy"].startswith("Roundtable Souls") and manifest["maintenance"] == str(sources)
    assert manifest["profile"] == str(world.profile) and "baseProfile" not in manifest
    assert not any(".installing-" in str(r["path"]) for r in manifest["sources"])
    # the download copy: what the build reads, at download paths; no installer, no programs
    kept = files(sources)
    assert "payload/mod/regulation.bin" in kept and "installer/example.hks" in kept and "edition.json" in kept
    assert "payload/settings/vanilla/msg/rusru/menu_dlc02.msgbnd.dcx" not in kept  # the game's own are read instead
    assert "licenses/lupa.txt" in kept
    assert not {"installer/setup.py", "tools/python/python.exe", "Install.cmd"} & set(kept)
    assert "payload/settings/vanilla/script/talk/m00.bin" not in kept
    src_record = records.SourcesRecord.load(sources / "roundtable.json")
    assert src_record.files["edition.json"].from_ == "edition.json"
    record = records.OverhaulRecord.load(world.library / "builds/example-overhaul/overhaul/roundtable.json")
    assert record.build == "example-overhaul-lite" and record.from_ == str(world.download)
    effects = records.SideEffectsRecord.load(world.library / "builds/example-overhaul/roundtable.json")
    assert [(e.entry, e.setting, e.before, e.after) for e in effects.changes] == [(None, "start_online", True, False)]
    # nothing of the installer's
    assert not (world.base / ".example-overhaul-setup").exists()
    assert not list(world.base.rglob("example-maintenance.json"))
    assert operations.problem(world.profile) is None
    # the rebuild before Play knows it as the launcher's build, current, with the preview build switch off
    tool = merge.find_backend(world.profile, loc=world.loc)
    assert tool is not None and tool.recipe.engine is not None
    assert merge.health(world.profile, loc=world.loc)["state"] == "current"


def test_a_launcher_install_whose_download_copy_is_gone_says_so(world):
    import shutil

    world.install()
    shutil.rmtree(world.library / "builds" / "example-overhaul" / "sources")
    tool = merge.find_backend(world.profile, loc=world.loc)
    assert tool is not None and tool.recipe.engine is None
    assert tool.recipe.problem is not None and "copy of example-overhaul's download is gone" in tool.recipe.problem
    assert "Install it again with the launcher" in tool.recipe.problem


def test_installing_again_is_an_update_with_one_set_of_entries(world, tmp_path):
    world.install()
    (world.own / "ExamplePrototype.ini").write_text("[Coop]\nEnabled=0\n")  # the player's setting
    first = files(world.own)
    newer = World.make_download(tmp_path / "again")
    (newer / "payload/ExamplePrototype.dll").write_bytes(b"rebuilt dll")
    p = world.preview(newer)
    assert p.ok and p.update and "is replaced by" in "\n".join(p.lines)
    out = overhaul_install.install(p, loc=world.loc)
    assert out["update"]
    data = world.data()
    assert [n["path"] for n in data["natives"]].count("ExampleOverhaul/ExamplePrototype.dll") == 1
    assert [x["id"] for x in data["packages"]].count("example-overhaul") == 1
    assert (world.own / "ExamplePrototype.dll").read_bytes() == b"rebuilt dll"
    assert (world.own / "ExamplePrototype.ini").read_text() == "[Coop]\nEnabled=0\n"  # kept
    # Roll back from Activity: the version before, as a set
    rec = {"type": "overhaul-update", "profile": str(world.profile), "name": "x", "operation": out["operation"]}
    assert undo.available(rec) and undo.label(rec) == "Roll back"
    undo.run(rec, lambda s: None, loc=world.loc)
    assert files(world.own) == first


def test_a_second_overhaul_is_refused_with_the_reason(world, tmp_path):
    toy = overhauls.OverhaulConfig.model_validate(
        tomllib.loads(
            """overhaul = 1
id = "toy"
label = "Toy Overhaul"
short_label = "Toy"
game = "eldenring"
[recognise]
folder = "Toy"
manifest = "installation.json"
[[builds]]
id = "toy"
match = { files = ["toy.json"] }
output = { mod = "mod" }
steps = []
[builds.install]
owned_package_ids = ["toy"]
"""
        )
    )
    with world.profile.open("a", encoding="utf-8") as f:
        f.write("\n[[packages]]\nid = \"toy\"\npath = 'mod/body'\n")
    configs = [*overhauls.load("eldenring"), toy]
    p = world.preview(configs=configs)
    assert not p.ok
    assert "This profile already has Toy Overhaul. A profile can have one overhaul for now" in p.refusals[0]
    with pytest.raises(OverhaulError):
        overhaul_install.install(p, loc=world.loc)


def test_a_setup_its_own_installer_made_is_not_rewritten(world):
    world.own.mkdir()
    (world.own / "installation.json").write_text(json.dumps({"version": "0.1.33-rc3", "sources": []}))
    before = files(world.base)
    p = world.preview()
    assert not p.ok and "was installed by its own installer" in p.refusals[0] and "Remove Example" in p.refusals[0]
    assert files(world.base) == before


def test_a_profile_changed_after_the_preview_is_not_overwritten(world):
    p = world.preview()
    world.profile.write_text(PROFILE + "\n# edited\n", encoding="utf-8")
    with pytest.raises(Exception, match="changed outside the launcher"):
        overhaul_install.install(p, loc=world.loc)
    assert world.text().endswith("# edited\n") and not world.own.exists()
    assert not (world.library / "builds" / "example-overhaul" / "sources").exists()


def test_a_failed_build_leaves_everything_as_it_was(world, monkeypatch):
    from roundtable_souls.mods import engine

    before = files(world.base)

    def broken(*a, **k):
        raise engine.EngineError("chr/c0000.anibnd.dcx could not be merged")

    monkeypatch.setattr(engine, "build", broken)
    with pytest.raises(engine.EngineError):
        world.install()
    assert files(world.base) == before
    assert not [
        p for p in world.base.iterdir() if p.name.startswith(".") and not p.name.startswith((".bayle", ".roundtable"))
    ]
    assert not list((world.library / "builds" / "example-overhaul").glob(".sources.staging*"))  # no staged copy left
    assert operations.pending(world.profile) == []


@pytest.mark.parametrize("crash_at", [1, 2, 3])
def test_an_interrupted_install_is_undone_on_the_next_start(world, monkeypatch, crash_at):
    before = files(world.base)
    real = B.os.replace
    n = {"i": 0}

    def dying(src, dst):
        # each live change of the commit: the download copy, the overhaul's folder, the profile
        if Path(dst).is_relative_to(world.profiles) and "journal" not in Path(dst).name:
            n["i"] += 1
            if n["i"] == crash_at:
                raise Crash()
        return real(src, dst)

    p = world.preview()
    with monkeypatch.context() as m:
        m.setattr(B.os, "replace", dying)
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            overhaul_install.install(p, loc=world.loc)
    assert "did not finish" in (operations.problem(world.profile) or "")
    said = operations.recover(world.profile)
    assert said and "undone" in said[0]
    assert files(world.base) == before and operations.problem(world.profile) is None
    assert not (world.library / "builds" / "example-overhaul" / "sources").exists()


def test_undo_install_from_activity_puts_the_profile_back_exactly(world):
    before = world.profile.read_bytes()
    out = world.install()
    rec = {"type": "overhaul-install", "profile": str(world.profile), "name": "x", "operation": out["operation"]}
    assert undo.available(rec) and undo.label(rec) == "Undo install"
    said = undo.run(rec, lambda s: None, loc=world.loc)
    assert "took back the install of Example Overhaul" in said
    assert world.profile.read_bytes() == before
    assert not world.own.exists() and not (world.library / "builds" / "example-overhaul" / "sources").exists()
    assert not (world.library / "builds/example-overhaul/overhaul/roundtable.json").exists()
    assert not (world.library / "builds/example-overhaul/roundtable.json").exists()
    assert not undo.available(rec)


# ----------------------------------------------------------------------------- removing
def test_remove_takes_its_entries_puts_side_effects_back_and_recycles_its_folders(world):
    world.install()
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    said = "\n".join(r.lines)
    assert r.ok and not r.legacy
    assert "loses Example Overhaul's entries: ExampleHudBootstrap.dll, ExamplePrototype.dll, example-overhaul" in said
    assert "start_online goes back to on, as before the install" in said
    assert "The launcher's copy of its download" in said and "Its folder ExampleOverhaul" in said
    assert "Seamless Co-op and your other mods are not touched" in said
    out = overhaul_install.remove(r)
    data = world.data()
    assert data["start_online"] is True
    assert [n["path"] for n in data["natives"]] == ["natives/SeamlessCoop/ersc.dll"]  # Seamless stays
    assert [x["id"] for x in data["packages"]] == ["body", "anims"]
    assert not world.own.exists() and len(out["trash"]) == 2
    assert not (world.library / "builds" / "example-overhaul" / "sources").exists()
    assert not (world.library / "builds" / "example-overhaul" / "overhaul").exists()
    assert not (world.library / "builds" / "example-overhaul").exists()
    assert operations.problem(world.profile) is None
    # Restore from Activity: all of it back
    removed = world.profile.read_bytes()
    rec = {"type": "overhaul-remove", "profile": str(world.profile), "name": "x", **out}
    assert undo.available(rec) and undo.label(rec) == "Restore"
    undo.run(rec, lambda s: None, loc=world.loc)
    assert world.profile.read_bytes() != removed and world.data()["start_online"] is False
    assert (world.own / "mod/regulation.bin").is_file()
    assert (world.library / "builds/example-overhaul/roundtable.json").is_file()
    assert merge.health(world.profile, loc=world.loc)["state"] == "current"


def test_a_side_effect_changed_since_is_left_and_said(world):
    world.install()
    world.profile.write_text(world.text().replace("start_online = false", "start_online = true"), encoding="utf-8")
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    assert r.reverted == [] and any("start_online stays on: you changed it after the install" in x for x in r.left)
    overhaul_install.remove(r)
    assert world.data()["start_online"] is True


def test_a_shared_dependency_switched_on_by_the_install_is_only_switched_off_when_asked(world):
    world.install()
    effects = world.library / "builds/example-overhaul/roundtable.json"
    rec = records.SideEffectsRecord(
        changes=[records.SideEffect(entry="ersc.dll", setting="enabled", before=False, before_set=True, after=True)]
    )
    effects.write_text(rec.text(), encoding="utf-8")
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    assert [e.entry for e in r.asked] == ["ersc.dll"] and "stays switched on unless you choose" in "\n".join(r.lines)
    assert r.change is not None and "enabled = false" not in r.change.text
    asked = overhaul_install.preview_remove(world.profile, loc=world.loc, revert_asked=True)
    assert asked.asked == [] and [e.entry for e in asked.reverted] == ["ersc.dll"]
    overhaul_install.remove(asked)
    [seamless] = world.data()["natives"]
    assert seamless["path"] == "natives/SeamlessCoop/ersc.dll" and seamless["enabled"] is False  # still there


def test_a_folder_another_profile_uses_stays(world):
    world.install()
    other = world.base / "other.me3"
    other.write_text("[[packages]]\nid = \"example-overhaul\"\npath = 'ExampleOverhaul/mod'\n", encoding="utf-8")
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    assert r.users == [other] and "Its folder ExampleOverhaul stays: other.me3 still uses it" in "\n".join(r.lines)
    overhaul_install.remove(r)
    assert world.own.is_dir() and (world.own / "mod/regulation.bin").is_file()


def test_an_interrupted_removal_before_its_folder_went_is_undone(world, monkeypatch):
    world.install()
    before = files(world.base)
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    with monkeypatch.context() as m:
        m.setattr(world.bin, "send", lambda path: (_ for _ in ()).throw(Crash()))
        m.setattr(B, "_undo", lambda op: None)
        with pytest.raises(Crash):
            overhaul_install.remove(r)
    assert operations.problem(world.profile)
    said = operations.recover(world.profile)
    assert said and "undone" in said[0]
    assert files(world.base) == before


def test_a_profile_without_an_overhaul_says_so(world):
    with pytest.raises(OverhaulError, match="my.me3 has no overhaul the launcher knows"):
        overhaul_install.preview_remove(world.profile, loc=world.loc)


# ----------------------------------------------------------------------------- a setup its own installer made
def legacy(world) -> None:
    """Example's installer's setup: its folder with its manifest, its setup copy, its backup of the profile before."""
    world.own.mkdir()
    (world.own / "mod").mkdir()
    (world.own / "mod/regulation.bin").write_bytes(b"x" * 3000)
    (world.own / "ExamplePrototype.dll").write_bytes(b"d")
    (world.own / "installation.json").write_text(json.dumps({"version": "0.1.33-rc3", "sources": []}))
    setup = world.base / ".example-overhaul-setup"
    (setup / "payload").mkdir(parents=True)
    (setup / "payload/big.bin").write_bytes(b"y" * 5000)
    for stamp, start_online in (("20260101-000000-000000", "true"), ("20260201-000000-000000", "false")):
        b = world.base / "Example Backups" / stamp
        b.mkdir(parents=True)
        (b / "file-0").write_text(PROFILE.replace("start_online = true", f"start_online = {start_online}"))
        (b / "restore.json").write_text(
            json.dumps({"files": [{"path": str(world.profile), "original": "file-0"}], "directories": []})
        )
    world.profile.write_text(
        PROFILE.replace("start_online = true", "start_online = false")
        + "\n[[natives]]\npath = 'ExampleOverhaul/ExamplePrototype.dll'\n"
        + "\n[[packages]]\nid = \"example-overhaul\"\npath = 'ExampleOverhaul/mod'\n",
        encoding="utf-8",
    )


def test_an_installer_setup_is_removed_with_the_changes_chosen_and_its_leftovers_offered(world):
    legacy(world)
    choices = overhaul_install.legacy_effects(world.profile, loc=world.loc)
    assert [(e.setting, e.before, e.after) for e in choices] == [("start_online", True, False)]  # the oldest backup
    r = overhaul_install.preview_remove(world.profile, loc=world.loc, legacy_choices=choices)
    assert r.legacy and r.trash == [world.own]
    overhaul_install.remove(r)
    assert world.data()["start_online"] is True and not world.own.exists()
    assert "ExamplePrototype" not in world.text()
    left = overhaul_install.leftovers(world.profile, loc=world.loc)
    assert [(x.path.name, x.backups) for x in left] == [(".example-overhaul-setup", False), ("Example Backups", True)]
    assert left[0].label.startswith(".example-overhaul-setup (") and left[0].size == 5000
    overhaul_install.remove_leftovers([left[0].path])
    assert not (world.base / ".example-overhaul-setup").exists() and (world.base / "Example Backups").is_dir()


def test_leftovers_in_use_are_not_offered(world):
    legacy(world)
    assert overhaul_install.leftovers(world.profile, loc=world.loc) == []


def test_without_choices_an_installer_setups_side_effects_stay(world):
    legacy(world)
    r = overhaul_install.preview_remove(world.profile, loc=world.loc)
    overhaul_install.remove(r)
    assert world.data()["start_online"] is False


# ----------------------------------------------------------------------------- the services the pages call
def test_the_services_leave_the_undo_records_activity_offers(world, monkeypatch):
    from roundtable_souls.config import settings
    from roundtable_souls.platform import logging as run_logging
    from roundtable_souls.services import mods as service

    assert not service.overhaul_preview_on(world.loc)  # the switch is off by default
    settings.save_settings(overhaul_install=True)
    assert service.overhaul_preview_on(world.loc)
    undos = []
    monkeypatch.setattr(run_logging, "set_undo", lambda d: undos.append(d))
    p = service.preview_overhaul_install(world.profile, world.download, loc=world.loc)
    out = service.install_overhaul(p, loc=world.loc)
    assert undos[-1] == {
        "type": "overhaul-install",
        "profile": str(world.profile),
        "name": "Example Overhaul",
        "operation": out["operation"],
    }
    assert undo.available(undos[-1])
    assert service.profile_overhaul(world.profile, loc=world.loc) == {
        "label": "Example Overhaul",
        "short_label": "Example",
        "legacy": False,
        "takeover": False,
    }
    r = service.preview_overhaul_removal(world.profile, loc=world.loc)
    service.remove_overhaul(r)
    assert undos[-1]["type"] == "overhaul-remove" and len(undos[-1]["trash"]) == 2
    assert undo.available(undos[-1]) and service.profile_overhaul(world.profile, loc=world.loc) is None


def test_a_profile_its_overhauls_installer_made_cannot_be_deleted_one_the_launcher_made_can(world):
    from types import SimpleNamespace

    from roundtable_souls.services import profile_mods as pm

    def refusal(kind="me3", source=None):
        return pm.delete_refusal(
            SimpleNamespace(profile=str(world.profile), kind=kind, source=str(source or world.profile)),
            False,
            loc=world.loc,
        )

    world.install()
    manifest = world.own / "installation.json"
    assert refusal() is None and refusal("manifest", manifest) is None
    assert pm.overhaul_to_keep(world.profile, loc=world.loc) == "Example Overhaul"
    overhaul_install.remove(overhaul_install.preview_remove(world.profile, loc=world.loc))
    legacy(world)  # the same profile, as its installer sets it up: refused through the .me3 and the manifest
    assert refusal() == pm.DELETE_MANAGED and refusal("manifest", manifest) == pm.DELETE_MANAGED
    assert pm.overhaul_to_keep(world.profile, loc=world.loc) == ""


def test_an_installer_setups_choices_and_leftovers_through_the_services(world):
    from roundtable_souls.services import mods as service

    legacy(world)
    assert service.profile_overhaul(world.profile, loc=world.loc)["legacy"] is True
    [(text, effect)] = service.legacy_overhaul_choices(world.profile, loc=world.loc)
    assert text == "start_online: back to on (its installer made it off)"
    r = service.preview_overhaul_removal(world.profile, loc=world.loc, legacy_choices=[effect])
    service.remove_overhaul(r)
    left = service.overhaul_leftovers(world.profile, loc=world.loc)
    assert [x.backups for x in left] == [False, True]
    service.remove_overhaul_leftovers([x.path for x in left])
    assert service.overhaul_leftovers(world.profile, loc=world.loc) == []


def test_the_switch_and_button_words_come_from_the_configs(world):
    from roundtable_souls.services import mods as service

    assert service.installable_overhauls("eldenring") == ["Example Overhaul LITE 0.1.33-rc3"]
    assert service.installable_overhauls("nightreign") == []
    text = service.overhaul_switch_text("eldenring")
    assert "Covers only Example Overhaul LITE 0.1.33-rc3" in text
    assert "in the profile's builds folder" in text
    assert "Covers only Example Overhaul LITE 0.1.33-rc3" in service.overhaul_button_tip("eldenring")


# ----------------------------------------------------------------------------- the Overhaul setup form (S3g)
def mixed_mod(world) -> Path:
    """A mod no config describes: game files and a DLL with its settings."""
    m = world.tmp / "Downloads" / "Mixed Mod"
    (m / "chr").mkdir(parents=True)
    (m / "chr/c0000_a00_hi.anibnd.dcx").write_bytes(dcx(bnd({**GAME_CLIPS, "mine.hkx": b"mine"})))
    (m / "regulation.bin").write_bytes(pack({"EquipParamWeapon": set_word(2000, 0, 9)}))
    (m / "MixedMod.dll").write_bytes(b"d")
    (m / "MixedMod.ini").write_text("[a]\nb=1\n")
    return m


def set_up(world) -> tuple[Path, Path, dict]:
    from roundtable_souls.overhauls import basic

    folder = mixed_mod(world)
    config = basic.make(id="mixed-mod", label="Mixed Mod", game="eldenring", basic=basic.propose(folder), folder=folder)
    p = overhaul_install.preview_setup(world.profile, folder, config, loc=world.loc)
    assert p.ok, p.refusals
    out = overhaul_install.install_setup(p, loc=world.loc)
    local = overhauls.local_dir()
    assert local is not None
    toml = local / "mixed-mod.toml"
    assert overhauls.read(toml) == config
    return folder, toml, out


def test_a_setup_made_with_the_form_is_undone_with_its_config(world):
    before = world.profile.read_bytes()
    _folder, toml, out = set_up(world)
    assert "mixed-mod" in world.text() and (world.base / "mixed-mod" / "mod").is_dir()
    rec = {"type": "overhaul-install", "profile": str(world.profile), "name": "x", "operation": out["operation"]}
    undo.run(rec, lambda s: None, loc=world.loc)
    assert world.profile.read_bytes() == before
    assert not toml.exists() and not (world.base / "mixed-mod").exists()


def test_turn_off_makes_the_mod_ordinary_and_undo_puts_the_setup_back(world):
    _folder, toml, _out = set_up(world)
    before, setup = world.profile.read_bytes(), toml.read_bytes()
    own = files(world.base / "mixed-mod")
    t = overhaul_install.preview_turn_off(world.profile, loc=world.loc)
    assert t.ok, t.refusals
    out = overhaul_install.turn_off(t)
    off = toml.with_name(toml.name + ".off")
    plain = world.base / "mod" / "mixed-mod"
    assert not toml.exists() and off.read_bytes() == setup
    assert not (world.base / "mixed-mod").exists() and (plain / "MixedMod.dll").is_file()
    assert not (plain / "roundtable.json").exists()
    data = world.data()
    assert {"id": "mixed-mod", "path": "mod/mixed-mod"}.items() <= data["packages"][-1].items()
    assert data["natives"][-1]["path"] == "mod/mixed-mod/MixedMod.dll"
    rec = {
        "type": "overhaul-turn-off",
        "profile": str(world.profile),
        "name": out["name"],
        "operation": out["operation"],
        "trash": out["trash"],
    }
    assert undo.available(rec) and undo.label(rec) == "Undo turn off"
    undo.run(rec, lambda s: None, loc=world.loc)
    assert world.profile.read_bytes() == before and toml.read_bytes() == setup and not off.exists()
    assert not plain.exists() and files(world.base / "mixed-mod") == own


# ----------------------------------------------------------------------------- the generic setup needs no shipped config
def test_the_setup_is_offered_with_the_switch_on_even_with_no_shipped_config(world, monkeypatch, tmp_path):
    from roundtable_souls.config import settings
    from roundtable_souls.overhauls import config as overhaul_config
    from roundtable_souls.services import mods as service

    empty = tmp_path / "no-shipped"
    empty.mkdir()
    monkeypatch.setattr(overhaul_config, "SHIPPED_DIR", empty)
    assert service.installable_overhauls("eldenring") == []
    assert not service.overhaul_preview_on(world.loc)  # switch off: hidden
    settings.save_settings(overhaul_install=True)
    assert service.overhaul_preview_on(world.loc)
    text = service.overhaul_switch_text("eldenring")
    assert "Lets you set up any mod as an overhaul" in text and "none for this game" not in text
    assert "Covers only" not in service.overhaul_button_tip("eldenring")


def test_a_local_config_the_player_made_is_listed(world, monkeypatch, tmp_path):
    from roundtable_souls import overhauls
    from roundtable_souls.overhauls import config as overhaul_config
    from roundtable_souls.services import mods as service

    shipped = overhaul_config.SHIPPED_DIR / "example-overhaul.toml"
    empty = tmp_path / "no-shipped"
    empty.mkdir()
    monkeypatch.setattr(overhaul_config, "SHIPPED_DIR", empty)
    folder = overhauls.local_dir()
    assert folder is not None
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "mine.toml").write_text(shipped.read_text(encoding="utf-8"), encoding="utf-8")
    assert service.installable_overhauls("eldenring") == ["Example Overhaul LITE 0.1.33-rc3"]
