"""platform.files.read_settled: one consistent snapshot of a file another program may be writing or holding open.
Files are invented bytes in tmp_path; the "other program" is simulated by changing the file from inside a patched
open(), so every case is deterministic (no timing, no real second process)."""

import builtins
import hashlib
import os

import pytest

from bayle.adapters.filesystem import files
from bayle.adapters.filesystem.files import Unsettled, read_settled

DATA = b"invented save bytes " * 50


def lock_error(winerror):
    e = PermissionError(13, "in use")
    e.winerror = winerror  # type: ignore[attr-defined]  # set by hand so the test runs off Windows too
    return e


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "ER0000.sl2"
    p.write_bytes(DATA)
    return p


def patched_open(monkeypatch, src, steps):
    """files.open for src: the n-th open first runs steps[n] (an exception to raise, or a callable that changes the
    file as another program would); opens past the steps are plain. Returns the list of opens."""
    opens = []
    real = builtins.open

    def fake(path, *a, **kw):
        if os.path.normcase(str(path)) != os.path.normcase(str(src)):
            return real(path, *a, **kw)
        n = len(opens)
        opens.append(n)
        step = steps[n] if n < len(steps) else None
        if isinstance(step, BaseException):
            raise step
        if step is not None:
            step()
        return real(path, *a, **kw)

    monkeypatch.setattr(files, "open", fake, raising=False)
    return opens


def append(src, extra=b"!"):
    def go():
        with open(src, "ab") as f:
            f.write(extra)

    return go


def bump_mtime(src):
    def go():
        st = src.stat()
        os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))

    return go


def test_a_quiet_file_is_returned_whole_with_its_stat_and_left_untouched(src):
    before = fingerprint(src)
    data, st = read_settled(src, pause=0)
    assert data == DATA and st.st_size == len(DATA) and st.st_mtime_ns == before[1]
    assert fingerprint(src) == before


def test_two_reads_that_differ_are_not_accepted(src, monkeypatch):
    class Flaky:
        def __init__(self, f):
            self.f, self.reads = f, 0

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()

        def read(self):
            self.reads += 1
            return self.f.read() + (b"x" if self.reads == 2 else b"")

        def seek(self, n):
            self.f.seek(n)

    real = builtins.open
    monkeypatch.setattr(files, "open", lambda p, *a, **k: Flaky(real(p, *a, **k)), raising=False)
    with pytest.raises(Unsettled) as e:
        read_settled(src, tries=1, pause=0)
    assert e.value.locked is False


def test_a_file_that_keeps_changing_raises_unsettled_after_the_tries(src, monkeypatch):
    opens = patched_open(monkeypatch, src, [append(src)] * 10)
    with pytest.raises(Unsettled) as e:
        read_settled(src, tries=3, pause=0)
    assert e.value.locked is False and isinstance(e.value, OSError) and len(opens) == 3


def test_a_file_that_settles_after_one_change_is_read_as_its_final_bytes(src, monkeypatch):
    opens = patched_open(monkeypatch, src, [append(src, b"TAIL")])
    data, st = read_settled(src, pause=0)
    assert data == DATA + b"TAIL" == src.read_bytes() and st.st_size == len(data) and len(opens) == 2


def test_a_changed_modified_time_alone_makes_it_read_again(src, monkeypatch):
    opens = patched_open(monkeypatch, src, [bump_mtime(src)])
    data, st = read_settled(src, pause=0)
    assert data == DATA and st.st_mtime_ns == src.stat().st_mtime_ns and len(opens) == 2


@pytest.mark.parametrize("winerror", [32, 33])
def test_a_sharing_violation_is_waited_out_and_the_read_succeeds(src, monkeypatch, winerror):
    opens = patched_open(monkeypatch, src, [lock_error(winerror), lock_error(winerror)])
    data, _ = read_settled(src, pause=0, retry_for=5)
    assert data == DATA and len(opens) == 3


def test_a_lock_that_never_ends_raises_unsettled_locked(src, monkeypatch):
    patched_open(monkeypatch, src, [lock_error(32)] * 10_000)
    with pytest.raises(Unsettled) as e:
        read_settled(src, pause=0.01, retry_for=0.05)
    assert e.value.locked is True and src.read_bytes() == DATA


def test_access_denied_raises_at_once_and_is_not_waited(src, monkeypatch):
    opens = patched_open(monkeypatch, src, [lock_error(5)] * 10)
    with pytest.raises(PermissionError) as e:
        read_settled(src, pause=0.01, retry_for=30)
    assert not isinstance(e.value, Unsettled) and len(opens) == 1


def test_a_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_settled(tmp_path / "gone.sl2", pause=0)


def test_the_source_is_never_modified_by_any_outcome(src, monkeypatch):
    before = fingerprint(src)
    read_settled(src, pause=0)
    patched_open(monkeypatch, src, [lock_error(32)] * 10_000)
    with pytest.raises(Unsettled):
        read_settled(src, pause=0.01, retry_for=0.05)
    assert fingerprint(src) == before
