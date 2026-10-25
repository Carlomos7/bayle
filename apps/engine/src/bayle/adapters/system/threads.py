"""The boundary between the UI thread and disk work: I/O service entry points that pages use call
assert_not_ui_thread() first. Off by default (release builds pay nothing); tests/ui turns it on, so a page that reads
the disk on the UI thread fails a test. A test host that runs background work inline wraps it in as_worker()."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_ui_thread: int | None = None
_local = threading.local()


class UiThreadIO(AssertionError):
    pass


def enable(ui_thread: int | None = None) -> None:
    """Start refusing I/O on ui_thread (default: the calling thread)."""
    global _ui_thread
    _ui_thread = threading.get_ident() if ui_thread is None else ui_thread


def disable() -> None:
    global _ui_thread
    _ui_thread = None


@contextmanager
def as_worker() -> Iterator[None]:
    """Work that a test runs inline on the UI thread stands in for a worker thread."""
    depth = getattr(_local, "depth", 0)
    _local.depth = depth + 1
    try:
        yield
    finally:
        _local.depth = depth


def assert_not_ui_thread(what: str = "") -> None:
    if _ui_thread is not None and threading.get_ident() == _ui_thread and not getattr(_local, "depth", 0):
        raise UiThreadIO(
            f"disk work on the UI thread: {what or 'a service entry point'} (run it with host.run_in_background)"
        )
