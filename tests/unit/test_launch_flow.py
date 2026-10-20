"""The Launch flow's safety rules (S9-Shell tests T3, T4, T5): the game never starts without its backup unasked, never
goes online with changed game data unasked, and never starts while a job or the game runs or Launch is blocked. The
flow runs over fakes: no Qt, no game, no files."""

from pathlib import Path
from types import SimpleNamespace

from roundtable_souls.config.settings import LauncherSettings
from roundtable_souls.game import catalog
from roundtable_souls.services import play as core
from roundtable_souls.ui.launcher import launch
from roundtable_souls.ui.launcher.launch import Ask, LaunchFlow, Services
from roundtable_souls.ui.launcher.topbar import OFFLINE, PROFILE, VANILLA


class Setup:
    profile = "main.me3"
    source = "main.me3"
    kind = "me3"
    game = catalog.ELDEN_RING

    def __init__(self, problems=()):
        self._problems = list(problems)

    def problems(self):
        return self._problems

    def locations(self):
        return Locations()


class Locations:
    game = catalog.ELDEN_RING

    def game_dir(self):
        return Path("game")


class State:
    def __init__(self, setup="default", game=catalog.ELDEN_RING, busy=False, running=False, exe=True):
        self.busy, self.game_running, self.game = busy, running, game
        self.setup = Setup() if setup == "default" else setup
        self.settings = LauncherSettings(offline_skip_confirm=True)
        self.locations = SimpleNamespace(game_dir=lambda: Path("game") if exe else None)


class Ports:
    """Records what the flow did; answers every fork with the next scripted answer (None: the test fails)."""

    def __init__(self, answers=()):
        self.answers = list(answers)
        self.asked: list[Ask] = []
        self.jobs: list[tuple[str, str]] = []
        self.toasts: list[str] = []

    def ask(self, ask, on_answer):
        self.asked.append(ask)
        on_answer(self.answers.pop(0))

    def toast(self, text, error=False):
        self.toasts.append(text)

    def progress(self, label):
        pass

    def background(self, work, on_result):
        on_result(work())

    def run_job(self, job, label, kind, on_done=None):
        self.jobs.append((label, kind))
        job(None, Locations())
        if on_done:
            on_done(True)

    def save_pending(self):
        return None

    def show_activity(self):
        pass


class Calls:
    """The services the flow calls, recorded."""

    def __init__(self, backup_fails=0, risk=None, backup_on=True):
        self.backup_fails, self.risk, self.backup_on = backup_fails, risk, backup_on
        self.backups = 0
        self.risk_checks = 0
        self.started: list[tuple[str, str]] = []  # (service, backup mode)

    def services(self):
        def backup(loc, required=False):
            self.backups += 1
            if self.backups <= self.backup_fails:
                raise core.BackupBeforePlayFailed([(Path("ER0000.sl2"), "locked")])

        def online_risk(profile, loc):
            self.risk_checks += 1
            return self.risk

        return Services(
            play_options=lambda settings=None: {"play_backup_before": self.backup_on, "play_update_merge": True},
            backup=backup,
            play_check=lambda prof, loc: None,
            online_risk=online_risk,
            job_play=lambda s, loc, backup: self.started.append(("play", backup)),
            job_play_offline=lambda s, loc, **kw: self.started.append(("offline", kw["backup"])),
            job_play_vanilla=lambda s, loc, backup: self.started.append(("vanilla", backup)),
        )


def flow(state=None, ports=None, calls=None):
    state, ports, calls = state or State(), ports or Ports(), calls or Calls()
    return LaunchFlow(state, ports, calls.services()), ports, calls  # type: ignore[arg-type]


# T3: backup
def test_a_failed_backup_starts_nothing_until_the_player_chooses():
    f, ports, calls = flow(ports=Ports([launch.CANCEL]), calls=Calls(backup_fails=9))
    f.start(PROFILE)
    assert [c.key for c in ports.asked[0].choices] == [launch.RETRY, launch.WITHOUT_BACKUP, launch.CANCEL]
    assert calls.started == [] and ports.jobs == [] and not f.active


def test_retry_runs_the_backup_again_and_then_starts_with_the_backup_done():
    f, ports, calls = flow(ports=Ports([launch.RETRY]), calls=Calls(backup_fails=1))
    f.start(PROFILE)
    assert calls.backups == 2
    assert calls.started == [("play", core.BACKUP_SKIP)]


def test_launch_without_backup_starts_the_game_and_says_so_in_the_log(monkeypatch):
    logged = []
    monkeypatch.setattr(launch.run_logging, "log", logged.append)
    f, ports, calls = flow(ports=Ports([launch.WITHOUT_BACKUP]), calls=Calls(backup_fails=9))
    f.start(PROFILE)
    assert calls.started == [("play", core.BACKUP_SKIP)]
    assert any("without a backup" in line for line in logged)


# T4: online
def test_changed_game_data_online_asks_before_any_launch():
    risk = SimpleNamespace(source="Some Pack")
    f, ports, calls = flow(ports=Ports([launch.CANCEL]), calls=Calls(risk=risk))
    f.start(PROFILE)
    assert len(ports.asked) == 1 and "fingerprint" in ports.asked[0].lines[0]
    assert "ban" not in " ".join(ports.asked[0].lines).lower()
    assert calls.started == []


def test_launch_offline_instead_starts_the_offline_job_not_the_online_one():
    f, ports, calls = flow(ports=Ports([launch.OFFLINE_INSTEAD]), calls=Calls(risk=SimpleNamespace(source="P")))
    f.start(PROFILE)
    assert [name for name, _ in calls.started] == ["offline"]


def test_offline_and_vanilla_never_run_the_online_check():
    for mode in (OFFLINE, VANILLA):
        f, ports, calls = flow(calls=Calls(risk=SimpleNamespace(source="P")))
        f.start(mode)
        assert calls.risk_checks == 0 and len(calls.started) == 1 and ports.asked == []


# T5: gates
def test_a_running_game_or_a_busy_job_refuses_launch():
    for state in (State(running=True), State(busy=True)):
        f, ports, calls = flow(state=state)
        assert f.start(PROFILE) is False
        assert calls.started == [] and ports.toasts


def test_a_blocked_state_starts_nothing():
    blocked = (
        State(game=catalog.SEKIRO),  # not supported yet
        State(exe=False),  # the game is not installed
        State(setup=None),  # no profile
        State(setup=Setup(["this setup was not finished"])),  # an incomplete managed setup
    )
    for state in blocked:
        f, ports, calls = flow(state=state)
        assert f.start(PROFILE) is False
        assert calls.started == [] and ports.asked == [] and ports.toasts


# T7: Vanilla
def test_vanilla_starts_through_steam_without_me3_a_profile_or_the_save_repair(monkeypatch):
    from roundtable_souls.game.locate import Locations as RealLocations

    opened = []
    forbidden = lambda *a, **k: (_ for _ in ()).throw(AssertionError("Vanilla must not call this"))  # noqa: E731
    monkeypatch.setattr(
        core,
        "play_options",
        lambda settings=None: {"play_backup_before": False, "play_clear_before": True, "play_clear_after": True},
    )
    monkeypatch.setattr(core.run_logging, "start_log", lambda *a, **k: None)
    monkeypatch.setattr(core.run_logging, "log", lambda *a, **k: None)
    monkeypatch.setattr(core.me3_session, "ensure_steam", lambda timeout: None)
    monkeypatch.setattr(core.me3_session, "clear_dead_shells", lambda exe, when: None)
    monkeypatch.setattr(core.me3_session, "wait_for_game", lambda exe, appear_timeout, quiet=False: True)
    monkeypatch.setattr(core.desktop, "open_path", opened.append)
    for name in ("launch",):
        monkeypatch.setattr(core.me3_session, name, forbidden)
    monkeypatch.setattr(core.save_repair, "repair_all", forbidden)
    monkeypatch.setattr(core, "offline_profile_for", forbidden)
    monkeypatch.setattr(core, "_after_play", forbidden)
    core.job_play_vanilla(None, RealLocations(catalog.ELDEN_RING), backup=core.BACKUP_SKIP)
    assert opened == ["steam://rungameid/1245620"]
