"""Some modules are not imported by the other tests, so at least make sure every module compiles."""

import py_compile
from pathlib import Path

import bayle


def test_every_module_compiles():
    root = Path(bayle.__file__).resolve().parent
    files = sorted(root.rglob("*.py"))
    assert any(p.name == "cli.py" and p.parent == root for p in files)
    for p in files:
        py_compile.compile(str(p), doraise=True)
