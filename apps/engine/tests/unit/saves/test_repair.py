"""The after-play regulation repair: the game, the saves and the regulation repair are faked; nothing is read from the
developer's install or saves."""

from types import SimpleNamespace

import pytest

from bayle.modules.saves import nightreign_repair, regulation
from bayle.modules.saves import repair as after_play


@pytest.fixture
def lines(monkeypatch):
    out = []
    monkeypatch.setattr(after_play, "log", out.append)
    monkeypatch.setattr(after_play, "fail", _fail)
    return out


def _fail(msg, code=1):
    raise SystemExit(f"{code}: {msg}")


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(after_play, "wait_for_save_flush", lambda saves, timeout=30: True)


def install(**kwargs):
    base = dict(
        name="Elden Ring",
        regulation_repair=True,
        save_reader="er",
        running=False,
        saves=[],
        regulation=None,
    )
    base.update(kwargs)
    game = SimpleNamespace(
        name=base["name"], regulation_repair=base["regulation_repair"], save_reader=base["save_reader"]
    )
    return SimpleNamespace(
        game=game,
        save_files=lambda: list(base["saves"]),
        game_running=lambda: base["running"],
        regulation_bin=lambda: base["regulation"],
    )


def test_a_game_without_repair_says_so_and_stops(lines):
    after_play.repair_all(install(regulation_repair=False))
    assert lines == ["Elden Ring: no save repair after play"]


def test_no_saves_on_the_pc_stops(lines):
    after_play.repair_all(install(saves=[]))
    assert lines == ["no Elden Ring saves found on this PC"]


def test_a_running_game_is_never_touched(lines, tmp_path):
    with pytest.raises(SystemExit):
        after_play.repair_all(install(saves=[tmp_path / "ER0000.sl2"], running=True))


def test_nightreign_repairs_every_save_through_its_own_repair(monkeypatch, lines, tmp_path):
    saves = [tmp_path / "a.co2", tmp_path / "b.co2"]
    monkeypatch.setattr(nightreign_repair, "repair", lambda save, log: 1)
    after_play.repair_all(install(name="Nightreign", save_reader="nightreign", saves=saves))
    assert lines[-1] == "done: 2 repaired"


def test_elden_ring_needs_its_regulation_bin(lines, tmp_path):
    with pytest.raises(SystemExit):
        after_play.repair_all(install(saves=[tmp_path / "ER0000.sl2"], regulation=None))


def test_elden_ring_repairs_each_save_from_the_regulation(monkeypatch, lines, tmp_path):
    source = tmp_path / "regulation.bin"
    source.write_bytes(b"x" * 0x200000)
    saves = [tmp_path / "ER0000.sl2", tmp_path / "ER0001.sl2"]
    calls = []
    monkeypatch.setattr(regulation, "load_regulation", lambda src: (b"reg", b"hdr"))
    monkeypatch.setattr(regulation, "plausible_regulation", lambda reg: True)
    monkeypatch.setattr(regulation, "repair", lambda save, reg, header: calls.append((save, reg, header)) or 1)
    after_play.repair_all(install(saves=saves, regulation=source))
    assert calls == [(saves[0], b"reg", b"hdr"), (saves[1], b"reg", b"hdr")]
    assert lines[-1] == "done: 2 repaired"


def test_a_misplaced_regulation_is_refused(monkeypatch, lines, tmp_path):
    monkeypatch.setattr(regulation, "load_regulation", lambda src: (b"reg", b"hdr"))
    monkeypatch.setattr(regulation, "plausible_regulation", lambda reg: False)
    with pytest.raises(SystemExit):
        after_play.repair_all(install(saves=[tmp_path / "ER0000.sl2"], regulation=tmp_path / "r.bin"))


def test_the_flush_wait_gives_up_after_its_timeout(monkeypatch, lines, tmp_path):
    monkeypatch.undo()  # the real wait, not the autouse no-op
    monkeypatch.setattr(after_play, "log", lines.append)
    monkeypatch.setattr(after_play.time, "sleep", lambda seconds: None)
    locked = tmp_path / "missing.sl2"  # cannot be opened: stands for a save the game still holds
    assert after_play.wait_for_save_flush([locked], timeout=0.05) is False
    assert lines == [f"warning: still locked after 0.05s: {locked}"]


def test_the_flush_wait_returns_when_the_saves_can_be_opened(monkeypatch, tmp_path):
    monkeypatch.undo()
    save = tmp_path / "ER0000.sl2"
    save.write_bytes(b"save")
    assert after_play.wait_for_save_flush([save], timeout=5) is True
