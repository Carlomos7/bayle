"""The Engine (runtime.bootstrap): one start runs the journal recovery once, the shell runs on the Engine's jobs and
bus, close() unbinds what the engine bound, and a second engine after it binds afresh."""

from pathlib import Path

from bayle.mods import rebuild
from bayle.platform import cpu
from bayle.runtime.bootstrap import create_engine
from bayle.saves import ports
from bayle.services import mods as mod_service
from bayle.services import startup_recovery
from bayle.session import startup

from bayle_qt.shell.service import Shell
from bayle_qt.shell.state import LauncherState
from support import InlineBackground


def _full_start(monkeypatch, remembered: Path, in_use: Path) -> tuple[list, Shell]:
    """create_engine, then the shell's start-up as the window runs it; every recovery is counted, not run."""
    calls = []
    monkeypatch.setattr(
        startup_recovery.core, "remembered_profile", lambda s, g: str(remembered) if g.key == "eldenring" else None
    )
    monkeypatch.setattr(mod_service, "recover_interrupted", lambda p, timeout: calls.append(Path(p)) or [f"fixed {p}"])
    monkeypatch.setattr(startup.run_health, "recover_all", lambda: [])
    monkeypatch.setattr(startup.saves_page, "adopt_legacy_folders", lambda *a, **k: [])
    monkeypatch.setattr(LauncherState, "profile_path", lambda self: in_use)
    engine = create_engine()
    shell = Shell(engine, background=InlineBackground())
    monkeypatch.setattr(shell.watch, "start", lambda: None)
    shell.startup()
    engine.close()
    return calls, shell


def _notices(shell: Shell) -> list[str]:
    sub = shell.bus.subscribe(since=0)
    return [e.data["text"] for e in iter(lambda: sub.get(0), None) if e.type == "notice"]


def test_a_full_start_recovers_the_remembered_profile_once(tmp_path, monkeypatch):
    profile = tmp_path / "main.me3"
    calls, shell = _full_start(monkeypatch, profile, profile)
    assert calls == [profile] and _notices(shell) == []  # the start already logged what it put right


def test_the_profile_in_use_is_recovered_when_the_start_did_not_cover_it(tmp_path, monkeypatch):
    calls, shell = _full_start(monkeypatch, tmp_path / "gone.me3", tmp_path / "first.me3")
    assert calls == [tmp_path / "gone.me3", tmp_path / "first.me3"]
    assert _notices(shell) == [f"fixed {tmp_path / 'first.me3'}"]  # what the start-up step put right is told


def test_the_shell_runs_on_the_engines_jobs_and_bus():
    engine = create_engine()
    try:
        shell = Shell(engine, background=InlineBackground())
        assert shell.jobs is engine.jobs and shell.bus is engine.bus
        # Activity reads the engine's activity log and gates its undo on the engine's job manager
        assert engine.activity is not None
        assert shell.activity._store is engine.activity and shell.activity._jobs is engine.jobs
        assert shell.features.activity is shell.activity
    finally:
        engine.close()


def test_close_unbinds_and_a_second_engine_binds_afresh():
    def backend(task, args):
        raise AssertionError("not called")

    first = create_engine()
    assert first.storage is not None and rebuild._HASH_STORE is first.hash_cache
    first.use_cpu(backend, backend, 1)
    assert cpu._backend is backend and cpu._ui_thread == 1
    first.close()
    assert rebuild._HASH_STORE is None and rebuild._RUN_STORE is None and ports._CURRENT is None
    assert cpu._backend is None and cpu._ui_thread is None
    second = create_engine()
    try:
        assert second.storage is not None and rebuild._HASH_STORE is second.hash_cache
        assert second.jobs.store is second.activity and ports._CURRENT is not None
    finally:
        second.close()
