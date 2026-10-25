"""A test that removes a mod never reaches the real Windows Recycle Bin (the suite's fixture gives it a bin of its own).
The shell call made before Qt's first QML window exists crashes that load on a Windows runner (CI runs the session
tests, which remove mods, before the UI tests), so only tests marked real_recycle_bin may make it."""

import sys

import pytest

from bayle.adapters.filesystem import trash

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="the Windows Recycle Bin")


def test_a_removal_goes_to_the_tests_own_bin_and_comes_back(tmp_path):
    mod = tmp_path / "mod"
    (mod / "parts").mkdir(parents=True)
    rec = trash.send(mod)
    assert not mod.exists() and trash.exists(rec)
    assert tmp_path in trash.Path(rec["item"]).parents  # not the drive's $Recycle.Bin
    trash.restore(rec)
    assert (mod / "parts").is_dir()
