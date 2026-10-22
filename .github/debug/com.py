"""Debug probe: COM state of the main thread before and after the Recycle Bin call."""

import ctypes
import pathlib
import sys
import tempfile

sys.path.insert(0, "src")
from bayle.platform import trash


def com():
    r = ctypes.windll.ole32.CoInitializeEx(None, 2) & 0xFFFFFFFF
    if r in (0, 1):
        ctypes.windll.ole32.CoUninitialize()
    return hex(r)


d = pathlib.Path(tempfile.mkdtemp()) / "x"
d.mkdir()
(d / "f").write_text("1")
print("before", com())
rec = trash.send(d)
print("after", com())
trash.purge(rec)
