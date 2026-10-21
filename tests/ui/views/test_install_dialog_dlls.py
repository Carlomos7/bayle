"""The Install mod dialog lets the player set an overhaul's DLL options before confirming (S3g)."""

from types import SimpleNamespace

from roundtable_souls.overhauls import basic
from roundtable_souls.overhauls.config import BasicNative
from roundtable_souls.ui.pages.mods.install_adapter import InstallAdapter


def test_dll_options_changed_in_the_dialog_go_into_the_config_and_ask_for_a_new_preview(qt_app, tmp_path):
    (tmp_path / "A.dll").write_bytes(b"d")
    config = basic.make(
        id="a", label="A", game="eldenring", basic=basic.propose(tmp_path, game="eldenring"), folder=tmp_path
    )
    adapter = InstallAdapter(SimpleNamespace(), SimpleNamespace())
    draft = SimpleNamespace(natives=[n.model_dump() for n in config.basic.natives], busy=False)
    adapter._draft, adapter._config, adapter._previewed = draft, config, ("setup", "a", None)
    adapter.setNative("A.dll", "early", "true")
    adapter.setNative("A.dll", "init", " Boot ")
    adapter.setNative("A.dll", "after", "false")
    assert draft.natives == [
        BasicNative(file="A.dll", load_early=True, initializer="Boot", after_others=False).model_dump()
    ]
    assert adapter._config.basic.natives[0].initializer == "Boot"
    assert adapter._previewed == () and draft.busy  # the preview is worked out again with the new options
    adapter._timer.stop()
