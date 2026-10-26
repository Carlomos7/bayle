"""One page read, off the UI thread: the page keeps showing what it has, a worker builds the new facts, and they are
applied on the UI thread when they land.

  request()  several calls in one event-loop turn make one build (host.defer = QTimer.singleShot(0); a host without
             defer, such as a test's, builds at once, so refresh() still finishes before it returns)
  generation every request counts; a build that lands after a newer request is dropped and the read starts again
  key        optional cheap fingerprint (file mtimes and sizes) taken on the worker; a soft request (force=False, the
             host's read after a job) with the same key as the last applied read builds nothing. A forced request
             (the page's own refresh) always builds."""

from __future__ import annotations

import inspect
import logging
import os
import weakref
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from bayle.adapters.system.threads import as_worker

log = logging.getLogger(__name__)
_SAME = object()
_FAILED = object()


def stat_key(paths: Iterable[Path | str | None], children: bool = False) -> tuple:
    """(mtime_ns, size) of each path (None when missing); children=True adds those of each folder's direct entries."""
    out: list[Any] = []
    for p in paths:
        if p is None:
            continue
        try:
            st = os.stat(p)
            out.append((str(p), st.st_mtime_ns, st.st_size))
            if children and os.path.isdir(p):
                with os.scandir(p) as it:
                    out.extend(sorted((e.name, s.st_mtime_ns, s.st_size) for e in it for s in (e.stat(),)))
        except OSError:
            out.append((str(p), None, None))
    return tuple(out)


def _held(fn: Callable[..., Any]) -> Callable[..., Any]:
    """fn held without keeping its object alive: an adapter owns its Refresher, and a Refresher holding the adapter's
    bound methods strongly is a reference cycle that frees the adapter (a QObject, with its children and timers) at
    some later garbage collection, on whichever thread runs it, instead of when the page goes. A dead owner: None."""
    if not inspect.ismethod(fn):
        return fn
    ref = weakref.WeakMethod(fn)

    def call(*args: Any) -> Any:
        method = ref()
        return method(*args) if method is not None else None

    return call


class Refresher:
    def __init__(
        self,
        host: Any,
        snapshot: Callable[[], Any],
        build: Callable[[Any], Any],
        apply: Callable[[Any], None],
        key: Callable[[Any], Any] | None = None,
        busy: Callable[[bool], None] | None = None,
    ):
        """snapshot() runs on the UI thread when the read starts; build(snap) and key(snap) run on the worker."""
        self._host, self._key = host, _held(key) if key else None
        self._snapshot, self._build, self._apply, self._busy = (
            _held(snapshot),
            _held(build),
            _held(apply),
            _held(busy) if busy else None,
        )
        self.generation = 0
        self.running = False
        self._queued = False
        self._force = False
        self._last: Any = None

    def request(self, force: bool = True) -> None:
        self.generation += 1
        self._force = self._force or force
        if self.running or self._queued:  # the build in flight lands stale and the read starts again
            return
        self._queued = True
        defer = getattr(self._host, "defer", None)
        if defer is None:
            self._start()
        else:
            defer(self._start)

    def _start(self) -> None:
        self._queued = False
        self.running = True
        if self._busy is not None:
            self._busy(True)
        gen = self.generation
        snap = self._snapshot()
        skip_ok, self._force = not self._force, False

        def work():
            try:
                k = self._key(snap) if self._key is not None else None
                if skip_ok and k is not None and k == self._last:
                    return _SAME, k
                with as_worker():  # a test host runs this inline
                    return self._build(snap), k
            except Exception:  # the page keeps what it shows
                log.exception("a page read failed")
                return _FAILED, None

        self._host.run_in_background(work, lambda got: self._land(gen, got))

    def _land(self, gen: int, got: tuple) -> None:
        self.running = False
        if self._busy is not None:
            self._busy(False)
        if gen != self.generation:
            self._queued = True
            self._start()
            return
        result, k = got
        if result is _SAME or result is _FAILED:
            return
        self._last = k
        self._apply(result)
