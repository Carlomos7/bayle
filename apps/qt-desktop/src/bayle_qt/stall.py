"""UI-thread stall watch: how long one turn of the UI thread's event loop runs without returning to wait for events.
Measured with the event dispatcher's awake / aboutToBlock signals (time between test code spins does not count). A
monitor QThread samples the UI thread's Python stack while a turn is over the threshold, so a stall comes with the
code that caused it."""

from __future__ import annotations

import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterable
from pathlib import Path

from PySide6.QtCore import QAbstractEventDispatcher, QThread

TARGET_MS = 50  # what real hardware should keep to (one 60 Hz frame is 16 ms; 50 ms is felt as a stutter)
TEST_MS = 250  # the failing threshold for offscreen CI (software rendering, shared runners)
LOG_MS = 200  # the app logs stalls longer than this, at most once a minute


class StallWatch(QThread):
    """on_stall(ms, stack_text) is called on the UI thread when a turn ends that ran longer than threshold_ms."""

    def __init__(self, threshold_ms: float, on_stall: Callable[[float, str], None], only_in: Iterable[str | Path] = ()):
        """only_in: report a stall only when the code running at the sample is in a file inside one of these folders (a
        test's own steps between event-loop spins look like stalls and are not the app's). Folders, not a name to look
        for in the path: the checkout itself can carry the package's name (CI checks out into ...\\bayle\\bayle\\)."""
        self._only_in = tuple(Path(p).resolve() for p in only_in)
        super().__init__()
        self.threshold = threshold_ms / 1000
        self._on_stall = on_stall
        self._ui = threading.get_ident()
        self._since: float | None = None
        self._stack = ""
        self._stop_flag = threading.Event()
        self._dispatcher = QAbstractEventDispatcher.instance()
        if self._dispatcher is not None:
            self._dispatcher.awake.connect(self._awake)
            self._dispatcher.aboutToBlock.connect(self._blocking)

    def begin(self) -> None:
        self._since = time.perf_counter()
        self.start()

    def end(self) -> None:
        self._stop_flag.set()
        self.wait(1000)
        if self._dispatcher is not None:
            self._dispatcher.awake.disconnect(self._awake)
            self._dispatcher.aboutToBlock.disconnect(self._blocking)

    def _awake(self) -> None:
        self._turn_over(time.perf_counter())  # awake again with no wait between: the last stretch was one turn

    def _blocking(self) -> None:
        self._turn_over(None)

    def _turn_over(self, next_start: float | None) -> None:
        since, stack = self._since, self._stack
        now = time.perf_counter()
        self._since, self._stack = next_start, ""
        if since is not None and now - since > self.threshold and self._counts(stack):
            self._on_stall((now - since) * 1000, stack)

    def _counts(self, stack: str) -> bool:
        if not self._only_in:
            return True
        files = [ln for ln in stack.splitlines() if ln.lstrip().startswith('File "')]
        if not files:
            return False
        innermost = Path(files[-1].split('"')[1]).resolve()
        return any(innermost.is_relative_to(folder) for folder in self._only_in)

    def run(self) -> None:  # the monitor: takes the stack once a turn has run past the threshold
        step = min(0.025, self.threshold / 4)
        while not self._stop_flag.wait(step):
            since = self._since
            if since is not None and not self._stack and time.perf_counter() - since > self.threshold:
                frame = sys._current_frames().get(self._ui)
                if frame is not None:
                    self._stack = "".join(traceback.format_stack(frame)[-12:])


def log_stalls(log, threshold_ms: float = LOG_MS, every: float = 60.0) -> StallWatch:
    """Watch the running app: stalls over threshold_ms go to the launcher log, at most one per `every` seconds."""
    last = [-every]

    def on_stall(ms: float, stack: str) -> None:
        now = time.monotonic()
        if now - last[0] >= every:
            last[0] = now
            log.warning("UI thread blocked for %d ms\n%s", ms, stack)

    watch = StallWatch(threshold_ms, on_stall)
    watch.begin()
    return watch
