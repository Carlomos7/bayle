"""The one-way app-data migration runner (storage.datamigrations): classification, refusals, order, failure
handling, restart after a kill, idempotence, backup verification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bayle.platform import instance
from bayle.storage import db as storage_db
from bayle.storage.datamigrations import MigrationError, migrate, runner

_spec = importlib.util.spec_from_file_location("migration_child_runner", Path(__file__).with_name("child_runner.py"))
assert _spec and _spec.loader
child = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(child)
STEPS = child.STEPS


@pytest.fixture
def data(tmp_path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    child.APPLIED.clear()
    return folder


def tree(folder: Path, skip: tuple[str, ...] = ()) -> dict[str, str]:
    """Every file under folder with its sha256."""
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and not p.relative_to(folder).as_posix().startswith(skip)
    }


def marker(folder: Path) -> dict:
    return json.loads((folder / runner.MARKER).read_text(encoding="utf-8"))


class Killed(BaseException):
    """Stands for the process dying: not an Exception, so the runner does not treat it as a failed step."""


def die_at(spot: tuple):
    def hook(step, phase):
        if (step, phase) == spot:
            raise Killed

    return hook


def test_fresh_writes_the_marker_and_runs_nothing(data):
    (data / "logs").mkdir()
    (data / "logs" / "launcher.log").write_text("x", encoding="utf-8")
    called = []
    migrate(data, "5.0.0", steps=STEPS, recover_journals=lambda: called.append(1) or [])
    assert marker(data)["version"] == 3 and marker(data)["app"] == "5.0.0"
    assert child.APPLIED == [] and called == []
    assert not (data / runner.BACKUPS).exists() and not (data / runner.STATE).exists()


def test_legacy_without_steps_recovers_journals_then_backs_up(data):
    child.make_legacy(data)
    before = tree(data)
    order = []

    def recover():
        order.append("journals")
        assert not (data / runner.BACKUPS).exists()  # nothing is backed up before the journals are resolved
        return ["finished an install"]

    migrate(data, "5.0.0", steps=[], recover_journals=recover, open_db=lambda: order.append("db"))
    assert order == ["journals", "db"]
    assert marker(data)["version"] == 1 and marker(data)["migrated_from"] == "4.5.1"
    (backup,) = (data / runner.BACKUPS).iterdir()
    assert set(runner.verify_backup(backup)) == {"launcher_settings.json", "merges.json", "updates/state/ready-4.5.1"}
    assert {k: v for k, v in tree(data, (runner.BACKUPS, runner.MARKER)).items()} == before
    assert not (data / runner.STATE).exists()


def test_legacy_runs_the_steps_in_order_after_the_backup(data):
    child.make_legacy(data)
    migrate(data, "5.0.0", steps=STEPS)
    assert child.APPLIED == ["one", "two"] and marker(data)["version"] == 3
    assert json.loads((data / "launcher_settings.json").read_text())["migrated_one"]


def test_current_data_is_left_alone(data):
    migrate(data, "5.0.0", steps=STEPS)
    before = tree(data)
    opened = []
    migrate(data, "5.0.1", steps=STEPS, open_db=lambda: opened.append(1))
    assert opened == [1] and tree(data) == before


def test_newer_marker_refuses_and_touches_nothing(data):
    child.make_legacy(data)
    (data / runner.MARKER).write_text(json.dumps({"version": 99}), encoding="utf-8")
    before = tree(data)
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=STEPS, recover_journals=lambda: pytest.fail("touched"), open_db=lambda: 1 / 0)
    assert e.value.code == "newer" and isinstance(e.value, storage_db.MigrationFailed)
    assert tree(data) == before and sorted(p.name for p in data.iterdir()) == sorted(
        {"launcher_settings.json", "merges.json", "updates", "logs", runner.MARKER}
    )


@pytest.mark.parametrize("text", ["{not json", "[]", '{"version": "2"}', '{"version": 0}', ""])
def test_corrupt_marker_refuses_with_a_repair_hint(data, text):
    child.make_legacy(data)
    (data / runner.MARKER).write_text(text, encoding="utf-8")
    before = tree(data)
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=STEPS)
    assert e.value.code == "corrupt-marker" and runner.MARKER in str(e.value) and "restore" in str(e.value)
    assert tree(data) == before


def test_below_floor_names_the_release_to_install_first(data):
    child.make_legacy(data)
    (data / "updates" / "state" / "ready-4.5.1").unlink()
    (data / "updates" / "state" / "ready-4.4.0").write_text("window 1", encoding="utf-8")
    before = tree(data)
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=STEPS)
    assert e.value.code == "below-floor" and "4.4.0" in str(e.value) and runner.INSTALL_FIRST in str(e.value)
    assert tree(data) == before


def test_floor_itself_and_a_prerelease_of_it_are_accepted(data, tmp_path):
    for version in ("4.5.0", "4.6.0-rc.3"):
        folder = tmp_path / version
        child.make_legacy(folder)
        (folder / "updates" / "state" / "ready-4.5.1").unlink()
        (folder / "updates" / "state" / f"ready-{version}").write_text("window 1", encoding="utf-8")
        migrate(folder, "5.0.0", steps=[])
        assert marker(folder)["version"] == 1


def test_database_below_0004_is_below_floor(data):
    child.make_legacy(data)
    import sqlite3

    con = sqlite3.connect(data / storage_db.DB_NAME)
    con.execute("create table alembic_version (version_num text)")
    con.execute("insert into alembic_version values ('0002')")
    con.commit()
    con.close()
    (data / "updates" / "state" / "ready-4.5.1").unlink()
    (data / "launcher_settings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=STEPS)
    assert e.value.code == "below-floor"


def test_a_killed_run_resumes_at_the_recorded_step(data):
    child.make_legacy(data)
    with pytest.raises(Killed):
        migrate(data, "5.0.0", steps=STEPS, fail_at=die_at((0, "after")))
    state = json.loads((data / runner.STATE).read_text())
    assert state["step"] == 1 and state["to"] == 3 and not (data / runner.MARKER).exists()
    child.APPLIED.clear()
    migrate(data, "5.0.0", steps=STEPS, recover_journals=lambda: pytest.fail("journals are resolved once"))
    assert child.APPLIED == ["two"]  # step one is not run again
    assert marker(data)["version"] == 3 and not (data / runner.STATE).exists()


def test_a_step_that_raises_puts_the_data_back_exactly(data):
    child.make_legacy(data)
    before = tree(data)

    def boom(ctx):
        raise RuntimeError("disk on fire")

    steps = [STEPS[0], runner.Step("boom", boom, lambda c: None)]
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=steps)
    assert e.value.code == "step-failed" and "boom" in str(e.value)
    assert tree(data, (runner.BACKUPS,)) == before
    assert not (data / runner.STATE).exists() and not (data / runner.MARKER).exists()
    assert list((data / runner.BACKUPS).iterdir())  # the backup is kept


def test_a_failed_check_puts_the_data_back_exactly(data):
    child.make_legacy(data)
    before = tree(data)

    def bad(ctx):
        raise AssertionError("not canonical")

    steps = [runner.Step("made-a-file", lambda c: (c.data / "merges.json").write_text("changed"), bad)]
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=steps)
    assert e.value.code == "step-failed"
    assert tree(data, (runner.BACKUPS,)) == before


def test_a_failure_removes_files_the_steps_made(data):
    child.make_legacy(data)
    before = tree(data)
    made = runner.Step(
        "made",
        lambda c: (c.data / "cache").mkdir() or (c.data / "cache" / "hashes.json").write_text("{}"),
        lambda c: None,
    )
    boom = runner.Step("boom", lambda c: 1 / 0, lambda c: None)
    with pytest.raises(MigrationError):
        migrate(data, "5.0.0", steps=[made, boom])
    assert tree(data, (runner.BACKUPS,)) == before


def test_database_failure_restores_the_app_data(data):
    child.make_legacy(data)
    before = tree(data)

    def open_db():
        raise storage_db.MigrationFailed("alembic broke")

    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=STEPS, open_db=open_db)
    assert e.value.code == "database-failed"
    assert tree(data, (runner.BACKUPS,)) == before


def test_storage_unavailable_still_completes_the_data_migration(data):
    child.make_legacy(data)

    def open_db():
        raise storage_db.StorageUnavailable("busy")

    with pytest.raises(storage_db.StorageUnavailable):
        migrate(data, "5.0.0", steps=STEPS, open_db=open_db)
    assert marker(data)["version"] == 3 and not (data / runner.STATE).exists()


def test_running_twice_changes_nothing_and_each_step_is_idempotent(data):
    child.make_legacy(data)
    migrate(data, "5.0.0", steps=STEPS)
    done = tree(data)
    migrate(data, "5.0.0", steps=STEPS)
    assert tree(data) == done
    ctx = runner.Ctx(data, lambda line: None)
    for step in STEPS:
        step.apply(ctx)
        step.apply(ctx)
        step.check(ctx)
    assert tree(data, (runner.BACKUPS, runner.MARKER)) == {
        k: v for k, v in done.items() if not k.startswith((runner.BACKUPS, runner.MARKER))
    }


def test_backup_verification_detects_corruption(data):
    child.make_legacy(data)
    backup = runner.make_backup(data, "x", lambda s, p: None)
    assert runner.verify_backup(backup)
    target = backup / "files" / "merges.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(ValueError, match="merges.json"):
        runner.verify_backup(backup)
    target.unlink()
    with pytest.raises(ValueError):
        runner.verify_backup(backup)


def test_a_damaged_backup_is_not_restored_over_the_data(data):
    child.make_legacy(data)

    def ruin(ctx):
        (ctx.data / "merges.json").write_text("ruined", encoding="utf-8")
        for f in (ctx.data / runner.BACKUPS).glob("*/files/merges.json"):
            f.write_text("also ruined", encoding="utf-8")
        raise RuntimeError("step failed")

    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=[runner.Step("ruin", ruin, lambda c: None)])
    assert e.value.code == "restore-failed" and (data / runner.STATE).exists()


def test_a_backup_that_cannot_be_made_stops_before_any_step(data):
    child.make_legacy(data)
    with pytest.raises(MigrationError) as e:
        migrate(
            data,
            "5.0.0",
            steps=STEPS,
            fail_at=lambda s, p: (_ for _ in ()).throw(OSError("disk full")) if s == "backup" else None,
        )
    assert e.value.code == "backup-failed" and child.APPLIED == []
    assert not (data / runner.BACKUPS).exists() or not list((data / runner.BACKUPS).iterdir())


def test_another_migration_running_refuses(data):
    child.make_legacy(data)
    hold = instance.acquire(instance.MIGRATE)
    assert hold
    try:
        with pytest.raises(MigrationError) as e:
            migrate(data, "5.0.0", steps=STEPS)
        assert e.value.code == "locked" and child.APPLIED == []
    finally:
        hold.release()


def test_a_state_file_that_cannot_be_read_refuses(data):
    child.make_legacy(data)
    (data / runner.STATE).write_text("{", encoding="utf-8")
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", steps=STEPS)
    assert e.value.code == "state-corrupt"


BOUNDARIES = (
    ["backup:during"]
    + [f"{i}:{p}" for i in (0, 1) for p in ("before", "during", "after")]
    + ["marker:before", "marker:after"]
)


@pytest.mark.parametrize("spot", BOUNDARIES)
def test_a_killed_process_is_finished_by_the_next_start(tmp_path, spot):
    run = tmp_path / "killed"
    ref = tmp_path / "reference"
    child.make_legacy(run)
    child.make_legacy(ref)
    migrate(ref, "9.9.9", steps=STEPS)
    proc = subprocess.Popen(
        [sys.executable, str(Path(child.__file__)), str(run), spot], stdout=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "AT"
    finally:
        proc.kill()
        proc.wait()
    child.APPLIED.clear()
    migrate(run, "9.9.9", steps=STEPS)  # the restart
    assert marker(run)["version"] == 3 and not (run / runner.STATE).exists()
    skip = (runner.BACKUPS, runner.MARKER)
    assert tree(run, skip) == tree(ref, skip)


def test_create_app_migrates_before_it_opens_the_database():
    from bayle.app import create_app
    from bayle.platform import data_folder

    folder = data_folder.data_root()  # conftest points it at the test's own folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "launcher_settings.json").write_text("{}", encoding="utf-8")  # a legacy folder
    ctx = create_app()
    try:
        assert marker(folder)["version"] == runner.CURRENT_VERSION and ctx.storage is not None
        assert list((folder / runner.BACKUPS).iterdir())
    finally:
        ctx.close()
