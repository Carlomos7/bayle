"""The Launch flow's safety rules (S9-Shell tests T3, T4, T5): the game never starts without its backup unasked, never
goes online with changed game data unasked, and never starts while a job or the game runs or Launch is blocked. The
flow runs over fakes: no Qt, no game, no files."""

from pathlib import Path
from types import SimpleNamespace

from bayle.config.settings import LauncherSettings
from bayle.game import catalog
from bayle.services import play as core
from bayle.ui.launcher import launch
from bayle.ui.launcher.launch import Ask, LaunchFlow, Services
from bayle.views.topbar import OFFLINE, PROFILE, VANILLA


class LaunchProfile:
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
    def __init__(self, launch_profile="default", game=catalog.ELDEN_RING, busy=False, running=False, exe=True):
        self.busy, self.game_running, self.game = busy, running, game
        self.launch_profile = LaunchProfile() if launch_profile == "default" else launch_profile
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
        State(launch_profile=None),  # no profile
        State(
            launch_profile=LaunchProfile([core.Problem("unfinished", detail="this setup was not finished")])
        ),  # an incomplete managed setup
    )
    for state in blocked:
        f, ports, calls = flow(state=state)
        assert f.start(PROFILE) is False
        assert calls.started == [] and ports.asked == [] and ports.toasts


# T7: Vanilla
def test_vanilla_starts_through_steam_without_me3_a_profile_or_the_save_repair(monkeypatch):
    from bayle.game.locate import Locations as RealLocations

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


# Merged mods that are out of date (ported from the retired Widgets window's tests)
class RebuildPorts(Ports):
    """Like Ports, but a job that raises SystemExit (a failed rebuild) reports failure to on_done."""

    def __init__(self, answers=(), fail=False):
        super().__init__(answers)
        self.fail = fail

    def run_job(self, job, label, kind, on_done=None):
        self.jobs.append((label, kind))
        ok = True
        try:
            job(None, Locations())
        except SystemExit:
            ok = False
        if kind == "update" and self.fail:
            ok = False
        if on_done:
            on_done(ok)


def stale_flow(answers=(), auto=True, blocked="", fail=False, tool_ok=True):
    from bayle.mods import rebuild as mod_merge

    ports, calls = RebuildPorts(answers, fail), Calls()
    services = calls.services()
    rebuilt: list[int] = []
    stale = {"reasons": ["a mod changed"], "blocked": blocked}

    def update_before_play(prof, log, loc):
        rebuilt.append(1)
        if fail:
            raise mod_merge.MergeError("refused")
        stale.clear()  # now current
        return None

    services.play_options = lambda settings=None: {"play_backup_before": False, "play_update_merge": auto}
    services.play_check = lambda prof, loc: dict(stale) or None
    services.update_before_play = update_before_play
    services.last_run = lambda prof: {"message": "refused"}
    services.tool_state = lambda prof, loc: SimpleNamespace(
        tool=None if tool_ok else SimpleNamespace(label="the tool"), problem="", allowed=tool_ok
    )
    return LaunchFlow(State(), ports, services), ports, calls, rebuilt


def test_launch_updates_the_merged_mods_first_then_starts():
    f, ports, calls, rebuilt = stale_flow()
    f.start(PROFILE)
    assert rebuilt == [1] and [k for _, k in ports.jobs] == ["update", "launch"]
    assert [name for name, _ in calls.started] == ["play"]


def test_stop_after_the_rebuild_lets_it_finish_but_does_not_start():
    f, ports, calls, rebuilt = stale_flow()

    def run_job(job, label, kind, on_done=None):
        f.stop_after_rebuild()
        RebuildPorts.run_job(ports, job, label, kind, on_done)

    ports.run_job = run_job  # type: ignore[method-assign]
    f.start(PROFILE)
    assert rebuilt == [1] and calls.started == []


def test_with_automatic_rebuilds_off_launch_asks_and_never_starts_silently():
    f, ports, calls, rebuilt = stale_flow([launch.CANCEL], auto=False)
    f.start(PROFILE)
    assert [c.key for c in ports.asked[0].choices] == [launch.REBUILD, launch.PLAY_ANYWAY, launch.CANCEL]
    assert rebuilt == [] and calls.started == []
    f, ports, calls, rebuilt = stale_flow([launch.PLAY_ANYWAY], auto=False)
    f.start(PROFILE)
    assert rebuilt == [] and [name for name, _ in calls.started] == ["play"]  # this once, with the previous result


def test_launch_asks_when_the_merged_mods_cannot_be_rebuilt_or_the_tool_is_not_allowed():
    for kwargs in ({"blocked": "the last package is missing"}, {"tool_ok": False}):
        f, ports, calls, rebuilt = stale_flow([launch.CANCEL], **kwargs)
        f.start(PROFILE)
        assert ports.asked[0].title == "Your merged mods are out of date"
        assert launch.PLAY_ANYWAY in [c.key for c in ports.asked[0].choices]
        assert rebuilt == [] and calls.started == []


def test_a_failed_update_offers_play_anyway_and_is_not_retried_silently():
    f, ports, calls, rebuilt = stale_flow([launch.PLAY_ANYWAY, launch.CANCEL], fail=True)
    f.start(PROFILE)
    assert ports.asked[0].title == "The merged mods could not be updated"
    assert [name for name, _ in calls.started] == ["play"]
    f.start(PROFILE)  # same inputs: it asks again instead of rebuilding or starting
    assert rebuilt == [1] and len(calls.started) == 1 and ports.asked[1].title == "Your merged mods are out of date"


def test_launch_reads_the_profile_checks_fresh_each_time():
    launch_profile = LaunchProfile()
    state = State(launch_profile=launch_profile)
    f, ports, calls = flow(state=state)
    f.start(PROFILE)
    assert calls.started  # a clean setup starts
    calls.started.clear()
    launch_profile._problems = [
        core.Problem("profile_missing", path="gone.me3")
    ]  # changed on disk since: the next Launch must see it
    assert f.start(PROFILE) is False and calls.started == []
