"""The generated ui/theme_tokens.py stays plain data (no Qt)."""

import ast
from pathlib import Path

from roundtable_souls.ui import theme_tokens


def test_theme_tokens_imports_nothing_but_future():
    tree = ast.parse(Path(theme_tokens.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name if isinstance(node, ast.Import) else node.module
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {"__future__"}
