"""The Mod Configs adapter against a real Session: the tree, a Seamless Co-op file, a save and a paste, no window."""

from types import SimpleNamespace

from PySide6.QtCore import QCoreApplication
from test_overhaul_install import World

from bayle.session import Session
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.ui.pages.mod_configs.adapter import ModConfigsAdapter
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager
from bayle.work.prompts import PlanStore


def test_the_page_reads_opens_saves_and_pastes_through_the_session(tmp_path, monkeypatch):
    QCoreApplication.instance() or QCoreApplication([])
    world = World(tmp_path, monkeypatch)
    ini = world.base / "natives/SeamlessCoop/ersc_settings.ini"
    ini.write_text("[PASSWORD]\ncooppassword = room\n", encoding="utf-8")
    session = Session(
        JobManager(EventBus(), spawn=lambda run, name=None: run()), plans=PlanStore(), locations=lambda: world.loc
    )
    toasts, asked = [], []
    notifier = SimpleNamespace(
        toast=lambda text, error=False: toasts.append((text, error)),
        confirm=lambda words, then, destructive=False: asked.append(then),
        ask=lambda *a, **k: None,
    )
    host = SimpleNamespace(
        busy=False,
        profile=world.profile,
        session=session,
        run_in_background=lambda work, done: done(work()),
        settings_changed=lambda key: None,
    )
    page = ModConfigsAdapter(host, notifier)  # pyright: ignore[reportArgumentType]
    page.refresh()
    assert page.hasProfile and page.nodes[0]["key"] == "seamless"  # pyright: ignore[reportIndexIssue]
    assert page.fileKind == "seamless" and page.selectedFile == str(ini)
    page.setValue("PASSWORD", "cooppassword", "new")
    assert page.dirty
    page.save()
    assert "cooppassword = new" in ini.read_text(encoding="utf-8") and not page.dirty
    page._take_shared("cooppassword = pasted\n")
    assert asked  # asks before writing
    asked[0](True)
    assert "cooppassword = pasted" in ini.read_text(encoding="utf-8")
    page.setValue("PASSWORD", "cooppassword", " ")
    page.save()
    assert toasts[-1][1]  # an empty password is refused
