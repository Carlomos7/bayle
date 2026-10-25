"""Every worker task string ("bayle.pkg.module:function", run by platform.cpu in a worker process) names a real public
callable. The strings are found by reading the source, so a module move that leaves one behind, or a new one that
points nowhere, fails here and not at the first run of that task in a worker."""

import ast
import importlib
import re
from pathlib import Path

import pytest

import bayle
from bayle.work import cpu

SRC = Path(bayle.__file__).resolve().parent
TASK = re.compile(r"bayle(\.\w+)+:[A-Za-z]\w*")
# What the code uses today. A string leaving this list is a removed task; add new ones here.
KNOWN = {
    "bayle.work.cpu:probe",
    "bayle.modules.saves.caches:forget",
    "bayle.adapters.merging.rules.param:combine_job",
    "bayle.adapters.filesystem.tree_hash:tree_hash_job",
    "bayle.modules.saves.service:save_info_job",
}


def _module_of(path: Path) -> str:
    parts = path.relative_to(SRC.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _found() -> set[str]:
    """Literal task strings, and the f"{__name__}:job" form (the module is the file's own)."""
    found = set()
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and TASK.fullmatch(node.value):
                found.add(node.value)
            elif isinstance(node, ast.JoinedStr) and len(node.values) == 2:
                head, tail = node.values
                if (
                    isinstance(head, ast.FormattedValue)
                    and isinstance(head.value, ast.Name)
                    and head.value.id == "__name__"
                    and isinstance(tail, ast.Constant)
                    and re.fullmatch(r":[A-Za-z]\w*", str(tail.value))
                ):
                    found.add(_module_of(path) + str(tail.value))
    return found


def test_the_scan_still_finds_every_known_task():
    assert KNOWN <= _found()


@pytest.mark.parametrize("task", sorted(_found() | KNOWN))
def test_a_task_string_resolves_to_a_public_callable(task):
    module, _, name = task.partition(":")
    assert module.startswith(cpu.PREFIX) and not name.startswith("_")  # what platform.cpu.call accepts
    assert callable(getattr(importlib.import_module(module), name))
