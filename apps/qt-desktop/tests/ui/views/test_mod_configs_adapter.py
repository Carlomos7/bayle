"""The Mod Configs adapter against the engine's Mod configs interface: the tree, a Seamless Co-op file, a save and a
paste, the stale refusal, the overhaul plans and the export job, no window. The host fake has no session: a page that
reached for one would fail."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from bayle.platform.threads import as_worker
from bayle.services.mod_configs import ModConfigsService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from PySide6.QtCore import QCoreApplication
from test_mod_configs_ops import other_of
from test_overhaul_install import PROFILE, World, mixed_mod

from bayle_qt.pages.mod_configs.adapter import ModConfigsAdapter


class Rig:
    def __init__(self, world: World):
        QCoreApplication.instance() or QCoreApplication([])
        self.world = world
        self.jobs = JobManager(EventBus(), spawn=lambda run, name=None: run())
        self.service = ModConfigsService(self.jobs, lambda: world.loc)
        self.toasts: list[tuple[str, bool]] = []
        self.asked: list = []
        self.words: list = []
        self.picked: Path | None = None
        self.saved_to: Path | None = None
        self.settings_keys: list[str] = []
        notifier = SimpleNamespace(
            toast=lambda text, error=False: self.toasts.append((text, error)),
            confirm=lambda words, then, destructive=False: (self.words.append(words), self.asked.append(then)),
            ask=lambda *a, **k: None,
        )
        host = SimpleNamespace(
            busy=False,
            profile=world.profile,
            features=SimpleNamespace(mod_configs=self.service),
            run_in_background=self._background,
            follow_job=lambda job_id, done: done(self.jobs.get(job_id)),
            settings_changed=self.settings_keys.append,
            pick_file=lambda title, filters: self.picked,
            save_file=lambda title, name: self.saved_to,
        )
        self.page = ModConfigsAdapter(host, notifier)  # pyright: ignore[reportArgumentType]
        self.page.refresh()

    @staticmethod
    def _background(work, done) -> None:
        with as_worker():  # inline here, a worker thread in the window
            got = work()
        done(got)


@pytest.fixture
def world(tmp_path, monkeypatch):
    return World(tmp_path, monkeypatch)


def ini_of(world) -> Path:
    ini = world.base / "natives/SeamlessCoop/ersc_settings.ini"
    ini.write_text("[PASSWORD]\ncooppassword = room\n", encoding="utf-8")
    return ini


def test_the_page_reads_opens_saves_and_pastes_through_the_engine(world):
    ini = ini_of(world)
    r = Rig(world)
    page = r.page
    assert page.hasProfile and page.nodes[0]["key"] == "seamless"  # pyright: ignore[reportIndexIssue]
    assert page.fileKind == "seamless" and page.selectedFile == str(ini)
    page.setValue("PASSWORD", "cooppassword", "new")
    assert page.dirty
    page.save()
    assert "cooppassword = new" in ini.read_text(encoding="utf-8") and not page.dirty
    page._take_shared("cooppassword = pasted\n")
    assert r.asked  # asks before writing
    r.asked[0](True)
    assert "cooppassword = pasted" in ini.read_text(encoding="utf-8")
    assert r.toasts[-1][1] is False
    page.setValue("PASSWORD", "cooppassword", " ")
    page.save()
    assert r.toasts[-1][1] and "password" in r.toasts[-1][0].lower()  # an empty password is refused, in words


def test_a_file_that_changed_after_it_was_opened_is_refused_as_stale_in_words(world):
    ini = ini_of(world)
    r = Rig(world)
    r.page.setValue("PASSWORD", "cooppassword", "mine")
    ini.write_text("[PASSWORD]\ncooppassword = theirs\n", encoding="utf-8")  # another program, meanwhile
    r.page.save()
    assert "changed on disk" in r.toasts[-1][0] and r.toasts[-1][1]
    assert "cooppassword = theirs" in ini.read_text(encoding="utf-8")  # nothing was overwritten


def test_pasting_into_a_file_that_changed_since_the_question_is_refused(world):
    ini = ini_of(world)
    r = Rig(world)
    r.page._take_shared("cooppassword = pasted\n")
    ini.write_text("[PASSWORD]\ncooppassword = other\n", encoding="utf-8")
    r.asked[0](True)
    assert r.toasts[-1][1] and "cooppassword = other" in ini.read_text(encoding="utf-8")
    r.toasts.clear()
    r.page._take_shared("cooppassword = other\n")  # the same as the file: nothing to ask
    assert not r.asked[1:] and "matches" in r.toasts[-1][0]


def test_attach_and_detach_tell_the_host_the_settings_changed(world):
    other_of(world)
    r = Rig(world)
    extra = world.tmp / "extra.txt"
    extra.write_text("x", encoding="utf-8")
    node = next(n for n in r.page._nodes if n.name == "other.dll")
    r.page._node = node
    r.picked = extra
    r.page.attachFile()
    assert r.settings_keys == ["native_configs"]
    assert any(f.how == "attached" for n in r.page._nodes for f in n.files)
    r.page.detachFile(str(extra))
    assert r.settings_keys == ["native_configs"] * 2
    assert not any(f.how == "attached" for n in r.page._nodes for f in n.files)


def test_saving_the_settings_to_a_file_is_a_job_the_page_follows(world):
    ini = ini_of(world)
    r = Rig(world)
    out = world.tmp / "friend.ini"
    r.saved_to = out
    r.page.saveSettingsAs()
    assert out.read_text(encoding="utf-8").startswith("[PASSWORD]") and r.toasts[-1] == ("Saved friend.ini", False)
    r.saved_to = world.tmp  # a folder: the job fails with its code
    r.page.saveSettingsAs()
    assert r.toasts[-1][1] and ini.read_text(encoding="utf-8").startswith("[PASSWORD]")


def test_a_mod_is_set_up_as_an_overhaul_and_turned_off_through_the_plans(world):
    folder = mixed_mod(world)
    inside = world.base / "Mixed Mod"
    folder.rename(inside)
    world.profile.write_text(PROFILE + "\n[[packages]]\nid = 'mixed'\npath = 'Mixed Mod'\n", encoding="utf-8")
    r = Rig(world)
    page = r.page
    page._start_new({"name": "Mixed Mod", "id": "", "folder": inside})
    assert page.fileKind == "overhaul" and page.dirty
    page.save()  # asks first
    assert r.words and r.words[-1].apply == "Set up" and "mixed-mod" not in world.profile.read_text(encoding="utf-8")
    r.asked[-1](True)
    assert "mixed-mod" in world.profile.read_text(encoding="utf-8") and "set up as an overhaul" in r.toasts[-1][0]
    assert any(n.kind == "overhaul" for n in page._nodes)  # the tree was read again
    page.selectFile("overhaul", str(next(n for n in page._nodes if n.kind == "overhaul").files[0].path))
    page.turnOffOverhaul()
    assert r.words[-1].apply == "Turn off"
    r.asked[-1](True)
    assert not any(n.kind == "overhaul" for n in page._nodes) and "Turned off" in r.toasts[-1][0]


def test_a_plan_that_cannot_go_ahead_is_said_not_asked(world):
    r = Rig(world)
    r.page._node = SimpleNamespace(kind="overhaul", setup={"verified": False}, key="overhaul")  # pyright: ignore[reportAttributeAccessIssue]
    r.page.turnOffOverhaul()  # the profile has no overhaul
    assert not r.asked and r.toasts[-1][1]
