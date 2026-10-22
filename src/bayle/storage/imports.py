"""The one-time (and after-rollback) imports of the old record files, run in the background after start-up has
reported ready: hashes.json into the hash cache, then jobs.jsonl into the activity log, then the activity log's
retention (only once its file is imported). Each step is resumable and idempotent; one that fails is tried again at
the next start, and its area keeps reading its old file meanwhile."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from bayle.storage.activity import ActivityLog
from bayle.storage.cache import HashCache
from bayle.storage.rebuild_runs import RebuildRuns


def run_imports(
    hashes_file: Path,
    jobs_file: Path,
    cache: HashCache,
    activity: ActivityLog,
    log: Callable[[str], None],
    runs: RebuildRuns | None = None,
    merges_file: Path | None = None,
) -> dict:
    """{area: active afterwards, "pruned": rows removed by retention}."""
    out: dict = {}
    steps = [
        ("hash cache", lambda: cache.import_file(hashes_file)),
        ("activity log", lambda: activity.import_file(jobs_file)),
    ]
    if runs is not None and merges_file is not None:
        steps.append(("rebuild runs", lambda: runs.import_file(merges_file)))
    for name, step in steps:
        try:
            out[name] = step()
        except Exception as e:  # a database error, a file that can't be read: the next start tries again
            log(f"warning: importing the {name} into the database failed ({e}); it is tried again next time")
            out[name] = False
    out["pruned"] = 0
    if activity.active:
        try:
            out["pruned"] = activity.prune_completed()
        except Exception as e:
            log(f"warning: the activity log's retention could not run ({e})")
    log(
        "storage: imports done ("
        + ", ".join(f"{k} {'in use' if v else 'not yet'}" for k, v in out.items() if k != "pruned")
        + f"; {out['pruned']} old entries removed)"
    )
    return out
