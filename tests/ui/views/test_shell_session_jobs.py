"""A page follows a session job to its end through the shell: once it has ended (at once when it already has); a quiet
job (the page words its end) gets no generic "done" toast, a failed one always says so."""

import time

import pytest
from PySide6.QtCore import QCoreApplication

from bayle.ui import self_test
from bayle.ui.launcher.host import ShellHost


def settled(cond, ms=4000) -> bool:
    end = time.time() + ms / 1000
    while not cond() and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


@pytest.fixture
def host(qt_app, tmp_path):
    return ShellHost(self_test._Context(tmp_path, "dark"))  # type: ignore[arg-type]


def test_a_follower_gets_the_snapshot_whether_it_asks_before_or_after_the_end(host):
    toasts, ended = [], []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append(text))
    job = host.session.start(lambda ctx: {"made": 1}, title="Making it...", quiet=True)
    host.follow_job(job, lambda snap: ended.append(snap.result))
    assert settled(lambda: ended) and ended == [{"made": 1}] and toasts == []  # quiet: no generic toast
    host.follow_job(job, lambda snap: ended.append(snap.state))  # after the end: at once
    assert ended[-1] == "done"


def test_a_job_that_is_not_quiet_says_done_and_a_failed_one_says_why(host):
    toasts = []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
    host.session.start(lambda ctx: None, title="Plain job...")
    assert settled(lambda: ("Plain job: done", False) in toasts)

    def boom(ctx):
        raise RuntimeError("no")

    ended = []
    job = host.session.start(boom, title="Failing...", quiet=True)
    host.follow_job(job, lambda snap: ended.append((snap.state, snap.error.code)))
    assert settled(lambda: ended) and ended == [("failed", "unexpected")]
