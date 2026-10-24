"""Helpers for the tests: Elden Ring's locations on this PC (er()), and for the integration tests, which need a real
Seamless Co-op save, a copy of one.

The save comes from ROUNDTABLE_TEST_SAVE when set, otherwise from the first ER0000.co2 under %APPDATA%\\EldenRing.
Tests copy it into a temp folder and never write the original. Without a save the tests skip.
"""

import os
import shutil
from pathlib import Path

import pytest

from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.saves.analyze import GameItems
from bayle.services.activity import ActivityService
from bayle.work.events import EventBus
from bayle.work.jobs import JobManager


def repo_root() -> Path:
    """The repository root (where pyproject.toml, scripts/ and .github/ live), however deep the calling test is."""
    return Path(__file__).resolve().parent.parent


def er() -> Locations:
    """Elden Ring with nothing set under Settings > Locations: what code that is handed a game's locations gets."""
    return Locations(catalog.ELDEN_RING)


def er_items() -> GameItems:
    """What a save is checked against with er(): the installed game's items (none when it is not installed)."""
    return GameItems.for_locations(er())


def live_save() -> Path | None:
    """A real co-op save to copy, only when ROUNDTABLE_TEST_SAVE names one: tests never go looking for the player's
    own saves (owner, 2026-10-23), so without it these tests skip."""
    override = os.environ.get("ROUNDTABLE_TEST_SAVE")
    if not override:
        return None
    p = Path(override)
    return p if p.is_file() else None


def copy_live_save(tmp_path: Path) -> Path:
    src = live_save()
    if src is None:
        pytest.skip("no Seamless Co-op save on this PC (set ROUNDTABLE_TEST_SAVE to use one)")
    tmp_path.mkdir(parents=True, exist_ok=True)
    copy = tmp_path / "ER0000.co2"
    shutil.copy2(src, copy)
    return copy


class FakeActivityFacts(ActivityService):
    """services.activity.ActivityService over plain data: no jobs index, log files or trash. Its rules (check_undo,
    undo) are the real ones; jobs: the JobManager they gate on (default: one running jobs inline)."""

    def __init__(self, jobs=(), available=bool, logs=None, in_trash=lambda p: False, files=None, manager=None):
        super().__init__(manager or JobManager(EventBus(), spawn=lambda run, name=None: run()), None, er)
        self._jobs_list, self._available, self._logs, self._in_trash, self._files = (
            list(jobs),
            available,
            logs or {},
            in_trash,
            files or {},
        )
        self._marked = 0.0

    def jobs(self):
        return list(self._jobs_list)

    def undo_available(self, undo):
        return self._available(undo)

    def in_trash(self, path):
        return self._in_trash(path)

    def read_log(self, name):
        return self._logs.get(name, {"entries": [], "cut": False, "missing": True})

    def read_attachment(self, name):
        return self._logs.get(name, {"text": "", "cut": False, "missing": True})

    def log_file(self, name):
        return self._files.get(name)

    def unseen(self):
        return sum(1 for r in self._jobs_list if r.get("outcome") in ("failed", "interrupted"))

    def mark_seen(self):
        self._marked += 1
        return self._marked


MODS_PROFILE = (
    'profileVersion = "v1"\n\n[[supports]]\ngame = "eldenring"\n\n'
    "[[packages]]\nid = \"flora\"\npath = 'mod/flora'\n\n"
    '[[packages]]\nid = "cloud"\npath = \'mod/cloud\'\nload_after = [{ id = "flora", optional = false }]\n\n'
    "[[natives]]\npath = 'natives/a.dll'\n"
)


def mods_profile(root: Path, text: str = MODS_PROFILE) -> Path:
    """A small me3 profile on disk (two packages, one DLL) with its folders: what the Mods operations are run over."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / "main.me3"
    path.write_bytes(text.encode("utf-8"))  # LF whatever the platform
    for d in ("mod/flora/parts", "mod/cloud/parts", "natives"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "natives" / "a.dll").write_bytes(b"d")
    return path


def tree_state(*roots: Path) -> dict:
    """(mtime, size) of every file and folder under the roots: a read must leave it as it was."""
    return {str(p): (p.stat().st_mtime_ns, p.stat().st_size) for r in roots for p in [r, *r.rglob("*")]}


class FakeShellContext:
    """bayle.session.shell.state.Context over a temporary data folder: no database, no real
    profile or save folder; settings go to the isolated settings file. What the shell tests build a Shell on."""

    def __init__(self, data_dir: Path, spawn=None):
        from bayle.config.settings import LauncherSettings
        from bayle.services.settings import load_settings, save_settings
        from bayle.work.prompts import PlanStore

        self._load = load_settings

        (data_dir / "profiles").mkdir(exist_ok=True)
        (data_dir / "saves").mkdir(exist_ok=True)
        self.data_dir = data_dir
        self.settings = LauncherSettings(
            me3_profile_dir=str(data_dir / "profiles"), saves_dir=str(data_dir / "saves"), tips_seen=["launch", "rail"]
        )
        save_settings(me3_profile_dir=self.settings.me3_profile_dir, saves_dir=self.settings.saves_dir)
        self.game = catalog.ELDEN_RING
        self.locations = Locations.from_settings(self.settings, self.game)
        self.jobs = JobManager(EventBus(), spawn=spawn)  # spawn: how jobs get a thread (inline in most tests)
        self.plans = PlanStore()
        self.activity = None

    def startup(self, profile):
        from bayle.session.startup import recovery_steps

        return recovery_steps(lambda: self.locations, profile)

    def select_game(self, game):
        self.game = game
        self.locations = Locations.from_settings(self.settings, game)
        return self.locations

    def note_profile_saves(self, names):
        return self.locations

    def reload_settings(self):
        self.settings = self._load()
        return self.settings

    def start_imports(self):
        return None


class InlineBackground:
    """shell.background.Background that runs work at once on the caller's thread, except the named loops and checks
    (the game watch, the update and me3 checks), which would loop or ask the network: those are only recorded."""

    def __init__(self, skip=("game-watch", "launcher-update", "me3-facts")):
        self.skip, self.started = tuple(skip), []

    def start(self, work, on_result=None, on_progress=None, name=None):
        self.started.append(name)
        if name in self.skip:
            return None
        got = work(on_progress or (lambda _value: None))
        if on_result is not None:
            on_result(got)
        return None


def mods_session(locations=er, **jobs_kw):
    """A Session over inline jobs whose Mods service is the real one (what the Mods operations are run through)."""
    from bayle.services.mods_page import ModsService
    from bayle.session import Session
    from bayle.session import ops as _ops  # noqa: F401  registers the operations
    from bayle.work.prompts import PlanStore

    jobs = JobManager(EventBus(), spawn=lambda run, name=None: run(), **jobs_kw)
    return Session(jobs, plans=PlanStore(), locations=locations, services={"mods": ModsService(jobs, locations)})


def refused(session, name, params):
    """The OperationError an operation raises (the test fails when it does not)."""
    from bayle.errors import OperationError

    with pytest.raises(OperationError) as e:
        session.run(name, params)
    return e.value


class Direct:
    """A feature router's routes called without HTTP, on a real service: `run("saves.back_up", {...})` validates the
    params as the route's body would and returns the route's result (a failed validation is the invalid_params
    OperationError), `snapshot("saves", **scope)` is its GET. For tests of the engine behaviour behind the routes."""

    def __init__(self, router_module, feature: str, service, jobs: JobManager):
        self.feature, self.service, self.jobs = feature, service, jobs
        self._routes = {r.name: r.endpoint for r in router_module.router.routes}

    def _call(self, name: str, raw):
        import typing

        from pydantic import ValidationError

        from bayle.errors import OperationError

        fn = self._routes[name]
        hints = typing.get_type_hints(fn)
        hints.pop("return", None)
        rest = [t for k, t in hints.items() if k != next(iter(hints))]
        if not rest:
            return fn(self.service)
        try:
            return fn(self.service, rest[0].model_validate(raw))
        except ValidationError as e:
            errors = [{"loc": [str(p) for p in x["loc"]], "msg": x["msg"], "type": x["type"]} for x in e.errors()]
            raise OperationError(
                "invalid_params", f"The request for {name} is not valid.", {"errors": errors}
            ) from None

    def run(self, name: str, params=None):
        raw = params.model_dump() if hasattr(params, "model_dump") else (params or {})
        return self._call(name.replace(".", "_", 1), raw)

    def snapshot(self, name: str, **scope):
        return self._call(name, scope)
