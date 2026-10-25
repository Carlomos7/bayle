"""The app-data version marker (storage.datamigrations): baseline stamp, refusals, journal recovery on every start,
the durable write."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from bayle.adapters.persistence import db as storage_db
from bayle.adapters.persistence.datamigrations import MigrationError, migrate, runner, write_json


@pytest.fixture
def data(tmp_path) -> Path:
    folder = tmp_path / "data"
    folder.mkdir()
    return folder


def tree(folder: Path) -> dict[str, str]:
    return {
        p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def make_existing(data: Path) -> None:
    (data / "launcher_settings.json").write_text('{"game": "eldenring"}', encoding="utf-8")
    (data / "layout-ops").mkdir()
    (data / "layout-ops" / "pending.json").write_text("{}", encoding="utf-8")


def marker(folder: Path) -> dict:
    return json.loads((folder / runner.MARKER).read_text(encoding="utf-8"))


def test_fresh_folder_gets_the_baseline_marker(data):
    migrate(data, "5.0.0")
    assert marker(data)["version"] == 1 and marker(data)["app"] == "5.0.0"
    assert [p.name for p in data.iterdir()] == [runner.MARKER]


def test_existing_data_without_a_marker_only_gains_the_marker(data):
    make_existing(data)
    before = tree(data)
    migrate(data, "5.0.0")
    after = tree(data)
    assert after.pop(runner.MARKER) and after == before and marker(data)["version"] == 1


def test_current_marker_changes_nothing(data):
    migrate(data, "5.0.0")
    before = tree(data)
    opened = []
    migrate(data, "5.0.1", open_db=lambda: opened.append(1))
    assert opened == [1] and tree(data) == before


def test_newer_marker_refuses_and_touches_nothing(data):
    make_existing(data)
    (data / runner.MARKER).write_text(json.dumps({"version": 99}), encoding="utf-8")
    before = tree(data)
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", recover_journals=lambda: pytest.fail("touched"), open_db=lambda: 1 / 0)
    assert e.value.code == "newer" and isinstance(e.value, storage_db.MigrationFailed)
    assert tree(data) == before


@pytest.mark.parametrize("text", ["{not json", "[]", '{"version": "2"}', '{"version": 0}', ""])
def test_corrupt_marker_refuses_with_a_repair_hint(data, text):
    make_existing(data)
    (data / runner.MARKER).write_text(text, encoding="utf-8")
    before = tree(data)
    with pytest.raises(MigrationError) as e:
        migrate(data, "5.0.0", recover_journals=lambda: pytest.fail("touched"))
    assert e.value.code == "corrupt-marker" and runner.MARKER in str(e.value) and "restore" in str(e.value)
    assert tree(data) == before


def test_journals_are_resolved_before_the_database_opens_on_every_start(data):
    order = []

    def recover():
        order.append("journals")
        return ["finished an install"]

    for _ in range(2):  # without a marker, then with one
        migrate(data, "5.0.0", recover_journals=recover, open_db=lambda: order.append("db"))
    assert order == ["journals", "db", "journals", "db"]


def test_create_engine_recovers_and_stamps_before_it_opens_the_database(monkeypatch):
    from bayle.adapters.system import data_folder
    from bayle.runtime import startup_recovery
    from bayle.runtime.bootstrap import create_engine

    ran = []
    monkeypatch.setattr(startup_recovery, "recover", lambda covered=None: ran.append(1) or [])
    folder = data_folder.data_root()  # conftest points it at the test's own folder
    folder.mkdir(parents=True, exist_ok=True)
    ctx = create_engine()
    try:
        assert ran == [1] and marker(folder)["version"] == runner.CURRENT_VERSION and ctx.storage is not None
    finally:
        ctx.close()


def test_write_json_replaces_whole_and_leaves_no_temp_file(data):
    target = data / "x.json"
    write_json(target, {"a": 1})
    write_json(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 2} and [p.name for p in data.iterdir()] == ["x.json"]


def test_a_process_killed_mid_write_leaves_the_old_file_whole(data):
    target = data / "x.json"
    write_json(target, {"a": 1})
    code = (
        "import json, os, sys, time\n"
        "from pathlib import Path\n"
        "os.replace = lambda *a: (print('AT', flush=True), time.sleep(120))\n"  # stop just before the rename
        "from bayle.adapters.persistence.datamigrations import write_json\n"
        "write_json(Path(sys.argv[1]), {'a': 2})\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code, str(target)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "AT"
    finally:
        proc.kill()
        proc.wait()
    assert json.loads(target.read_text()) == {"a": 1}
