"""The Install mod dialog's adapter against the engine's ModInstallService: open, edit, preview, install, close, the
stale profile asked once more and a failed install's error. The service is a scripted fake (what the adapter sends and
how it words the answers) and the real one over folders under tmp_path (the profile and the download are invented)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_mods_view import Host

from bayle.errors import OperationError
from bayle.services import profile_mods
from bayle.services.mod_configs import stamp
from bayle.services.mod_install import OpenedInstall, OverhaulChoices, OverhaulPlan, OverhaulPreview, Sources
from bayle.services.mods import profile_entries
from bayle.ui.notifications import Notifier
from bayle.ui.pages.mods import take_over
from bayle.ui.pages.mods.install_adapter import InstallAdapter
from support import mods_profile

TABLE_FILE = "msg/{each}/menu.msgbnd.dcx"
NATIVE = {"file": "A.dll", "load_early": False, "after_others": False, "initializer": None}
OVERHAUL_PLAN = {
    "name": "Big",
    "id": "big",
    "kind": "package",
    "assets": ["parts"],
    "size": 10,
    "dest": "",
    "contents": [],
    "overhaul_hint": {"reason": "installer", "file": "setup.exe"},
    "option": "suggested",
}


class FakeInstall:
    """The engine's ModInstallService as far as the dialog uses it, recording what it is asked."""

    def __init__(self, plan: dict, profile: Path, *, overhaul_on: bool = True):
        self.plan, self.profile, self.overhaul_on = plan, profile, overhaul_on
        self.previews: list = []  # (name, setup) of each check_overhaul
        self.installed: list = []  # (install_id, choices, expect)
        self.closed: list = []
        self.stale_once = False

    def sources(self, paths):
        return Sources(tuple(paths), ())

    def open(self, profile, source):
        return OpenedInstall(
            "i1", dict(self.plan, dest=str(self.profile.parent / "mod" / "Big")), self.overhaul_on, stamp(self.profile)
        )

    def replan(self, install_id, name, id, variant):
        return dict(self.plan, name=name, id=id)

    def check_overhaul(self, install_id, name, setup=None):
        self.previews.append((name, setup))
        table = (setup.tables if setup else {}).get(TABLE_FILE, "")
        natives = tuple(setup.natives) if setup else (dict(NATIVE),)
        texts = ({"file": TABLE_FILE, "table": table, "tables": ["t1", "t2"]},)
        return OverhaulPreview("setup", ("Set up Big",), ("a note",), (), natives, (), texts, True)

    def install(self, install_id, choices, expect):
        if self.stale_once:
            self.stale_once = False
            raise OperationError("stale", "The profile changed since you were asked. Ask again.")
        self.installed.append((install_id, choices, expect))
        return "j1"

    def close(self, install_id):
        self.closed.append(install_id)


def adapter_over(host) -> tuple[InstallAdapter, list, list]:
    notifier, toasts, asked = Notifier(), [], []
    notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
    notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
    adapter = InstallAdapter(host, notifier)
    return adapter, toasts, asked


def fake_host(tmp_path, **kw):
    profile = mods_profile(tmp_path / "p")
    host = Host(profile)
    fake = FakeInstall(OVERHAUL_PLAN, profile, **kw)
    host.features = SimpleNamespace(mod_install=fake)
    return host, fake, profile


def test_the_overhaul_preview_and_the_setup_edits_go_to_the_engine_and_come_back_with_the_install(qt_app, tmp_path):
    host, fake, _profile = fake_host(tmp_path)
    adapter, toasts, _asked = adapter_over(host)
    adapter._add([tmp_path / "big"])
    view = adapter._view
    assert view["mode"] == "setup" and view["overhaul"]["ready"] and view["overhaul"]["lines"] == ["Set up Big"]
    assert fake.previews == [("Big", None)]  # the engine's own setup, as proposed
    assert [n["file"] for n in view["natives"]] == ["A.dll"]
    assert view["texts"][0]["table"] == "" and not view["canInstall"]  # a texts entry still needs its table
    assert view["overhaul"]["refusals"] == [
        "Choose the table for the texts added to msg/<language>/menu.msgbnd.dcx before installing."
    ]
    adapter.setTable(TABLE_FILE, "t2")
    adapter.setNative("A.dll", "init", " Boot ")
    assert adapter._view["busy"] and adapter._timer.isActive() and not adapter.accept()
    adapter._timer.stop()
    adapter._refresh()
    name, setup = fake.previews[-1]
    assert setup.tables == {TABLE_FILE: "t2"} and setup.natives[0]["initializer"] == "Boot"
    assert adapter._view["canInstall"] and adapter.accept() and adapter._view == {}
    ((install_id, choices, expect),) = fake.installed
    assert install_id == "i1" and choices.overhaul and choices.name == "Big" and choices.setup == setup
    assert expect == stamp(host.profile) and toasts == []


def test_an_edit_made_while_the_engine_is_asked_is_asked_again_and_the_old_answer_is_dropped(qt_app, tmp_path):
    host, fake, _profile = fake_host(tmp_path)
    adapter, _toasts, _asked = adapter_over(host)
    adapter._add([tmp_path / "big"])
    pending: list = []
    host.run_in_background = lambda work, landed: pending.append((work, landed))  # the worker, run by hand
    adapter.setTable(TABLE_FILE, "t1")
    adapter._timer.stop()
    adapter._refresh()
    assert len(pending) == 1  # the preview is out (the key is unchanged: no replan)
    adapter.setNative("A.dll", "early", "true")  # an edit while it is out
    adapter._timer.stop()
    adapter._refresh()
    assert adapter._again and len(pending) == 1
    work, landed = pending.pop(0)
    landed(work())
    assert adapter._view["busy"] and adapter._view["natives"][0]["load_early"] is True  # the old answer was dropped
    assert len(pending) == 1  # and the engine is asked again
    work, landed = pending.pop(0)
    landed(work())
    assert not adapter._view["busy"] and not pending
    assert fake.previews[-1][1].natives[0]["load_early"] is True


def test_closing_the_dialog_drops_the_open_install_and_a_cancelled_one_installs_nothing(qt_app, tmp_path):
    host, fake, _profile = fake_host(tmp_path)
    adapter, _toasts, _asked = adapter_over(host)
    adapter._add([tmp_path / "big"])
    adapter.dialogClosed()
    assert fake.closed == ["i1"] and adapter._view == {} and fake.installed == []


def test_a_profile_that_changed_while_the_dialog_was_open_asks_once_more_and_installs_on_yes(qt_app, tmp_path):
    host, fake, _profile = fake_host(tmp_path)
    adapter, toasts, asked = adapter_over(host)
    adapter._add([tmp_path / "big"])
    adapter.setTable(TABLE_FILE, "t1")
    adapter._timer.stop()
    adapter._refresh()
    fake.stale_once = True
    assert adapter.accept()
    token, words = asked[-1]
    assert words["title"] == "Install Big now?" and fake.installed == []
    adapter.notifier.answerWith(token, True, False)
    assert len(fake.installed) == 1 and fake.installed[0][2] == stamp(host.profile) and toasts == []
    # a second stale answer is told, not asked again
    adapter._add([tmp_path / "big"])
    adapter.setTable(TABLE_FILE, "t1")
    adapter._timer.stop()
    adapter._refresh()
    fake.stale_once = True
    assert adapter.accept()
    adapter.notifier.answerWith(asked[-1][0], False, False)  # declined: the download is let go
    assert fake.closed == ["i1"] and len(fake.installed) == 1


# ---- on the real service
def real_host(tmp_path):
    profile = mods_profile(tmp_path / "p")
    src = tmp_path / "dl" / "grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.partsbnd.dcx").write_bytes(b"g")
    return Host(profile), profile, src


def test_a_download_edited_in_the_dialog_is_installed_by_the_real_service(qt_app, tmp_path):
    host, profile, src = real_host(tmp_path)
    adapter, toasts, _asked = adapter_over(host)
    adapter._add([src])
    assert adapter._view["title"] == "Install grass" and adapter._view["canInstall"]
    adapter.setName("grass2")
    adapter.setId("flora2")
    assert not adapter.accept()  # waits for the plan of what was typed
    adapter._timer.stop()
    adapter._refresh()
    assert adapter._view["title"] == "Install grass2" and adapter.accept()
    assert host.jobs == ["Installing grass2..."] and toasts == []
    assert "flora2" in [e["name"] for e in profile_entries(profile)]  # the id the player typed
    assert (profile.parent / "mod" / "grass2" / "parts" / "grass.partsbnd.dcx").is_file()


def test_the_real_service_lets_a_closed_install_go(qt_app, tmp_path):
    host, _profile, src = real_host(tmp_path)
    adapter, _toasts, _asked = adapter_over(host)
    adapter._add([src])
    install_id = adapter._draft.install_id
    adapter.dialogClosed()
    with pytest.raises(OperationError) as gone:
        host.features.mod_install.close(install_id)
    assert gone.value.code == "unknown_install" and host.jobs == []


def test_the_real_service_asks_again_when_the_profile_changed_under_the_dialog(qt_app, tmp_path):
    host, profile, src = real_host(tmp_path)
    adapter, toasts, asked = adapter_over(host)
    adapter._add([src])
    with profile.open("ab") as f:
        f.write(b"\n# edited elsewhere\n")
    assert adapter.accept() and host.jobs == []
    token, words = asked[-1]
    assert words["title"] == "Install grass now?"
    adapter.notifier.answerWith(token, True, False)
    assert host.jobs == ["Installing grass..."] and toasts == []
    assert "grass" in [e["name"] for e in profile_entries(profile)]


def test_a_failed_install_tells_why_and_leaves_the_profile_as_it_was(qt_app, tmp_path, monkeypatch):
    host, profile, src = real_host(tmp_path)
    adapter, toasts, _asked = adapter_over(host)
    before = profile.read_bytes()

    def boom(*a, **k):
        raise OperationError("disk_full", "The disk is full.")

    monkeypatch.setattr(profile_mods, "install_and_record", boom)
    adapter._add([src])
    assert adapter.accept()
    assert len(toasts) == 1 and toasts[0][1] is True
    assert toasts[0][0].startswith("Could not install grass: ") and "disk" in toasts[0][0].lower()
    assert profile.read_bytes() == before
    with pytest.raises(OperationError) as gone:
        host.features.mod_install.close("i1")  # the failed job ended the install too
    assert gone.value.code == "unknown_install"


# ---- Take over (the Mods page is stubbed: its own tests run with its adapter)
class FakeTakeOver:
    def __init__(self, rows=("a change",), ok=True, stale_once=False):
        self.rows, self.ok, self.stale_once = rows, ok, stale_once
        self.checked, self.started = [], []

    def take_over_choices(self, profile):
        return OverhaulChoices("Reborn", tuple(self.rows), (0,) if self.rows else ())

    def check_take_over(self, profile, chosen):
        self.checked.append(list(chosen))
        refusals = () if self.ok else ("Reborn is running.",)
        return OverhaulPlan("Reborn", ("Put its files back",), (), refusals, ("Seamless",), False, (1, 2))

    def take_over(self, profile, chosen, revert, expect):
        if self.stale_once:
            self.stale_once = False
            raise OperationError("stale", "The profile changed since you were asked. Ask again.")
        self.started.append((list(chosen), revert, expect))
        return "j1"


def take_over_page(tmp_path, service):
    host = Host(mods_profile(tmp_path / "p"))
    host.features = SimpleNamespace(mod_install=service)
    notifier, toasts, asked = Notifier(), [], []
    notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
    notifier.confirmFullRequested.connect(lambda token, words: asked.append((token, words)))
    picks: list = []
    page = SimpleNamespace(
        host=host,
        notifier=notifier,
        _view=SimpleNamespace(overhaul_info=SimpleNamespace(takeover=True, label="Reborn")),
        _ready=lambda: host.profile,
        _show_pick=lambda prompt, then: picks.append((prompt, then)),
    )
    return page, host, toasts, asked, picks


def test_take_over_offers_the_rows_confirms_with_the_words_and_starts_with_the_stamp(qt_app, tmp_path):
    service = FakeTakeOver()
    page, host, toasts, asked, picks = take_over_page(tmp_path, service)
    take_over.start(page)
    ((prompt, then),) = picks
    assert prompt["title"] == "Take over Reborn: what to put back?" and prompt["rows"] == ["a change"]
    assert prompt["ticked"] == [0] and prompt["none"] == "Leave them"
    then([0])
    token, words = asked[-1]
    assert words["title"] == "Take over Reborn in main.me3" and words["changes"] == ["Put its files back"]
    assert words["option"] == "Also switch Seamless back off, as it was before the install"
    host.follow_job = lambda job_id, done: done(SimpleNamespace(state="done"))
    page.notifier.answerWith(token, True, True)
    assert service.started == [([0], True, (1, 2))]
    assert asked[-1][1]["title"] == "Install Reborn with the launcher now?"  # offered once it is done


def test_take_over_with_nothing_to_pick_asks_at_once_and_says_a_refusal_in_words(qt_app, tmp_path):
    service = FakeTakeOver(rows=(), ok=False)
    page, _host, toasts, asked, picks = take_over_page(tmp_path, service)
    take_over.start(page)
    assert not picks and not asked and service.checked == [[]]
    assert toasts == [("Can't take over Reborn. Reborn is running.", True)]


def test_take_over_asks_once_more_when_the_profile_changed_between_the_question_and_yes(qt_app, tmp_path):
    service = FakeTakeOver(rows=(), stale_once=True)
    page, host, toasts, asked, _picks = take_over_page(tmp_path, service)
    host.follow_job = lambda job_id, done: done(None)
    take_over.start(page)
    page.notifier.answerWith(asked[-1][0], True, False)
    assert service.started == [] and len(asked) == 2  # stale: the fresh words are asked
    page.notifier.answerWith(asked[-1][0], True, False)
    assert service.started == [([], False, (1, 2))] and toasts == []
