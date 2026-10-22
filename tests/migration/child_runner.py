"""Test-only steps for the app-data migration runner, and a child process that runs it and stops at a boundary.

Not a test module (no test_ prefix); test_data_migration.py loads it by path. As a script:
    child_runner.py DATA STEP:PHASE   prints AT when it reaches the boundary and then waits to be killed.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from bayle.platform import instance
from bayle.storage.datamigrations import Ctx, Step, migrate

APPLIED: list[str] = []  # in this process: which steps ran


def _set_flag(ctx: Ctx, file: str, key: str) -> None:
    path = ctx.data / file
    doc = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    doc[key] = True  # idempotent: running it again writes the same bytes
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def _check_flag(ctx: Ctx, file: str, key: str) -> None:
    if not json.loads((ctx.data / file).read_text(encoding="utf-8")).get(key):
        raise AssertionError(f"{key} missing in {file}")


def _apply_one(ctx: Ctx) -> None:
    APPLIED.append("one")
    _set_flag(ctx, "launcher_settings.json", "migrated_one")


def _apply_two(ctx: Ctx) -> None:
    APPLIED.append("two")
    _set_flag(ctx, "merges.json", "migrated_two")


STEPS = [
    Step("one", _apply_one, lambda c: _check_flag(c, "launcher_settings.json", "migrated_one")),
    Step("two", _apply_two, lambda c: _check_flag(c, "merges.json", "migrated_two")),
]


def make_legacy(data: Path) -> None:
    """The files a 4.5.1 build leaves: settings that remember the update, merges.json, the readiness marker."""
    data.mkdir(parents=True, exist_ok=True)
    (data / "launcher_settings.json").write_text(
        json.dumps({"game": "eldenring", "update_result": {"status": "ok", "version": "4.5.1"}}), encoding="utf-8"
    )
    (data / "merges.json").write_text("{}", encoding="utf-8")
    (data / "updates" / "state").mkdir(parents=True, exist_ok=True)
    (data / "updates" / "state" / "ready-4.5.1").write_text("window 1", encoding="utf-8")
    (data / "logs").mkdir(exist_ok=True)
    (data / "logs" / "launcher.log").write_text("hello", encoding="utf-8")


if __name__ == "__main__":
    folder, spot = Path(sys.argv[1]), sys.argv[2]

    def stop_here(step, phase):
        if f"{step}:{phase}" == spot:
            print("AT", flush=True)
            time.sleep(120)

    instance.use_scope("RoundtableSouls.Child", folder)
    migrate(folder, "9.9.9", steps=STEPS, fail_at=stop_here, log=lambda line: None)
