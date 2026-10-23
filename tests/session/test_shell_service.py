"""The shell behind the Session (WP19): top-bar facts as a page, the game watch's push events and the writes gate,
the Launch flow's questions over the prompt broker, start-up ownership. No Qt, no game, no me3: every worker is inline."""

import time

import pytest

from bayle.errors import Busy, OperationError
from bayle.platform import logging as run_logging
from bayle.services import play as core
from bayle.session import Session, reset_process_globals, startup
from bayle.session import ops as _ops  # noqa: F401  registers the operations
from bayle.session.shell.service import Shell
from bayle.views.common import Choice, Choose
from bayle.work.jobs import JobManager
from support import FakeShellContext, InlineBackground


def inline(run, name=None):
    run()


@pytest.fixture
def shell(tmp_path):
    reset_process_globals()
    s = Shell(FakeShellContext(tmp_path), background=InlineBackground(), spawn=inline)
    yield s
    reset_process_globals()


@pytest.fixture
def threaded(tmp_path):
    """A shell whose jobs run on real threads (a job that waits for an answer needs one)."""
    reset_process_globals()
    s = Shell(FakeShellContext(tmp_path), background=InlineBackground())
    yield s
    reset_process_globals()


def events(shell):
    sub = shell.bus.subscribe(since=0)
    out = []
    while (e := sub.get(0)) is not None:
        out.append(e)
    sub.close()
    return out


def types(shell):
    return [e.type for e in events(shell)]


def wait_until(check, seconds=5.0):
    deadline = time.time() + seconds
    while not check() and time.time() < deadline:
        time.sleep(0.01)
    assert check()


# ---------------------------------------------------------------- the top bar as a page
def test_the_shell_snapshot_reads_without_writing(shell, tmp_path):
    def stamp():
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in tmp_path.rglob("*") if p.is_file())

    before = stamp()
    view = shell.session.snapshot("shell")
    assert view.game == "eldenring" and view.pill.mode == "profile" and view.status.text
    assert [g.key for g in view.games if g.checked] == ["eldenring"] and view.updates.notices == ()
    assert stamp() == before


# ---------------------------------------------------------------- game.state and the writes gate
def test_game_state_is_pushed_and_a_running_game_refuses_writing_jobs(shell):
    shell._on_running(True)
    got = [e for e in events(shell) if e.type == "game.state"]
    assert got[-1].data == {"game": "eldenring", "running": True, "steam_problem": False, "dead_shells": 0}
    assert "invalidated" in types(shell)
    with pytest.raises(Busy) as refused:
        shell.session.start(lambda ctx: None, title="write")
    assert refused.value.details["reason"] == "game_running"
    shell.session.start(lambda ctx: None, title="read", writes=False)  # reads pass
    shell._on_running(False)
    shell.session.start(lambda ctx: None, title="write again")


def test_a_change_is_pushed_once_and_the_same_state_not_at_all(shell):
    shell._on_shells(2)
    shell._on_shells(2)
    shell._on_steam(False)
    assert [e.data["dead_shells"] for e in events(shell) if e.type == "game.state"] == [2]


def test_clearing_leftover_processes_may_run_while_the_game_does(shell, monkeypatch):
    ran = []
    monkeypatch.setattr(core, "job_clear", lambda launch, loc: ran.append(1))
    shell._on_running(True)
    shell.clear_dead_processes()
    assert ran == [1]
    with pytest.raises(Busy):
        shell.start(lambda launch, loc: None, "another job")


# ---------------------------------------------------------------- job bookkeeping before clients see the end
def test_the_top_bar_is_current_when_a_job_ends_and_pages_are_told_first(shell):
    seen = []

    def job(launch, loc):
        seen.append((shell.state.busy, shell.facts().busy, shell.state.job_label))
        raise SystemExit(1)

    shell.start(job, "Doing a thing...", "other")
    assert seen == [(True, True, "Doing a thing...")]
    assert shell.failed_job == "Doing a thing..." and not shell.state.busy
    order = types(shell)
    assert order.index("invalidated") < order.index("failed")  # pages read again before a client sees the end


def test_on_done_comes_through_the_background_with_the_outcome(shell):
    done = []

    def bad(launch, loc):
        raise SystemExit(1)

    shell.start(lambda launch, loc: None, "ok", "page", on_done=done.append)
    shell.start(bad, "bad", "page", on_done=done.append)
    assert done == [True, False]


# ---------------------------------------------------------------- questions over the API
def test_the_launch_flow_asks_through_a_prompt_event_and_the_answer_goes_back_by_id(shell):
    got = []
    shell.flow.ports.ask(Choose("Retry?", (), (Choice("retry", "Retry"),)), got.append)
    prompt = next(e for e in events(shell) if e.type == "prompt")
    assert prompt.data["kind"] == "choose" and prompt.data["title"] == "Retry?"
    shell.session.answer_prompt(prompt.data["prompt_id"], "retry")
    assert got == ["retry"]
    with pytest.raises(OperationError) as late:
        shell.session.answer_prompt(prompt.data["prompt_id"], "retry")
    assert late.value.code == "unknown_prompt"


def test_a_running_job_can_ask_and_waits_for_the_answer(threaded):
    words = Choose("Which?", (), (Choice("a", "A"), Choice("b", "B")))
    job = threaded.session.start(lambda ctx: {"picked": ctx.ask(words, timeout=10)}, title="asks", writes=False)
    wait_until(lambda: any(e.type == "prompt" for e in events(threaded)))
    prompt = next(e for e in events(threaded) if e.type == "prompt")
    assert prompt.job_id == job
    threaded.session.answer_prompt(prompt.data["prompt_id"], "b")
    wait_until(lambda: threaded.jobs.get(job).state != "running")
    assert threaded.jobs.get(job).result == {"picked": "b"}


def test_a_cancelled_job_stops_waiting_for_its_answer(threaded):
    job = threaded.session.start(lambda ctx: ctx.ask(Choose("Which?", (), ())), title="asks", writes=False)
    wait_until(lambda: threaded.jobs.prompts.pending() == 1)
    threaded.jobs.cancel(job)
    wait_until(lambda: threaded.jobs.get(job).state != "running")
    assert threaded.jobs.get(job).result == "cancel" and threaded.jobs.prompts.pending() == 0


# ---------------------------------------------------------------- operations
def test_game_and_mode_operations_go_through_the_session(shell):
    assert shell.session.run("shell.set_mode", {"mode": "offline"}).mode == "offline"
    assert shell.session.snapshot("shell").pill.mode == "offline"
    assert shell.session.run("shell.set_game", {"key": "eldenring"}).game == "eldenring"
    assert shell.session.run("shell.pick_profile", {"index": 5}).changed is False
    with pytest.raises(OperationError) as e:
        shell.session.run("shell.add_profile", {"path": "nowhere.txt"})
    assert e.value.code == "not_a_profile"


def test_a_game_cannot_be_switched_while_a_job_runs(shell):
    shell.state.busy = True
    with pytest.raises(Busy):
        shell.session.run("shell.set_game", {"key": "nightreign"})
    assert shell.state.game.key == "eldenring"


def test_launch_says_why_it_cannot_start(shell):
    shell._on_running(True)
    with pytest.raises(OperationError) as e:
        shell.session.run("shell.launch", {})
    assert e.value.code == "cannot_launch" and "running" in e.value.message


def test_support_logs_are_zipped_into_the_folder_asked(shell, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    run_logging.setup_logging(console=False)
    got = shell.session.run("shell.save_logs", {"folder": str(out)})
    run_logging.shutdown()
    assert got.path.endswith(".zip") and [p.suffix for p in out.iterdir()] == [".zip"]


def test_a_session_without_a_shell_says_so():
    with pytest.raises(OperationError) as e:
        Session(JobManager()).snapshot("shell")
    assert e.value.code == "no_shell"


# ---------------------------------------------------------------- start-up has one owner
def test_startup_runs_the_session_steps_once_and_tells_what_they_put_right(shell, monkeypatch):
    calls = []
    monkeypatch.setattr(startup.run_health, "recover_all", lambda: calls.append("runs") or ["last run reported"])
    monkeypatch.setattr(startup.saves_page, "adopt_legacy_folders", lambda *a, **k: calls.append("adopt") or [])
    monkeypatch.setattr(shell.watch, "start", lambda: calls.append("watch"))
    shell.startup()
    assert calls.count("runs") == 1 and "watch" in calls
    assert [e.data["text"] for e in events(shell) if e.type == "notice"] == ["last run reported"]


def test_reading_recovers_nothing(shell, monkeypatch):
    from bayle.services import mods as mod_service

    monkeypatch.setattr(mod_service, "recover_interrupted", lambda *a, **k: pytest.fail("a read recovered"))
    shell.session.snapshot("shell")
    shell.session.snapshot("activity")
