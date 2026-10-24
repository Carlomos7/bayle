"""ui/refresh.Refresher: coalescing, stale results, the cheap key, a failed build, and the I/O boundary guard."""

import threading

import pytest
from bayle.platform import threads

from bayle_qt.refresh import Refresher, stat_key


class Host:
    """Deferred calls wait in a list (the event loop); background work runs inline."""

    def __init__(self):
        self.pending = []

    def defer(self, call):
        self.pending.append(call)

    def run_in_background(self, work, on_result):
        on_result(work())

    def turn(self):
        todo, self.pending = self.pending, []
        for call in todo:
            call()


def make(host, builds, applied, key=None):
    return Refresher(host, lambda: None, lambda snap: builds.append(1) or len(builds), applied.append, key=key)


def test_requests_in_one_turn_make_one_build():
    host, builds, applied = Host(), [], []
    r = make(host, builds, applied)
    r.request(), r.request(), r.request()
    assert builds == []
    host.turn()
    assert builds == [1] and applied == [1]


def test_without_defer_the_read_finishes_before_request_returns():
    class Plain:
        def run_in_background(self, work, on_result):
            on_result(work())

    builds, applied = [], []
    make(Plain(), builds, applied).request()
    assert applied == [1]


def test_a_result_that_lands_after_a_newer_request_is_dropped():
    box = {}

    class Slow(Host):
        def run_in_background(self, work, on_result):
            box["land"] = lambda: on_result(work())

    host, builds, applied = Slow(), [], []
    r = make(host, builds, applied)
    r.request()
    host.turn()  # build in flight
    r.request()  # newer request while it runs
    box["land"]()  # the old build lands: dropped, the read starts again
    assert applied == []
    box["land"]()
    assert applied == [2]


def test_same_key_skips_a_soft_request_but_not_a_forced_one():
    host, builds, applied = Host(), [], []
    r = make(host, builds, applied, key=lambda snap: "k")
    r.request()
    host.turn()
    r.request(force=False)
    host.turn()
    assert builds == [1]
    r.request(force=False)
    r.request()  # forced wins when both wait
    host.turn()
    assert builds == [1, 1]


def test_a_failed_build_leaves_the_page_and_frees_the_refresher(caplog):
    host, applied = Host(), []

    def boom(snap):
        raise ValueError("x")

    r = Refresher(host, lambda: None, boom, applied.append)
    r.request()
    host.turn()
    assert applied == [] and not r.running


def test_stat_key_changes_with_the_files(tmp_path):
    (tmp_path / "a.me3").write_text("1")
    before = stat_key([tmp_path / "a.me3", tmp_path], children=True)
    (tmp_path / "b").write_text("22")
    assert stat_key([tmp_path / "a.me3", tmp_path], children=True) != before


def test_io_on_the_ui_thread_is_refused_unless_it_stands_in_for_a_worker():
    threads.enable()
    try:
        with pytest.raises(threads.UiThreadIO):
            threads.assert_not_ui_thread("x")
        with threads.as_worker():
            threads.assert_not_ui_thread("x")
        seen = []
        t = threading.Thread(target=lambda: seen.append(threads.assert_not_ui_thread("x")))
        t.start(), t.join()
        assert seen == [None]
    finally:
        threads.disable()


def test_shutdown_logs_the_work_still_running_and_returns_false():
    pytest.importorskip("PySide6.QtCore")
    from bayle.platform import logging as run_logging

    from bayle_qt import jobs as ui_jobs

    release, started, lines = threading.Event(), threading.Event(), []
    ui_jobs.run_async(lambda: (started.set(), release.wait(5)), "slow-job")
    assert started.wait(5)
    orig = run_logging.log_shown
    run_logging.log_shown = lambda text, *a, **k: lines.append(text)
    try:
        assert ui_jobs.drain(100) is False
    finally:
        run_logging.log_shown = orig
        release.set()
        ui_jobs.POOL.waitForDone(5000)
    assert any("slow-job" in ln for ln in lines)


class Owner:
    """A page adapter: it owns its Refresher, which is given the adapter's own methods."""

    def __init__(self, host):
        self.applied = []
        self.refresher = Refresher(host, self._snapshot, self._build, self.applied.append, busy=self._busy)

    def _snapshot(self):
        return 7

    def _build(self, snap):
        return snap * 2

    def _busy(self, on):
        pass


def test_the_refresher_does_not_keep_its_owner_alive():
    # The adapter is a QObject: a cycle through its Refresher freed it (children, timers) at a later garbage
    # collection, on any thread, and crashed CI's next QML load. It must go the moment its last reference does.
    import gc
    import weakref

    host = Host()
    gc.disable()
    try:
        owner = Owner(host)
        owner.refresher.request()
        host.turn()
        assert owner.applied == [14]
        gone = weakref.ref(owner)
        del owner
        assert gone() is None
    finally:
        gc.enable()
