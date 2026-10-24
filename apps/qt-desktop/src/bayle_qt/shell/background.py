"""Where the shell's small pieces of work run. A client supplies its own (the window's Jobs hands results back on the UI
thread); ThreadBackground is the plain one: a daemon thread, callbacks on that thread. No Qt."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Protocol


class Background(Protocol):
    def start(
        self,
        work: Callable[[Callable[[Any], None]], Any],
        on_result: Callable[[Any], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        name: str | None = None,
    ) -> Any:
        """Run work(progress) off the caller's thread; progress(value) goes to on_progress, the return value to
        on_result."""
        ...


class ThreadBackground:
    def start(
        self,
        work: Callable[[Callable[[Any], None]], Any],
        on_result: Callable[[Any], None] | None = None,
        on_progress: Callable[[Any], None] | None = None,
        name: str | None = None,
    ) -> threading.Thread:
        def run() -> None:
            got = work(on_progress or (lambda _value: None))
            if on_result is not None:
                on_result(got)

        thread = threading.Thread(target=run, name=name or "shell-work", daemon=True)
        thread.start()
        return thread
