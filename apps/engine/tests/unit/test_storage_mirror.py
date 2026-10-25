"""Backup notes and keep flags, profile history and the save library's library.json mirrored in the database. The
files stay authoritative (an older build restored by the watchdog reads and writes only them); the row follows and is
repaired from the file; an uncertain keep flag always prevents pruning. Real temporary databases."""

import json
import os
import sqlite3

import pytest

from bayle.adapters.persistence import db, mirror
from bayle.modules.mods import history
from bayle.modules.saves import backups, ports
from bayle.runtime import bootstrap

pytestmark = pytest.mark.skipif(db.sqlite_problem() is not None, reason=str(db.sqlite_problem()))


@pytest.fixture
def mir(tmp_path):
    data = tmp_path / "launcher-data"
    data.mkdir(parents=True, exist_ok=True)
    d = db.open_database(data, log=lambda line: None)
    m = mirror.Mirror(d)
    bootstrap.bind(mirror=m)
    yield m
    bootstrap.bind(mirror=None)
    d.close()


@pytest.fixture
def bak(tmp_path):
    folder = tmp_path / "saves" / "backups"
    folder.mkdir(parents=True)
    f = folder / "ER0000.sl2.20260101-000000.bak"
    f.write_bytes(b"save")
    return f


def _note(bak_path):
    return bak_path.with_name(bak_path.name + ".json")


def _rows(m):
    conn = sqlite3.connect(m.db.path)
    try:
        return {
            (k, os.path.basename(key)): fp
            for k, key, fp in conn.execute("SELECT kind, key, fingerprint FROM record_mirror")
        }
    finally:
        conn.close()


def test_backup_note_round_trip_file_then_row(mir, bak):
    backups.write_note(bak, {"action": "edit", "keep": True})
    assert json.loads(_note(bak).read_text(encoding="utf-8"))["keep"] is True  # the old format, untouched
    row = mir.row(ports.BACKUP_NOTE, _note(bak))
    assert row is not None and row.fingerprint == mirror.fingerprint(_note(bak).read_bytes())
    assert backups.protection(bak) == backups.KEPT
    backups.set_keep(bak, False)
    assert backups.protection(bak) == backups.NOT_KEPT
    assert json.loads(mir.row(ports.BACKUP_NOTE, _note(bak)).payload)["keep"] is False


def test_deleting_a_backup_removes_its_row(mir, bak):
    backups.write_note(bak, {"keep": False})
    backups.delete(bak)
    assert mir.row(ports.BACKUP_NOTE, _note(bak)) is None


def test_interrupted_row_write_leaves_the_file_and_the_next_write_heals(mir, bak, monkeypatch):
    backups.write_note(bak, {"keep": False})
    with monkeypatch.context() as m:
        m.setattr(mir.db, "unit_of_work", lambda: (_ for _ in ()).throw(RuntimeError("database stopped")))
        backups.set_keep(bak, True)  # the file is written; the row is not
    assert backups.protection(bak) == backups.KEPT  # the file says keep
    assert mir.row(ports.BACKUP_NOTE, _note(bak)).fingerprint != mirror.fingerprint(_note(bak).read_bytes())
    mir.sync(ports.BACKUP_NOTE, _note(bak))
    assert mir.row(ports.BACKUP_NOTE, _note(bak)).fingerprint == mirror.fingerprint(_note(bak).read_bytes())


def test_an_older_build_that_unkept_a_backup_cannot_make_pruning_remove_it(mir, bak):
    backups.set_keep(bak, True)
    # the watchdog restored an older build, which rewrote the note in the same format without keep
    _note(bak).write_text(json.dumps({"action": "edit", "keep": False}), encoding="utf-8")
    assert backups.protection(bak) != backups.NOT_KEPT and backups.is_kept(bak)
    # the new build's own explicit choice clears the doubt
    backups.set_keep(bak, False)
    assert backups.protection(bak) == backups.NOT_KEPT


def test_a_note_that_vanished_while_the_row_says_keep_keeps_the_backup(mir, bak):
    backups.set_keep(bak, True)
    _note(bak).unlink()  # an older build, or a crash, removed the note
    assert backups.is_kept(bak)


def test_an_older_build_that_kept_more_loses_nothing(mir, bak):
    backups.set_keep(bak, False)
    _note(bak).write_text(json.dumps({"keep": True, "extra": 1}), encoding="utf-8")  # old build marked it keep
    assert backups.protection(bak) == backups.KEPT


def test_without_a_mirror_the_files_alone_work(bak):
    bootstrap.bind(mirror=None)
    backups.set_keep(bak, True)
    assert backups.protection(bak) == backups.KEPT and not ports.keep_doubt(_note(bak))


def test_history_index_is_mirrored_and_an_older_writer_is_harmless(mir, tmp_path):
    d = tmp_path / "hist"
    d.mkdir()
    history._write_index(d, {"a.me3": "why a"})
    row = mir.row(ports.HISTORY, d / history.INDEX)
    assert json.loads(row.payload) == {"a.me3": "why a"}
    (d / history.INDEX).write_text(json.dumps({"a.me3": "why a", "b.me3": "old build"}), encoding="utf-8")
    assert history._index(d) == {"a.me3": "why a", "b.me3": "old build"}  # the file wins
    history._write_index(d, history._index(d))
    assert json.loads(mir.row(ports.HISTORY, d / history.INDEX).payload)["b.me3"] == "old build"


def test_library_manifest_is_mirrored_from_a_real_shaped_old_folder(mir, tmp_path):
    from bayle.modules.saves import library

    save_dir = tmp_path / "saves" / "76561198000000000"
    save_dir.mkdir(parents=True)
    old = {"version": 1, "entries": []}
    folder = library.folder_for(save_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / library.MANIFEST).write_text(json.dumps(old), encoding="utf-8")  # written by an older build
    library._save(save_dir, library.load(save_dir))
    assert ("library", library.MANIFEST) in _rows(mir)
