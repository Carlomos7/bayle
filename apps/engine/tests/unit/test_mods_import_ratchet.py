"""The mods modules used to form one import cycle that only function-level imports hid from import-linter (24
modules, 77 such edges). This counts the function-level imports of one mods module by another and fails when the
number rises: it may only go down (then lower LIMIT). A new dependency between mods modules goes at the top of the
file, or through mods/kinds.py when the other module owns a persisted kind."""

import ast

from bayle.resources import PACKAGE_DIR

LIMIT = 20  # the mods modules' own cycles, plus the two the Mods page services keep (service -> mod_configs, transfer_resources -> profile_transfer)


def _targets(node: ast.stmt, mods: set[str]) -> int:
    """How many mods modules this import statement names."""
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        found = {f"{node.module}.{a.name}" for a in node.names} & mods
        return len(found) or int(node.module in mods)
    if isinstance(node, ast.Import):
        return sum(a.name in mods for a in node.names)
    return 0


def function_level_imports() -> list[str]:
    root = PACKAGE_DIR / "modules" / "mods"
    mods = {"bayle.modules.mods." + ".".join(p.relative_to(root).with_suffix("").parts) for p in root.rglob("*.py")}
    found = []
    for path in sorted(root.rglob("*.py")):
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                for node in ast.walk(fn):
                    if isinstance(node, ast.Import | ast.ImportFrom) and _targets(node, mods):
                        found.append(f"{path.relative_to(root).as_posix()}:{node.lineno}")
    return sorted(set(found))


def test_function_level_imports_between_mods_modules_do_not_grow():
    found = function_level_imports()
    assert len(found) <= LIMIT, f"{len(found)} function-level imports between mods modules (limit {LIMIT}): {found}"


def test_the_kind_registry_is_filled_for_every_persisted_kind():
    from bayle.modules.mods import kinds

    kinds.ensure_loaded()
    assert set(kinds.FINISHERS) == {
        "profile-folders",
        "profile-move-in",
        "folder-rename",
        "folder-split",
        "profile-rename",
    }
    assert {
        *kinds.OPERATIONS,
        *kinds.OVERHAUL,
        *kinds.LIBRARY,
        "remove", "rebuild", "multi", "rename", "profile-import", "profile-rename", "profile-duplicate",
        "profile-folders", "layout-relocate", "layout-rename", "profile-move-in", "folder-rename", "folder-split",
        "dll-folders",
    } <= set(kinds.UNDO)  # fmt: skip
