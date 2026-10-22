"""The app-data migration runner (decision-one-way-migration.md, phase0-plan.md A.4).

<data>/data-version.json says which data version the folder is at. Without it the folder is fresh (nothing of
Bayle's in it: the marker is written, no step runs) or legacy (a build from before the marker left its files: the
steps run). A marker newer than this build, a marker that can't be read, and data from before FLOOR are refused
with nothing touched.

Order when a migration is needed: the migration lock, then the legacy journals are resolved (they change user files,
which no metadata backup can undo, so they go first), then the small data is backed up and verified, then the steps
run, each recorded in migration-state.json, then open_db (Alembic), then the marker. A step that raises, or whose
check fails, puts the backup back and removes the state; a process that dies leaves the state and the next start
resumes at the recorded step, so steps must be idempotent.

Data version v means steps[:v-1] are applied: legacy data is version 1, CURRENT_VERSION = 1 + len(STEPS).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.platform import instance
from bayle.platform import logging as run_logging
from bayle.storage import db as storage_db

MARKER = "data-version.json"
STATE = "migration-state.json"
BACKUPS = "migration-backup"
FLOOR = "4.5.0"  # the oldest build whose data the steps understand (E4)
INSTALL_FIRST = "4.5.1"  # what a user below FLOOR installs before this build
LEGACY_DB_REVISION = "0004"  # every build from 4.2.0 on leaves the database at this revision or later

# What is backed up: the small data only (A.4). Files by name pattern, folders whole. Mod folders, saves and save
# backup payloads are never in it. shortcut: per-profile .bayle folders live outside the data folder and are not
# covered; add them when a real step rewrites them.
BACKUP_FILES = ("launcher_settings.json*", "roundtable.db*", "merges.json", "cache/hashes.json", "logs/jobs.jsonl")
BACKUP_DIRS = ("layout-ops", "updates/state")
# What marks a folder as legacy rather than fresh (logs and temp files alone do not).
LEGACY_FILES = ("launcher_settings.json", "roundtable.db", "merges.json")
LEGACY_DIRS = ("layout-ops", ".bayle", ".roundtable")


class MigrationError(storage_db.MigrationFailed):
    """The migration did not run or did not finish; .code says why, the message says what to do."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Ctx:
    data: Path
    log: Callable[[str], None]


@dataclass(frozen=True)
class Step:
    name: str
    apply: Callable[[Ctx], None]
    check: Callable[[Ctx], None]  # raises when the step's result is not right


STEPS: list[Step] = []  # no real step yet; the first lands with the first format change
CURRENT_VERSION = 1 + len(STEPS)

FailAt = Callable[[Any, str], None]  # (step index or "backup"/"marker", "before"|"during"|"after"); tests only


# ----------------------------------------------------------------------------- durable files
def _fsync_dir(path: Path) -> None:
    if sys.platform == "win32":
        return  # a directory can't be opened for fsync on Windows
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _durable_copy(src: Path, dest: Path) -> None:
    """Copy src over dest through a temp file in dest's folder: flushed to disk, then renamed into place."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f"{dest.name}.{os.getpid()}.mig-tmp")
    try:
        with open(src, "rb") as r, open(tmp, "wb") as w:
            shutil.copyfileobj(r, w)
            w.flush()
            os.fsync(w.fileno())
        os.replace(tmp, dest)
        _fsync_dir(dest.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.mig-tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- backup
def _covered(data: Path) -> dict[str, Path]:
    """The files that exist now in the backed-up set, by path relative to the data folder (posix style)."""
    found: dict[str, Path] = {}
    for pattern in BACKUP_FILES:
        found.update({p.relative_to(data).as_posix(): p for p in data.glob(pattern) if p.is_file()})
    for folder in BACKUP_DIRS:
        found.update({p.relative_to(data).as_posix(): p for p in (data / folder).rglob("*") if p.is_file()})
    return found


def make_backup(data: Path, label: str, hook: FailAt) -> Path:
    for old in (data / BACKUPS).glob("*"):  # one an earlier start died in the middle of: never complete
        if not (old / "manifest.json").exists():
            shutil.rmtree(old, ignore_errors=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest = data / BACKUPS / f"{label}-{stamp}"
    files: dict[str, str] = {}
    try:
        for rel, src in sorted(_covered(data).items()):
            _durable_copy(src, dest / "files" / rel)
            files[rel] = _sha(dest / "files" / rel)
            if _sha(src) != files[rel]:  # changed while it was copied: another program is writing it
                raise OSError(f"{rel} changed while it was backed up")
            hook("backup", "during")
        write_json(dest / "manifest.json", {"from": label, "at": stamp, "files": files})
        verify_backup(dest)
    except (OSError, ValueError) as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise MigrationError("backup-failed", f"Bayle could not back up your data before updating it ({e}).") from e
    return dest


def verify_backup(backup: Path) -> dict[str, str]:
    """The manifest's files, each checked against its sha256. Raises ValueError when one is missing or differs."""
    try:
        files = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"the backup's manifest can't be read ({e})") from e
    for rel, digest in files.items():
        p = backup / "files" / rel
        if not p.is_file() or _sha(p) != digest:
            raise ValueError(f"{rel} in the backup is missing or damaged")
    return files


def restore_backup(data: Path, backup: Path) -> None:
    """Put the data folder's backed-up set back as it was: files the migration made are removed, the others copied
    back and checked."""
    files = verify_backup(backup)
    for rel, p in _covered(data).items():
        if rel not in files:
            p.unlink()
    for rel, digest in files.items():
        _durable_copy(backup / "files" / rel, data / rel)
        if _sha(data / rel) != digest:
            raise OSError(f"{rel} was not restored intact")


# ----------------------------------------------------------------------------- reading the data folder
def _read_marker(data: Path) -> dict | None:
    path = data / MARKER
    if not path.exists():
        return None
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        version = marker["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ValueError("no version number")
        return marker
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise MigrationError(
            "corrupt-marker",
            f"{path} can't be read ({e}). Bayle left your data alone. To repair it, restore {MARKER} from a "
            f"backup, or delete it only if you are sure the data is from Bayle {INSTALL_FIRST} or later.",
        ) from e


def is_legacy(data: Path) -> bool:
    """Whether an older build left its files here (by content, not by the folder merely existing)."""
    return any((data / f).is_file() for f in LEGACY_FILES) or any((data / d).is_dir() for d in LEGACY_DIRS)


def _release(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None  # a pre-release counts as its release


def legacy_version(data: Path) -> str | None:
    """The newest build known to have run here: ready-VERSION files (every build since the updater writes one), else
    the update the settings remember. None when nothing says."""
    found = [r for p in (data / "updates" / "state").glob("ready-*") if (r := _release(p.name[6:]))]
    if not found:
        try:
            raw = json.loads((data / "launcher_settings.json").read_text(encoding="utf-8"))
            for key in ("update_result", "update_pending"):
                found += [r for r in [_release(str((raw.get(key) or {}).get("version") or ""))] if r]
        except OSError, ValueError, AttributeError:
            pass
    return ".".join(map(str, max(found))) if found else None


def check_floor(data: Path) -> None:
    """Refuse data that an older build than FLOOR left. shortcut: a build is only known from its ready-VERSION file
    or the settings' update record; with neither, only a database below 0004 (before 4.2.0) shows it is too old."""
    version = legacy_version(data)
    floor = _release(FLOOR)
    old = version is not None and floor is not None and (_release(version) or floor) < floor
    if not old:
        try:
            rev = storage_db.read_revision(data / storage_db.DB_NAME)
        except storage_db.StorageUnavailable:
            rev = None
        old = rev is not None and rev in storage_db.known_revisions() and rev < LEGACY_DB_REVISION
        version = version or "before 4.2.0"
    if old:
        raise MigrationError(
            "below-floor",
            f"These files are from Bayle {version}, which this version can't upgrade directly. Install Bayle "
            f"{INSTALL_FIRST} first, start it once, then install this version. Bayle left your data alone.",
        )


# ----------------------------------------------------------------------------- the run
def _no_hook(step: Any, phase: str) -> None:
    pass


def _read_state(data: Path) -> dict | None:
    path = data / STATE
    if not path.exists():
        return None
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
        return {"from": str(s["from"]), "to": int(s["to"]), "step": int(s["step"]), "backup": str(s["backup"])}
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise MigrationError(
            "state-corrupt",
            f"{path} can't be read ({e}). Bayle left your data alone. The files from before the update are in "
            f"{data / BACKUPS}; restore them over the data folder, then delete {STATE}.",
        ) from e


def _fail(data: Path, backup: Path, code: str, what: str, cause: BaseException) -> MigrationError:
    """Put the backup back, drop the state, and say what failed."""
    try:
        restore_backup(data, backup)
    except (OSError, ValueError) as e:
        return MigrationError(
            "restore-failed",
            f"{what}, and the old data could not be put back ({e}). It is in {backup}; the next start tries again.",
        )
    (data / STATE).unlink(missing_ok=True)
    return MigrationError(code, f"{what} ({cause}). Your data was put back as it was.")


def _marker(version: int, app: str, migrated_from: str | None) -> dict:
    now = datetime.datetime.now(datetime.UTC).isoformat()
    return {"version": version, "app": app, "migrated_from": migrated_from, "at": now}


def migrate(
    data: Path,
    app_version: str,
    *,
    recover_journals: Callable[[], list[str]] = lambda: [],
    open_db: Callable[[], Any] | None = None,
    steps: list[Step] | None = None,
    fail_at: FailAt | None = None,
    log: Callable[[str], None] = run_logging.log,
) -> Any:
    """Bring the data folder to this build's data version before anything else uses it, then return open_db()'s
    result (None without open_db). Raises MigrationError when the folder is refused or the migration failed.
    recover_journals resolves the older build's pending operations (it may change user files); it is asked only for
    legacy data."""
    steps = STEPS if steps is None else steps
    hook = fail_at or _no_hook
    target = 1 + len(steps)
    marker = _read_marker(data)
    state = _read_state(data)
    if marker and marker["version"] > target:
        raise MigrationError(
            "newer",
            f"This data was written by a newer Bayle (data version {marker['version']}, this build knows {target}). "
            "Bayle left it alone: install the newer version again.",
        )
    if state and state["to"] != target:  # a different build began it: undo that, then start from the old data
        try:
            restore_backup(data, Path(state["backup"]))
        except (OSError, ValueError) as e:
            raise MigrationError("restore-failed", f"An earlier update could not be undone ({e}).") from e
        (data / STATE).unlink(missing_ok=True)
        state = None
    version = marker["version"] if marker else 1
    if state is None:
        if marker is None and not is_legacy(data):  # fresh: nothing to migrate
            result = open_db() if open_db else None
            write_json(data / MARKER, _marker(target, app_version, None))
            return result
        if marker is not None and version == target:
            return open_db() if open_db else None
        if marker is None:
            check_floor(data)

    hold = instance.acquire(instance.MIGRATE)
    if hold is None or instance.held(instance.WINDOW):
        if hold:
            hold.release()
        raise MigrationError("locked", "Bayle is open in another window. Close it, then start Bayle again.")
    try:
        ctx = Ctx(data, log)
        if state is None:
            if marker is None:
                log("migration: resolving the unfinished operations of the older build")
                for line in recover_journals():
                    log(f"migration: {line}")
            label = f"v{version}" if marker else (legacy_version(data) or "legacy")
            backup = make_backup(data, label, hook)
            state = {"from": label, "to": target, "step": version - 1, "backup": str(backup)}
            write_json(data / STATE, state)
        backup = Path(state["backup"])
        for i in range(state["step"], len(steps)):
            step = steps[i]
            hook(i, "before")
            try:
                step.apply(ctx)
                hook(i, "during")
                step.check(ctx)
            except Exception as e:
                raise _fail(data, backup, "step-failed", f"Updating your data failed at {step.name}", e) from e
            state["step"] = i + 1
            write_json(data / STATE, state)
            hook(i, "after")
        hook("marker", "before")
        try:
            result = open_db() if open_db else None
        except storage_db.MigrationFailed as e:  # Alembic put its own database back; the rest goes back too
            raise _fail(data, backup, "database-failed", "Updating the database failed", e) from e
        except storage_db.StorageUnavailable:
            write_json(data / MARKER, _marker(target, app_version, state["from"]))
            (data / STATE).unlink(missing_ok=True)
            raise  # storage is off for this run; the app-data part is done
        write_json(data / MARKER, _marker(target, app_version, state["from"]))
        (data / STATE).unlink(missing_ok=True)
        hook("marker", "after")
        return result
    finally:
        hold.release()
