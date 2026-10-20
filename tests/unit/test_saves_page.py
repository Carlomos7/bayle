"""The Saves page's safety: nothing is written while the game runs, and Check & repair's ticked boxes become the
right writes. The repair test runs on a temporary COPY of a real save (skipped without one)."""

import pytest

from roundtable_souls.game.locate import Locations
from roundtable_souls.saves import fix as F
from roundtable_souls.saves import layout as L
from roundtable_souls.services import saves as service
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.saves.adapter import SavesAdapter, apply_repairs
from roundtable_souls.ui.pages.saves.presenter import SavesPresenter
from support import copy_live_save, er


class Host:
    busy = False
    game_running = True
    locations = er()

    def __init__(self):
        self.jobs = []

    def run_job(self, job, status):
        self.jobs.append(status)

    def run_in_background(self, work, on_result):
        raise AssertionError("a refused write must not plan anything")

    def pick_file(self, title, filters):
        raise AssertionError("a refused write must not ask for a file")

    def open_path(self, path):
        pass

    def saves_in_use(self):
        return {}


WRITES = [
    ("backUpNow", ("x.sl2",)),
    ("saveCopy", ("x.sl2", "name")),
    ("importFile", ("x.sl2", "name")),
    ("copyCharacter", ("a.sl2", 1, "b.sl2", 2)),
    ("replaceFromLibrary", ("folder", "id", "b.sl2")),
    ("replaceFromFile", ("b.sl2",)),
    ("restoreBackup", ("a.bak", "b.sl2")),
    ("applyRepair", ()),
    ("postSessionRepair", ()),
]


@pytest.mark.parametrize(("slot", "args"), WRITES)
def test_no_write_slot_runs_while_the_game_is_running(slot, args, monkeypatch):
    for name in ("back_up_now", "assert_writable", "fix_checksums", "restore_backup", "fix_loading"):
        monkeypatch.setattr(service, name, lambda *a, **k: pytest.fail("a service was called"))
    host, notifier, told = Host(), Notifier(), []
    notifier.toastRequested.connect(lambda text, error: told.append((text, error)))
    getattr(SavesAdapter(host, notifier), slot)(*args)
    assert host.jobs == [] and len(told) == 1 and told[0][1]
    assert "running" in told[0][0] or "Close" in told[0][0]


def test_check_and_repair_signs_a_stale_slot_and_the_first_backup_is_the_file_before(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    save = copy_live_save(tmp_path)
    active = [i for i, on in enumerate(L.parse(str(save))["ud10"]["active"]) if on]
    if not active:
        pytest.skip("this save has no characters")
    data = bytearray(save.read_bytes())
    start = L.HEADER + active[0] * F.SLOT_STRIDE
    data[start : start + 0x10] = bytes(16)  # that slot's checksum goes stale
    save.write_bytes(bytes(data))
    before = save.read_bytes()
    presenter = SavesPresenter()
    groups = presenter.repair_groups(service.save_info(save, loc=er()))
    ticked = [i["tuple"] for g in groups for i in g["items"] if i["checked"]]
    assert ("checksum", active[0]) in ticked
    first = apply_repairs(save, presenter.calls(ticked), loc=er())
    after = L.parse(str(save))
    assert all(after["slot_md5_ok"][i] for i in active) and after["ud10_md5_ok"]
    assert first is not None and first.read_bytes() == before
