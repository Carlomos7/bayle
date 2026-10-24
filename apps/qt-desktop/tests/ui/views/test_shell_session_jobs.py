"""A page follows a session job to its end through the shell: once it has ended (at once when it already has); a quiet
job (the page words its end) gets no generic "done" toast, a failed one always says so."""

import time

import pytest
from PySide6.QtCore import QCoreApplication


def settled(cond, ms=4000) -> bool:
    end = time.time() + ms / 1000
    while not cond() and time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


@pytest.fixture
def host(qt_app, shell_host):
    return shell_host


def test_a_follower_gets_the_snapshot_whether_it_asks_before_or_after_the_end(host):
    toasts, ended = [], []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append(text))
    job = host.job_manager.start(lambda ctx: {"made": 1}, title="Making it...", quiet=True)
    host.follow_job(job, lambda snap: ended.append(snap.result))
    assert settled(lambda: ended) and ended == [{"made": 1}] and toasts == []  # quiet: no generic toast
    host.follow_job(job, lambda snap: ended.append(snap.state))  # after the end: at once
    assert ended[-1] == "done"


def test_a_job_that_is_not_quiet_says_done_and_a_failed_one_says_why(host):
    toasts = []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
    host.job_manager.start(lambda ctx: None, title="Plain job...")
    assert settled(lambda: ("Plain job: done", False) in toasts)

    def boom(ctx):
        raise RuntimeError("no")

    ended = []
    job = host.job_manager.start(boom, title="Failing...", quiet=True)
    host.follow_job(job, lambda snap: ended.append((snap.state, snap.error.code)))
    assert settled(lambda: ended) and ended == [("failed", "unexpected")]


def test_the_shells_codes_reach_the_player_as_the_same_sentences(host):
    from bayle.work.prompts import Option, Question

    toasts, forks, answers = [], [], []
    host.notifier.toastRequested.connect(lambda text, error: toasts.append((text, error)))
    host.notifier.chooseRequested.connect(lambda token, words: forks.append(words))
    host.shell.flow.ports.toast("launch_cancelled_rebuild")
    host.shell.flow.ports.toast("blocked", {"code": "no_profile", "game": "Elden Ring"}, error=True)
    host.shell.flow.ports.ask(
        Question("backup_failed", {"failed": ["ER0000.sl2: locked"]}, (Option("retry", "primary"), Option("cancel"))),
        answers.append,
    )
    assert settled(lambda: len(toasts) == 2 and forks)
    assert toasts == [
        ("Launch cancelled: the rebuild finishes first, then the game does not start.", False),
        ("No profile", True),
    ]
    fork = forks[0]
    assert fork["title"] == "Backing up your saves failed" and fork["lines"] == ["ER0000.sl2: locked"]
    assert [(c["key"], c["label"], c["role"]) for c in fork["choices"]] == [
        ("retry", "Retry", "primary"),
        ("cancel", "Cancel", "normal"),
    ]
    assert fork["warning"] == "The game has not started: 'Back up saves before launch' is on."
