"""Opening a path with the desktop's handler: the OS calls are faked, nothing is opened."""

from pathlib import Path

import pytest

from roundtable_souls.platform import desktop


def test_windows_uses_startfile(monkeypatch, tmp_path):
    opened = []
    monkeypatch.setattr(desktop, "IS_WINDOWS", True)
    monkeypatch.setattr(desktop.os, "startfile", opened.append, raising=False)
    desktop.open_path(tmp_path / "folder")
    assert opened == [str(tmp_path / "folder")]


@pytest.mark.parametrize(("platform", "command"), [("darwin", "open"), ("linux", "xdg-open")])
def test_other_systems_run_the_platform_opener(monkeypatch, platform, command):
    calls = []
    monkeypatch.setattr(desktop, "IS_WINDOWS", False)
    monkeypatch.setattr(desktop.sys, "platform", platform)
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda args, **kw: calls.append((args, kw)))
    desktop.open_path("https://example.invalid/page")
    assert calls[0][0] == [command, "https://example.invalid/page"]
    if platform == "linux":
        assert calls[0][1]["stdout"] == desktop.subprocess.DEVNULL


def test_path_objects_are_passed_as_text(monkeypatch):
    calls = []
    monkeypatch.setattr(desktop, "IS_WINDOWS", False)
    monkeypatch.setattr(desktop.sys, "platform", "darwin")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda args, **kw: calls.append(args))
    desktop.open_path(Path("x") / "y")
    assert calls == [["open", str(Path("x") / "y")]]
