"""The engine ships without a GUI toolkit (gate G6): this environment has no PySide6, and no engine module pulls in
PySide6, bayle_qt or velopack. Imports run in a fresh interpreter so the test session's own modules cannot hide a leak."""

import importlib.util
import subprocess
import sys

BANNED = ("PySide6", "shiboken6", "bayle_qt", "velopack")

# __main__ runs the program on import.
PROBE = f"""
import importlib, pkgutil, sys
import bayle
for m in pkgutil.walk_packages(bayle.__path__, "bayle."):
    if m.name.rsplit(".", 1)[-1] != "__main__":
        importlib.import_module(m.name)
print(sorted(n for n in sys.modules if n.split(".")[0] in {BANNED!r}))
"""


def test_the_engine_environment_has_no_qt():
    assert importlib.util.find_spec("PySide6") is None


def test_no_engine_module_loads_qt_or_velopack():
    out = subprocess.run([sys.executable, "-I", "-c", PROBE], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]", out.stdout
