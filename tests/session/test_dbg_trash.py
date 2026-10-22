"""Debug only: the Recycle Bin call alone, then the UI tests."""

import sys

import pytest

from bayle.platform import trash


@pytest.mark.skipif(sys.platform != "win32", reason="windows")
def test_dbg_send_alone(tmp_path):
    d = tmp_path / "x"
    d.mkdir()
    (d / "f").write_text("1")
    rec = trash.send(d)
    trash.purge(rec)
