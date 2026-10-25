"""merges.json -> rebuild_runs: the file stays authoritative (an older build restored by the watchdog only knows it);
the row follows it and is repaired from it. Real temporary databases; the data folder is the conftest's temp one."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from bayle.adapters.persistence import db, models
from bayle.adapters.persistence.rebuild_runs import RebuildRuns, fingerprint
from bayle.modules.mods import rebuild
from bayle.runtime import bootstrap

pytestmark = pytest.mark.skipif(db.sqlite_problem() is not None, reason=str(db.sqlite_problem()))


@pytest.fixture
def data(tmp_path):
    return tmp_path / "launcher-data"


@pytest.fixture
def runs(data):
    data.mkdir(parents=True, exist_ok=True)
    d = db.open_database(data, log=lambda line: None)
    store = RebuildRuns(d)
    bootstrap.bind(run_store=store)
    yield store
    bootstrap.bind(run_store=None)
    d.close()


def _rows(store):
    with store.db.unit_of_work() as s:
        return [(r.profile, r.ok, r.message, r.fingerprint) for r in s.scalars(select(models.RebuildRun))]


def _profile(tmp_path, name="p.me3"):
    p = tmp_path / name
    p.write_text("x", encoding="utf-8")
    return p


def test_round_trip_file_then_row(runs, data, tmp_path):
    p = _profile(tmp_path)
    rebuild.note_run(p, False, "boom")
    entry = rebuild.last_run(p)
    assert entry is not None and entry["message"] == "boom"
    assert json.loads((data / "merges.json").read_text(encoding="utf-8")) == {
        next(iter(json.loads((data / "merges.json").read_text(encoding="utf-8")))): entry
    }
    [(profile, ok, message, fp)] = _rows(runs)
    assert (ok, message, fp) == (False, "boom", fingerprint(entry))


def test_interrupted_row_write_the_file_wins_and_the_row_heals(runs, data, tmp_path, monkeypatch):
    p = _profile(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(runs, "_put", lambda *a: (_ for _ in ()).throw(RuntimeError("database stopped")))
        rebuild.note_run(p, True, "fine")  # the row write fails: the file already has it
        assert rebuild.last_run(p)["message"] == "fine"
        assert _rows(runs) == []
    rebuild.last_run(p)  # next use repairs the row from the file
    assert [r[2] for r in _rows(runs)] == ["fine"]


def test_an_older_writer_between_two_runs_loses_nothing(runs, data, tmp_path):
    p = _profile(tmp_path)
    rebuild.note_run(p, True, "new build")
    key = next(iter(json.loads((data / "merges.json").read_text(encoding="utf-8"))))
    # the watchdog restored an older build: it rewrites the file in the same format, no database
    old = {key: {"when": 1.0e9, "ok": False, "message": "old build"}, "other": {"when": 5.0, "ok": True, "message": ""}}
    (data / "merges.json").write_text(json.dumps(old, indent=1), encoding="utf-8")
    entry = rebuild.last_run(p)
    assert entry["message"] == "old build"  # the file wins
    assert "old build" in [r[2] for r in _rows(runs)]  # the row was repaired
    assert runs.import_file(data / "merges.json")
    assert {r[0] for r in _rows(runs)} == {key, "other"}
    rebuild.note_run(p, True, "new build again")  # the newer build still writes the file whole, keeping "other"
    assert "other" in json.loads((data / "merges.json").read_text(encoding="utf-8"))


def test_import_from_a_real_shaped_old_merges_file_is_idempotent(runs, data):
    old = {
        r"c:\users\x\profiles\er.me3": {"when": 1760000000.5, "ok": True, "message": ""},
        r"c:\users\x\profiles\er-coop.me3": {"when": 1760000100.25, "ok": False, "message": "Rebuild tool missing"},
    }
    (data / "merges.json").write_text(json.dumps(old, indent=1), encoding="utf-8")
    assert runs.import_file(data / "merges.json") and runs.import_file(data / "merges.json")
    assert len(_rows(runs)) == 2
    with runs.db.unit_of_work() as s:
        assert s.get(models.ImportState, "merges.json").verified_at is not None


def test_a_damaged_file_is_not_imported_and_left_alone(runs, data):
    (data / "merges.json").write_text("{not json", encoding="utf-8")
    assert runs.import_file(data / "merges.json") is False
    assert (data / "merges.json").read_text(encoding="utf-8") == "{not json"


def test_only_the_newest_rows_per_profile_are_kept(runs):
    for n in range(30):
        runs.record("p", {"when": 1000.0 + n, "ok": True, "message": str(n)})
    rows = _rows(runs)
    assert len(rows) == 20 and rows[-1][2] == "29"


def test_without_a_store_the_file_alone_works(data, tmp_path):
    bootstrap.bind(run_store=None)
    p = _profile(tmp_path)
    rebuild.note_run(p, True, "ok")
    assert rebuild.last_run(Path(p))["ok"] is True
