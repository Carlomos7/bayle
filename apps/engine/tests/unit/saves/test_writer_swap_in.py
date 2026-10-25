"""How saves.library.swap_in (_swap_in) puts a library copy over a live save through durable_write: the bytes, the
backup (taken only once the written copy verified), and what each failure leaves behind (the save untouched, no stray
temp file)."""

import re

import pytest
from synthetic_save import (
    OLD_MTIME_NS,
    backups_of,
    build,
    corrupt_after_replace,
    corrupt_tmp,
    disk_full_on_tmp,
    put,
    refuse_replace,
    strays,
)

from bayle.modules.games import catalog as games
from bayle.modules.saves import backups as save_backups
from bayle.modules.saves import fix as F
from bayle.modules.saves import library as Lib

ER = games.ELDEN_RING


@pytest.fixture
def world(tmp_path):
    """A live save (old) and a library entry 'run two' holding another save (new)."""
    old, new = build({0: b"old"}), build({0: b"new"})
    other = put(tmp_path / "elsewhere" / "ER0000.co2", new)
    entry = Lib.add(tmp_path, other, "run two", ER)
    live = put(tmp_path / "ER0000.sl2", old)
    return live, entry, old, new


def test_success_swaps_the_copy_in_and_keeps_the_old_save_twice(world, tmp_path):
    live, entry, old, new = world
    out = Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert live.read_bytes() == new
    assert set(out) == {"entry", "outgoing", "backup", "warning", "signed"}
    assert out["entry"]["id"] == entry["id"] and out["warning"] is None and out["signed"] is False
    outgoing = out["outgoing"]
    assert outgoing["name"] == "run one" and Lib.entry_path(tmp_path, outgoing).read_bytes() == old
    (bak,) = backups_of(live)
    assert out["backup"] == bak and re.fullmatch(r"ER0000\.sl2\.\d{8}-\d{6}\.bak", bak.name)
    assert bak.read_bytes() == old and bak.stat().st_mtime_ns == OLD_MTIME_NS
    note = F.read_manifest(bak)
    assert note["action"] == "Before swapping in 'run two'" and note["changes"] == ["run two"]
    doc = Lib.load(tmp_path)
    assert [e["name"] for e in doc["entries"]] == ["run two", "run one"]
    assert [h["action"] for h in doc["history"]] == ["save copy", "swapped out", "swap in"]
    assert doc["history"][-1] | {"when": ""} == {
        "when": "",
        "action": "swap in",
        "entry": entry["id"],
        "name": "run two",
        "target": "ER0000.sl2",
        "outgoing": outgoing["id"],
        "backup": bak.name,
    }
    assert strays(tmp_path) == []


def test_a_missing_live_file_is_just_written(world, tmp_path):
    live, entry, _, new = world
    live.unlink()
    out = Lib.swap_in(tmp_path, entry["id"], live, "x", ER)
    assert live.read_bytes() == new and out["outgoing"] is None and out["backup"] is None
    assert strays(tmp_path) == []


def test_a_busy_backup_stops_the_swap(world, tmp_path, monkeypatch):
    live, entry, old, _ = world

    def busy(*_a, **_k):
        raise save_backups.BackupsBusy("busy")

    monkeypatch.setattr(F, "backup", busy)
    with pytest.raises(save_backups.BackupsBusy):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert live.read_bytes() == old and strays(tmp_path) == []
    assert [h["action"] for h in Lib.load(tmp_path)["history"]] == ["save copy", "swapped out"]  # no "swap in" line


def test_today_the_outgoing_library_copy_comes_first_and_stays_when_the_swap_fails(world, tmp_path, monkeypatch):
    # stays true after the switch: the outgoing library copy is a new file, not the live save
    live, entry, old, _ = world
    monkeypatch.setattr(F, "backup", lambda *_a, **_k: (_ for _ in ()).throw(save_backups.BackupsBusy("busy")))
    with pytest.raises(save_backups.BackupsBusy):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    outgoing = next(e for e in Lib.load(tmp_path)["entries"] if e["name"] == "run one")
    assert Lib.entry_path(tmp_path, outgoing).read_bytes() == old


def test_a_failed_check_leaves_the_save_untouched_and_takes_no_backup(world, tmp_path, monkeypatch):
    live, entry, old, _ = world
    corrupt_tmp(monkeypatch, live, 0x400)
    with pytest.raises(Lib.LibraryError):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert live.read_bytes() == old and backups_of(live) == [] and strays(tmp_path) == []


def test_a_read_back_mismatch_after_the_replace_is_reported(world, tmp_path, monkeypatch):
    # today and after the switch (after=): an error, the new file stays in place, the backup is kept
    live, entry, old, new = world
    corrupt_after_replace(monkeypatch, live)
    with pytest.raises(Lib.LibraryError, match="did not read back the same"):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert live.read_bytes() != new
    (bak,) = backups_of(live)
    assert bak.read_bytes() == old


def test_a_replace_refused_once_is_retried_and_written(world, tmp_path, monkeypatch):
    live, entry, _, new = world
    refuse_replace(monkeypatch, live, times=1)
    Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert live.read_bytes() == new


def test_a_replace_refused_for_good_keeps_the_save_and_its_backup(world, tmp_path, monkeypatch):
    live, entry, old, _ = world
    refuse_replace(monkeypatch, live)
    with pytest.raises(PermissionError):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    (bak,) = backups_of(live)
    assert live.read_bytes() == old and bak.read_bytes() == old


def test_a_replace_refused_for_good_leaves_no_temp_file(world, tmp_path, monkeypatch):
    live, entry, *_ = world
    refuse_replace(monkeypatch, live)
    with pytest.raises(PermissionError):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert strays(tmp_path) == []


def test_disk_full_leaves_the_save_untouched(world, tmp_path, monkeypatch):
    live, entry, old, _ = world
    disk_full_on_tmp(monkeypatch, live)
    with pytest.raises(OSError, match="No space"):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert live.read_bytes() == old


def test_disk_full_leaves_no_temp_file(world, tmp_path, monkeypatch):
    live, entry, *_ = world
    disk_full_on_tmp(monkeypatch, live)
    with pytest.raises(OSError):
        Lib.swap_in(tmp_path, entry["id"], live, "run one", ER)
    assert strays(tmp_path) == []
