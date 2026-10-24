"""The runtime-owned slots (the data root, the instance scope, the record stores, the CPU backend) are bound in one
place, bayle.runtime.bootstrap: no other module in src/ or scripts/ writes them or calls the setters they replaced.
Tests may bind them through bootstrap.bind."""

import re
from pathlib import Path

from bayle.runtime import bootstrap

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "src" / "bayle" / "runtime"
REMOVED = re.compile(
    r"\b(use_hash_store|use_run_store|use_job_store|attach_notice_sink|reset_process_globals|use_scope|AppContext)\b"
    r"|\bdata_folder\.use\(|\bmirror\.use\(|\bcpu\.install\(|\bcpu_pool\.install\(|\bbayle\.app\b"
    r"|from bayle import app\b"
)


def _lines():
    for folder in (ROOT / "src", ROOT / "scripts"):
        for path in folder.rglob("*.py"):
            if RUNTIME not in path.parents:
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    yield path.resolve(), f"{path.relative_to(ROOT)}:{n}: {line.strip()}", line


def test_only_the_runtime_writes_the_runtime_owned_slots():
    names = sorted({name for _module, name in bootstrap._SLOTS.values()})
    owners: dict[Path, set[str]] = {}
    for module, name in bootstrap._SLOTS.values():
        owners.setdefault(Path(module.__file__).resolve(), set()).add(name)
    write = re.compile(rf"\.({'|'.join(names)})\s*=[^=]|setattr\([^)]*[\"']({'|'.join(names)})[\"']")
    found = [
        where
        for path, where, line in _lines()
        if write.search(line) or any(re.search(rf"\bglobal\b.*\b{n}\b", line) for n in owners.get(path, ()))
    ]
    assert found == []


def test_the_removed_setters_are_gone():
    assert [where for _path, where, line in _lines() if REMOVED.search(line)] == []
