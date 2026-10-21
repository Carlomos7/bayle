"""Dead eldenring.exe shells: PowerShell and the log are faked, so no real process is queried or stopped."""

import subprocess

import pytest

from roundtable_souls.platform import processes


class FakeRun:
    """Stands in for subprocess.run: returns the given stdout, or raises the given error."""

    def __init__(self, stdout="", error=None):
        self.stdout, self.error, self.calls = stdout, error, []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if self.error:
            raise self.error
        return subprocess.CompletedProcess(args, 0, stdout=self.stdout, stderr="")


@pytest.fixture
def logged(monkeypatch):
    lines = []
    monkeypatch.setattr(processes, "log", lines.append)
    return lines


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(processes.sys, "platform", "win32")


def test_dead_shells_is_empty_off_windows_and_never_queries(monkeypatch):
    monkeypatch.setattr(processes.sys, "platform", "linux")
    fake = FakeRun("123\n")
    monkeypatch.setattr(processes.subprocess, "run", fake)
    assert processes.dead_shells("eldenring.exe") == []
    assert fake.calls == []


def test_dead_shells_parses_pids_and_asks_for_threadless_processes(monkeypatch, windows):
    fake = FakeRun("1234\r\n5678\r\n\nnot-a-pid\n")
    monkeypatch.setattr(processes.subprocess, "run", fake)
    assert processes.dead_shells("eldenring.exe") == [1234, 5678]
    script = fake.calls[0][-1]
    assert "Get-Process -Name 'eldenring'" in script  # the extension is dropped
    assert "Threads.Count -eq 0" in script


def test_dead_shells_removes_quotes_from_the_name(monkeypatch, windows):
    fake = FakeRun("")
    monkeypatch.setattr(processes.subprocess, "run", fake)
    processes.dead_shells("elden'ring.exe")
    assert "Get-Process -Name 'eldenring'" in fake.calls[0][-1]


@pytest.mark.parametrize("error", [OSError("no powershell"), subprocess.TimeoutExpired("powershell", 30)])
def test_dead_shells_gives_nothing_when_powershell_fails(monkeypatch, windows, error):
    monkeypatch.setattr(processes.subprocess, "run", FakeRun(error=error))
    assert processes.dead_shells("eldenring.exe") == []


def test_kill_elevated_stops_the_pids_and_reports_those_still_present(monkeypatch, windows):
    fake = FakeRun("")
    monkeypatch.setattr(processes.subprocess, "run", fake)
    monkeypatch.setattr(processes, "dead_shells", lambda name: [2, 9])
    assert processes.kill_elevated([1, 2], "eldenring.exe") == [2]
    launcher = fake.calls[0][-1]
    assert "Stop-Process -Id 1,2 -Force" in launcher
    assert "-Verb RunAs" in launcher  # the UAC prompt


def test_kill_elevated_logs_a_launch_failure_and_still_checks(monkeypatch, windows, logged):
    monkeypatch.setattr(processes.subprocess, "run", FakeRun(error=OSError("denied")))
    monkeypatch.setattr(processes, "dead_shells", lambda name: [7])
    assert processes.kill_elevated([7], "eldenring.exe") == [7]
    assert any("could not run the elevated kill" in line for line in logged)


def test_clear_with_nothing_to_remove_says_so(monkeypatch, windows, logged):
    monkeypatch.setattr(processes, "dead_shells", lambda name: [])
    assert processes.clear("eldenring.exe") == ([], [])
    assert logged == ["no dead eldenring.exe shells"]


def test_clear_dry_run_finds_without_elevating(monkeypatch, windows, logged):
    monkeypatch.setattr(processes, "dead_shells", lambda name: [4, 5])

    def no_elevation(*args):
        raise AssertionError("a dry run must not ask for administrator rights")

    monkeypatch.setattr(processes, "kill_elevated", no_elevation)
    assert processes.clear("eldenring.exe", dry_run=True) == ([4, 5], [4, 5])


def test_clear_reports_what_stayed_and_what_was_cleared(monkeypatch, windows, logged):
    monkeypatch.setattr(processes, "dead_shells", lambda name: [4, 5])
    monkeypatch.setattr(processes, "kill_elevated", lambda pids, name: [5])
    assert processes.clear("eldenring.exe") == ([4, 5], [5])
    assert "still present (UAC declined, or held by a driver): 5" in logged

    logged.clear()
    monkeypatch.setattr(processes, "kill_elevated", lambda pids, name: [])
    assert processes.clear("eldenring.exe") == ([4, 5], [])
    assert logged[-1] == "cleared"
