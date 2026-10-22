"""The Install mod dialog lets the player set an overhaul's DLL options before confirming (S3g). The draft is the
session's; the dialog's adapter sends each edit and asks for the new preview after its pause."""

from types import SimpleNamespace

from bayle.overhauls import basic
from bayle.overhauls.config import BasicNative
from bayle.services import mods as mod_service
from bayle.session import EventBus, JobManager, PlanStore, Session
from bayle.session import ops as _registered_operations  # noqa: F401
from bayle.session.ops.mods_install import DraftState, drafts
from bayle.ui.pages.mods.install_adapter import InstallAdapter
from bayle.views.mod_install import InstallDraft
from support import er, mods_profile


def test_dll_options_changed_in_the_dialog_go_into_the_config_and_ask_for_a_new_preview(qt_app, tmp_path):
    profile = mods_profile(tmp_path / "p")
    dll = tmp_path / "dl" / "A.dll"
    dll.parent.mkdir()
    dll.write_bytes(b"d")
    config = basic.make(
        id="a", label="A", game="eldenring", basic=basic.propose(dll.parent, game="eldenring"), folder=dll.parent
    )
    session = Session(JobManager(EventBus(), spawn=lambda run, name=None: run()), plans=PlanStore(), locations=er)
    plan = mod_service.plan_mod_install(profile, dll, loc=er())
    state = DraftState(InstallDraft(plan, profile, overhaul_on=True), profile)
    state.draft.natives = [n.model_dump() for n in config.basic.natives]
    state.config, state.previewed = config, ("setup", "a", None)
    draft_id = drafts(session).add(state)
    adapter = InstallAdapter(SimpleNamespace(session=session), SimpleNamespace())
    adapter._draft = draft_id
    adapter.setNative("A.dll", "early", "true")
    adapter.setNative("A.dll", "init", " Boot ")
    adapter.setNative("A.dll", "after", "false")
    assert state.draft.natives == [
        BasicNative(file="A.dll", load_early=True, initializer="Boot", after_others=False).model_dump()
    ]
    assert state.config.basic.natives[0].initializer == "Boot"
    assert state.previewed == () and state.draft.busy  # the preview is worked out again with the new options
    assert adapter._view["busy"] and adapter._timer.isActive()  # after the dialog's pause
    adapter._timer.stop()


def test_a_download_is_opened_edited_planned_again_and_installed_through_the_adapter(qt_app, tmp_path):
    from test_mods_view import Host

    from bayle.services.mods import profile_entries
    from bayle.ui.notifications import Notifier

    profile = mods_profile(tmp_path / "p")
    src = tmp_path / "dl" / "grass"
    (src / "parts").mkdir(parents=True)
    (src / "parts" / "grass.partsbnd.dcx").write_bytes(b"g")
    host, toasts = Host(profile), []
    notifier = Notifier()
    notifier.toastRequested.connect(lambda text, error: toasts.append(text))
    adapter, shown = InstallAdapter(host, notifier), []
    adapter.openRequested.connect(lambda: shown.append(adapter._view["title"]))
    adapter._add([src, tmp_path / "notes.txt"])
    assert shown == ["Install grass"] and toasts == [
        "Skipped notes.txt: not an archive (.zip, .7z, .rar), a .dll or a folder."
    ]
    adapter.setName("grass2")
    assert adapter._timer.isActive() and adapter._view["busy"] and not adapter.accept()  # waits for the plan
    adapter._timer.stop()
    adapter._refresh()
    assert adapter._view["canInstall"] and adapter.accept()
    assert host.jobs == ["Installing grass2..."] and adapter._view == {}
    assert "grass2" in [e["name"] for e in profile_entries(profile)]
