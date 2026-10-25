"""fix.backup: one consistent read of the save, written whole or not at all, checked before it gets its name, with
the save's timestamps (prune ages backups by mtime), under the account lock. Saves are invented bytes in tmp_path;
the backups go to the conftest's temporary data folder."""

import hashlib
import os
import threading
import time
from types import SimpleNamespace

import pytest

from bayle.adapters.filesystem.files import Unsettled
from bayle.modules.saves import backups as save_backups
from bayle.modules.saves import fix as save_fix

DATA = b"invented save bytes " * 50
DAY = 86400


@pytest.fixture
def save(tmp_path):
    p = tmp_path / "76561198000000001" / "ER0000.sl2"
    p.parent.mkdir()
    p.write_bytes(DATA)
    return p


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def age(path, days):
    t = time.time_ns() - days * DAY * 10**9
    os.utime(path, ns=(t, t))


def files_in(save):
    folder = save_backups.backups(save.parent)
    return sorted(p.name for p in folder.iterdir() if p.is_file() and p.suffix != ".lock") if folder.is_dir() else []


def stamps(monkeypatch, *values):
    """fix.backup's clock: each stamp in turn, then the last one for ever."""
    it = iter(values)
    last = []

    def strftime(fmt):
        if fmt == "%Y%m%d-%H%M%S":
            last[:] = [next(it, last[0] if last else values[-1])]
            return last[0]
        return time.strftime(fmt)

    monkeypatch.setattr(save_fix, "time", SimpleNamespace(strftime=strftime))


def test_the_backup_has_the_saves_bytes_and_its_modified_time_and_the_save_is_untouched(save):
    age(save, 3)
    before = fingerprint(save)
    bak = save_fix.backup(save)
    assert bak.read_bytes() == DATA and bak.stat().st_mtime_ns == before[1]
    assert fingerprint(save) == before
    assert save_fix.read_manifest(bak)["action"] == "Before a change"


def test_a_backup_is_ordinary_to_prune_it_ages_by_the_saves_modified_time(save, monkeypatch):
    monkeypatch.setattr(save_backups, "keep_newest", lambda: 5)
    age(save, 30)
    stamps(monkeypatch, *(f"20260101-00000{i}" for i in range(8)))
    for _ in range(8):
        save_fix.backup(save)
    kept = [n for n in files_in(save) if n.endswith(".bak")]
    assert len(kept) == 5  # the old save's backups beyond the newest five went, as before


def test_backups_of_a_recent_save_are_all_kept_by_age(save, monkeypatch):
    monkeypatch.setattr(save_backups, "keep_newest", lambda: 5)
    stamps(monkeypatch, *(f"20260101-00000{i}" for i in range(8)))
    for _ in range(8):
        save_fix.backup(save)
    assert len([n for n in files_in(save) if n.endswith(".bak")]) == 8  # younger than KEEP_DAYS: prune leaves them


def test_two_backups_in_one_second_get_distinct_names_and_both_are_kept(save, monkeypatch):
    stamps(monkeypatch, "20260101-000000")
    a, b, c = (save_fix.backup(save) for _ in range(3))
    assert [p.name for p in (a, b, c)] == [
        "ER0000.sl2.20260101-000000.bak",
        "ER0000.sl2.20260101-000000-2.bak",
        "ER0000.sl2.20260101-000000-3.bak",
    ]
    assert all(p.read_bytes() == DATA for p in (a, b, c))


def test_a_save_that_will_not_settle_makes_no_backup_and_no_folder_entry(save, monkeypatch):
    def unsettled(path):
        raise Unsettled("kept changing")

    monkeypatch.setattr(save_fix, "read_settled", unsettled)
    before = fingerprint(save)
    with pytest.raises(Unsettled):
        save_fix.backup(save)
    assert files_in(save) == [] and fingerprint(save) == before


def test_a_copy_that_does_not_read_back_the_same_is_never_kept(save, monkeypatch):
    real = save_fix.durable_write
    monkeypatch.setattr(save_fix, "durable_write", lambda dest, data, **kw: real(dest, data + b"x", **kw))
    with pytest.raises(OSError, match="did not read back"):
        save_fix.backup(save)
    assert files_in(save) == []  # no .bak, no note, no .tmp


def test_a_backup_folder_that_is_locked_for_good_fails_and_leaves_no_backup(save, monkeypatch):
    real_replace, calls = os.replace, []

    def refuse(src, dst, *a, **k):
        if str(dst).endswith(".bak"):
            calls.append(dst)
            e = PermissionError(13, "in use")
            e.winerror = 1  # type: ignore[attr-defined]  # not a sharing violation: raised at once, not waited out
            raise e
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(PermissionError):
        save_fix.backup(save)
    assert files_in(save) == [] and len(calls) == 1


def test_a_backup_replace_refused_once_with_a_sharing_violation_still_succeeds(save, monkeypatch):
    real_replace, refused = os.replace, []

    def refuse_once(src, dst, *a, **k):
        if str(dst).endswith(".bak") and not refused:
            refused.append(dst)
            e = PermissionError(13, "in use")
            e.winerror = 32  # type: ignore[attr-defined]
            raise e
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", refuse_once)
    bak = save_fix.backup(save)
    assert refused and bak.read_bytes() == DATA


def test_a_busy_account_lock_means_no_backup(save, monkeypatch):
    monkeypatch.setattr(save_backups, "LOCK_TIMEOUT", 0.2)
    folder = save_backups.backups(save.parent)
    folder.mkdir(parents=True, exist_ok=True)
    held, release = threading.Event(), threading.Event()

    def hold():
        with save_backups.account_lock(folder):
            held.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    try:
        assert held.wait(5)
        with pytest.raises(save_backups.BackupsBusy):
            save_fix.backup(save)
    finally:
        release.set()
        t.join()
    assert files_in(save) == []
