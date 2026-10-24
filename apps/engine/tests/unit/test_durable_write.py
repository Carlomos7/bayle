"""platform.files.durable_write: the new bytes land whole after the caller's checks and backup, or nothing changes;
the temp file never outlives a failed write and never takes the target's name."""

import os
import stat
import subprocess
import sys
import threading

import pytest

from bayle.platform.files import atomic_write, durable_write


def sharing_violation(winerror=32):
    e = PermissionError(13, "The process cannot access the file because it is being used by another process")
    e.winerror = winerror  # type: ignore[attr-defined]  # set by hand so the test runs off Windows too
    return e


@pytest.fixture
def target(tmp_path):
    p = tmp_path / "save.sl2"
    p.write_bytes(b"original \x00\xff bytes")
    return p


def names(folder):
    return sorted(f.name for f in folder.iterdir())


def test_str_and_bytes_land_as_given(tmp_path):
    p = tmp_path / "a.txt"
    durable_write(p, "line\r\nnext\né")
    assert p.read_bytes() == "line\r\nnext\né".encode()
    durable_write(p, b"\x00\x01\xfe")
    assert p.read_bytes() == b"\x00\x01\xfe" and names(tmp_path) == ["a.txt"]


def test_hooks_run_in_order_and_the_backup_hooks_result_is_returned(target):
    seen = []

    def verify(tmp):
        seen.append(("verify", tmp.read_bytes(), target.read_bytes()))

    def backup():
        seen.append(("backup",))
        return "bak-path"

    assert durable_write(target, b"new", verify=verify, before_replace=backup, after=lambda p: seen.append(p)) == (
        "bak-path"
    )
    assert seen == [("verify", b"new", b"original \x00\xff bytes"), ("backup",), target]


def test_a_failed_verify_leaves_the_target_and_no_temp_file(target):
    before = target.read_bytes()
    backups = []

    def verify(tmp):
        raise ValueError("checksum mismatch")

    with pytest.raises(ValueError):
        durable_write(target, b"bad", verify=verify, before_replace=lambda: backups.append(1))
    assert target.read_bytes() == before and backups == [] and names(target.parent) == ["save.sl2"]


def test_a_failed_backup_leaves_the_target_and_no_temp_file(target, monkeypatch):
    before = target.read_bytes()
    replaced = []
    monkeypatch.setattr(os, "replace", lambda *a: replaced.append(a))

    def backup():
        raise OSError("backup folder full")

    with pytest.raises(OSError, match="backup folder full"):
        durable_write(target, b"new", before_replace=backup)
    assert replaced == [] and target.read_bytes() == before and names(target.parent) == ["save.sl2"]


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_a_refused_replace_is_retried_until_it_goes_through(target, monkeypatch, winerror):
    real = os.replace
    tries = []

    def replace(src, dst):
        tries.append(1)
        if len(tries) <= 3:
            raise sharing_violation(winerror)
        real(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    durable_write(target, b"new")
    assert len(tries) == 4 and target.read_bytes() == b"new" and names(target.parent) == ["save.sl2"]


def test_a_replace_refused_for_good_raises_and_leaves_the_target(target, monkeypatch):
    before = target.read_bytes()
    tries = []

    def replace(src, dst):
        tries.append(1)
        raise sharing_violation()

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(PermissionError):
        durable_write(target, b"new", retry_for=0.2)
    assert len(tries) > 1 and target.read_bytes() == before and names(target.parent) == ["save.sl2"]


@pytest.mark.parametrize(
    "error", [OSError(28, "No space left on device"), PermissionError(13, "Access is denied")], ids=["disk", "acl"]
)
def test_any_other_replace_error_raises_at_once(target, monkeypatch, error):
    before = target.read_bytes()
    tries = []

    def replace(src, dst):
        tries.append(1)
        raise error

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(OSError):
        durable_write(target, b"new")
    assert tries == [1] and target.read_bytes() == before and names(target.parent) == ["save.sl2"]


def test_a_failed_after_check_raises_and_keeps_the_new_file(target):
    # Documented: no roll-back; the caller's backup (before_replace) is its recovery.
    def after(p):
        raise ValueError("re-read failed")

    with pytest.raises(ValueError):
        durable_write(target, b"new", after=after)
    assert target.read_bytes() == b"new" and names(target.parent) == ["save.sl2"]


def test_an_existing_bak_survives_a_failed_write(target, monkeypatch):
    bak = target.with_name(target.name + ".bak")
    bak.write_bytes(b"older backup")

    def verify(tmp):
        raise ValueError("bad")

    with pytest.raises(ValueError):
        durable_write(target, b"new", verify=verify)
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError(28, "No space left on device")))
    with pytest.raises(OSError):
        durable_write(target, b"new")
    assert bak.read_bytes() == b"older backup" and names(target.parent) == ["save.sl2", "save.sl2.bak"]


def test_atomic_write_backup_keeps_one_bak_of_the_previous_file(tmp_path):
    p = tmp_path / "settings.ini"
    atomic_write(p, "one", backup=True)
    assert names(tmp_path) == ["settings.ini"]  # nothing to back up yet
    atomic_write(p, "two", backup=True)
    atomic_write(p, "three", backup=True)
    assert p.read_text() == "three" and (tmp_path / "settings.ini.bak").read_text() == "two"
    assert names(tmp_path) == ["settings.ini", "settings.ini.bak"]


def test_two_writers_at_once_leave_one_complete_result(tmp_path):
    p = tmp_path / "library.json"
    payloads = [bytes([65 + i]) * 1_000_000 for i in range(2)]
    errors: list[BaseException] = []
    start = threading.Barrier(2)

    def writer(data):
        start.wait()
        for _ in range(10):
            try:
                durable_write(p, data, verify=lambda tmp: tmp.stat().st_size == len(data) or 1 / 0)
            except BaseException as e:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(d,)) for d in payloads]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and p.read_bytes() in payloads and names(tmp_path) == ["library.json"]


CHILD = """
import os, sys, time
from pathlib import Path
from bayle.platform.files import durable_write

def stall(tmp):
    print("AT", tmp.name, flush=True)  # the temp file is written and fsynced; the target is not touched yet
    time.sleep(120)

durable_write(Path(sys.argv[1]), os.urandom(4 << 20), verify=stall)
"""


def test_a_process_killed_mid_write_leaves_the_original_whole(target):
    before = target.read_bytes()
    proc = subprocess.Popen([sys.executable, "-c", CHILD, str(target)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None
        word, tmp_name = proc.stdout.readline().split()
    finally:
        proc.kill()
        proc.wait()
    assert word == "AT" and target.read_bytes() == before
    stray = set(names(target.parent)) - {"save.sl2"}
    assert stray <= {tmp_name} and tmp_name.startswith("save.sl2.") and tmp_name.endswith(".tmp")


@pytest.mark.skipif(sys.platform == "win32", reason="Windows can't open a folder to fsync it")
def test_posix_fsyncs_the_folder_after_the_replace(tmp_path, monkeypatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (synced.append(os.fstat(fd).st_mode), real(fd)))
    durable_write(tmp_path / "x", b"1")
    assert len(synced) == 2 and stat.S_ISDIR(synced[1])


@pytest.mark.skipif(sys.platform != "win32", reason="a real sharing violation needs Windows file locking")
def test_a_real_windows_sharing_violation_is_retried(target):
    # An open handle without FILE_SHARE_DELETE (Python's default) blocks the rename until it closes.
    f = open(target, "rb")
    threading.Timer(0.3, f.close).start()
    try:
        durable_write(target, b"new")
    finally:
        f.close()
    assert target.read_bytes() == b"new"
