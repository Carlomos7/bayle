from pathlib import Path
from types import SimpleNamespace

from bayle.session import startup


def test_recovery_steps_order_and_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(startup.run_health, "recover_all", lambda: calls.append("runs") or [])
    monkeypatch.setattr(
        startup.mod_service, "recover_interrupted", lambda p, timeout: calls.append(("mods", p)) or ["x"]
    )
    monkeypatch.setattr(
        startup.save_backups, "adopt_legacy_save_folders", lambda d, g, again: calls.append(("adopt", d))
    )
    loc = SimpleNamespace(game="g", save_files=lambda: [Path("a/1.sl2"), Path("a/2.sl2"), Path("b/1.sl2")])

    steps = startup.recovery_steps(loc, Path("p.json"))
    assert [s.name for s in steps] == ["run_health", "interrupted_installs", "legacy_save_folders"]
    for s in steps:
        s.fn()
    assert calls == ["runs", ("mods", Path("p.json")), ("adopt", Path("a")), ("adopt", Path("b"))]
    assert [s.name for s in startup.recovery_steps(loc)] == ["run_health", "legacy_save_folders"]
