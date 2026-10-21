"""ui/refresh.Refresher: coalescing, stale results, the cheap key, a failed build, and the I/O boundary guard."""

import threading

import pytest

from roundtable_souls.platform import threads
from roundtable_souls.ui.refresh import Refresher, stat_key


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
