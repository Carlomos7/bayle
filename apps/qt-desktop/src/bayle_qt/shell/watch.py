"""The game watch (technical specification §8.10: "the game watch drives the running state everywhere"): every few
seconds, on a worker thread, whether the game runs, Steam's state and the leftover game processes; each answer is
handed to the shell (on the background's thread). "Running" is decided by threads, not memory (platform/paths.py): a starting
game is small, a dead shell has none.

Steam signed out: Steam running but not signed in for SIGN_IN_WAIT seconds is said (earlier it is just starting up)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from bayle.services.play import steam_state
from bayle.services.saves import dead_shells_count

from bayle_qt.shell.background import Background

INTERVAL = 5  # seconds between looks
SIGN_IN_WAIT = 20  # seconds Steam may be running and not signed in before it is called a problem


class GameWatch:
    def __init__(
        self,
        jobs: Background,
        locations: Callable[[], object],
        on_running: Callable[[bool], None],
        on_steam: Callable[[bool], None],
        on_shells: Callable[[int], None],
        interval: float = INTERVAL,
    ):
        self._jobs, self._locations, self._interval = jobs, locations, interval
        self._on_running, self._on_steam, self._on_shells = on_running, on_steam, on_shells
        self._bad_since: float | None = None
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def start(self) -> None:
        def work(report):
            while True:
                try:
                    loc = self._locations()
                    report(("running", loc.game_running()))  # type: ignore[attr-defined]
                    report(("steam", steam_state()))
                    report(("shells", dead_shells_count(loc=loc)))  # type: ignore[arg-type]
                except Exception:
                    pass  # a look that failed is just missed; the next one tries again
                if self._stop.wait(self._interval):
                    return

        self._jobs.start(work, on_progress=self._seen, name="game-watch")

    def look_now(self) -> None:
        """One look at once (a game switch: the other game may be running)."""
        loc = self._locations()
        self._jobs.start(lambda _progress: loc.game_running(), on_result=self._on_running)  # type: ignore[attr-defined]

    def _seen(self, seen) -> None:
        what, value = seen
        if what == "running":
            self._on_running(value)
        elif what == "steam":
            self._on_steam(self.steam_problem(*value))
        else:
            self._on_shells(value)

    def steam_problem(self, running: bool, signed_in: bool, now: float | None = None) -> bool:
        """Steam runs but has not been signed in for SIGN_IN_WAIT seconds."""
        now = time.time() if now is None else now
        if not (running and not signed_in):
            self._bad_since = None
            return False
        if self._bad_since is None:
            self._bad_since = now
        return now - self._bad_since >= SIGN_IN_WAIT
