"""`--update` without the window: every step (instance, feed, apply) is faked, so nothing is downloaded or installed."""

from types import SimpleNamespace

import pytest
from bayle.adapters.system import logging as run_logging
from bayle.runtime import instance

from bayle_qt.updater import apply, feed, headless


@pytest.fixture
def steps(monkeypatch):
    """Quiet defaults for the happy path; each test changes the one step it is about."""
    lines = []
    monkeypatch.setattr(instance, "held", lambda name: False)
    monkeypatch.setattr(apply, "busy_reason", lambda: "")
    monkeypatch.setattr(
        feed,
        "check_launcher_update",
        lambda force: SimpleNamespace(failed=False, reason="", blocked="", offer={"version": "9.9.9"}),
    )
    monkeypatch.setattr(apply, "can_self_update", lambda offer: True)
    monkeypatch.setattr(apply, "download_update", lambda offer: SimpleNamespace(delta=True, version="9.9.9"))
    monkeypatch.setattr(apply, "stage_rollback", lambda: "rollback-token")
    applied = []
    monkeypatch.setattr(apply, "apply_update", lambda prepared, restart_args: applied.append((prepared, restart_args)))
    return SimpleNamespace(lines=lines, applied=applied)


def run(steps, **kwargs):
    return headless.update_headless(
        ["--game", "er", "--play"], log=steps.lines.append, start_log=lambda s: None, **kwargs
    )


def test_installs_the_offer_and_hands_over_with_the_restart_args(steps):
    assert run(steps) == 0
    prepared, args = steps.applied[0]
    assert args == ["--game", "er", "--play"]
    assert prepared.rollback == "rollback-token"
    assert any(line.startswith("checked: signed feed and delta package") for line in steps.lines)
    assert steps.lines[-1].startswith("installing 9.9.9")


def test_refuses_while_the_window_is_open(steps, monkeypatch):
    monkeypatch.setattr(instance, "held", lambda name: True)
    assert run(steps) == 1
    assert steps.applied == []
    assert "Bayle is open" in steps.lines[0]


def test_stops_when_another_update_is_busy(steps, monkeypatch):
    monkeypatch.setattr(apply, "busy_reason", lambda: "a game is being updated")
    assert run(steps) == 1
    assert steps.lines == ["error: a game is being updated"]


def test_stops_when_the_check_fails(steps, monkeypatch):
    monkeypatch.setattr(
        feed,
        "check_launcher_update",
        lambda force: SimpleNamespace(failed=True, reason="offline", blocked="", offer=None),
    )
    assert run(steps) == 1
    assert steps.lines == ["error: could not check for updates: offline"]


def test_a_release_that_failed_here_is_exit_code_3(steps, monkeypatch):
    monkeypatch.setattr(
        feed,
        "check_launcher_update",
        lambda force: SimpleNamespace(failed=False, reason="", blocked="9.9.9", offer=None),
    )
    assert run(steps) == 3
    assert steps.applied == []


def test_already_current_is_success_without_an_install(steps, monkeypatch):
    monkeypatch.setattr(
        feed, "check_launcher_update", lambda force: SimpleNamespace(failed=False, reason="", blocked="", offer=None)
    )
    assert run(steps) == 0
    assert steps.applied == []
    assert steps.lines[-1].endswith("is the latest release")


def test_a_copy_that_cannot_self_update_points_at_the_releases_page(steps, monkeypatch):
    monkeypatch.setattr(apply, "can_self_update", lambda offer: False)
    assert run(steps) == 1
    assert feed.RELEASES_URL in steps.lines[-1]


def test_a_failed_download_changes_nothing(steps, monkeypatch):
    def broken(offer):
        raise feed.UpdateError("signature does not match")

    monkeypatch.setattr(apply, "download_update", broken)
    assert run(steps) == 1
    assert steps.applied == []
    assert steps.lines[-1] == "error: signature does not match"


def test_without_start_log_the_launcher_log_is_started(steps, monkeypatch):
    started = []
    monkeypatch.setattr(run_logging, "start_log", lambda *args: started.append(args))
    headless.update_headless([], log=steps.lines.append)
    assert started and started[0][0] == "launcher: update (no window)"
