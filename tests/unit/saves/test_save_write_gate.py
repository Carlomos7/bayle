"""The gate in front of every save write: a file the game still holds is refused, and Undo for a save write puts the
backup back after backing the current file up. Writes happen on temporary files only."""

import pytest

from bayle.game.locate import Locations
from bayle.mods import models as mod_models
from bayle.mods import undo
from bayle.saves import backups as save_backups
from bayle.saves import repair as save_repair
from bayle.services import saves as service
from support import copy_live_save, er


@pytest.fixture(autouse=True)
def game_closed(monkeypatch):
    monkeypatch.setattr(Locations, "game_running", lambda self: False)


def test_a_save_the_game_still_holds_is_refused_and_left_alone(tmp_path, monkeypatch):
    save = tmp_path / "ER0000.sl2"
    save.write_bytes(b"not touched")
    monkeypatch.setattr(save_repair, "wait_for_save_flush", lambda paths, timeout=30: False)
    with pytest.raises(RuntimeError, match="still in use"):
        service.assert_writable(save, settle_seconds=0, loc=er())
    with pytest.raises(RuntimeError, match="still in use"):
        service.fix_checksums(save, loc=er())
    assert save.read_bytes() == b"not touched"


def _undo_record(tmp_path):
    save = copy_live_save(tmp_path)
    bak = tmp_path / "older.bak"
    older = bytearray(save.read_bytes())
    older[-1] ^= 0xFF
    bak.write_bytes(bytes(older))
    return save, bak, {"type": "save-restore", "save": str(save), "backup": str(bak), "name": save.name}


def test_undo_puts_the_backup_back_after_backing_up_the_current_file(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "SETTLE_SECONDS", 0)
    save, bak, record = _undo_record(tmp_path)
    now = save.read_bytes()
    assert undo.available(record) and undo.label(record) == "Undo"
    undo.run(record, lambda *_: None, loc=er())
    assert save.read_bytes() == bak.read_bytes()
    safety = [b for b in save_backups.backups(save.parent).iterdir() if b.suffix == ".bak"]
    assert [b.read_bytes() for b in safety] == [now]


def test_undo_changes_nothing_when_the_backup_is_gone_or_the_game_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "SETTLE_SECONDS", 0)
    save, bak, record = _undo_record(tmp_path)
    now = save.read_bytes()
    monkeypatch.setattr(Locations, "game_running", lambda self: True)
    with pytest.raises(mod_models.UndoError):
        undo.run(record, lambda *_: None, loc=er())
    monkeypatch.setattr(Locations, "game_running", lambda self: False)
    bak.unlink()
    assert not undo.available(record)
    with pytest.raises(mod_models.UndoError):
        undo.run(record, lambda *_: None, loc=er())
    assert save.read_bytes() == now
