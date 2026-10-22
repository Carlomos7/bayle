"""A page follows a session job to its end through the shell: once, whether it asks before or after the job ended;
a quiet job (the page words its end) gets no generic "done" toast, a failed one always says so."""

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


def test_a_follower_registered_before_the_end_is_called_once_with_the_result(host):
    ended, toasts = [], []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append(text))
    job = host.session.start(lambda ctx: {"made": 1}, title="Making it...", quiet=True)
    host.follow_job(job, lambda ok, data: ended.append((ok, data["result"])))
    assert settled(lambda: ended)
    assert ended == [(True, {"made": 1})] and toasts == []  # quiet: the page words it, no generic toast
    assert settled(lambda: not host.state.busy)


def test_a_follower_registered_after_the_end_still_hears_how_it_ended(host):
    job = host.session.start(lambda ctx: {"made": 2}, title="Making it...", quiet=True)
    assert settled(lambda: host.session.jobs.get(job).state == "done" and job in host._ended)
    ended = []
    host.follow_job(job, lambda ok, data: ended.append((ok, data["result"])))
    assert ended == [(True, {"made": 2})]
    host.follow_job(job, lambda ok, data: ended.append("again"))  # once only
    assert ended == [(True, {"made": 2})]


def test_a_job_that_is_not_quiet_says_done_and_a_failed_one_says_why_it_stopped(host):
    toasts = []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
    host.session.start(lambda ctx: None, title="Plain job...")
    assert settled(lambda: ("Plain job: done", False) in toasts)

    def boom(ctx):
        raise RuntimeError("no")

    ended = []
    job = host.session.start(boom, title="Failing...", quiet=True)
    host.follow_job(job, lambda ok, data: ended.append((ok, data["error"]["code"])))
    assert settled(lambda: ended) and ended == [(False, "unexpected")]
