"""What an import holds between its steps: the unpacked skeleton of a zip someone sent, or the staging folder of a
download that ships a profile. Each is a resource with an id; it is let go (its folders deleted) by discard() or,
when nobody touches it for ttl seconds, by the next call that sweeps. No Qt: a client keeps only the id."""

from __future__ import annotations

import itertools
import shutil
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bayle.errors import OperationError

if TYPE_CHECKING:
    from bayle.modules.mods import profile_transfer as pt

DEFAULT_TTL = 3600.0  # seconds a resource waits untouched


@dataclass
class Resource:
    id: str
    incoming: pt.Incoming | None = None  # a share list or a full export: read, previewed, applied
    unpacked: Path | None = None  # a download's unpacked folder (a bundled profile)
    staging: Path | None = None  # the folder to delete when the resource goes
    names: list[str] = field(default_factory=list)  # the .me3 paths inside unpacked
    preview: Any = None  # the last preview made from it (pt.Preview, or the bundled import's)
    serial: int = 0  # how many previews were made from it
    touched: float = 0.0

    @property
    def bundled(self) -> bool:
        return self.incoming is None


class TransferResources:
    def __init__(self, clock: Callable[[], float] = time.monotonic, ttl: float = DEFAULT_TTL):
        self._clock, self._ttl = clock, ttl
        self._lock = threading.Lock()
        self._items: dict[str, Resource] = {}
        self._ids = itertools.count(1)

    def add(self, **fields: Any) -> Resource:
        with self._lock:
            expired = self._expired()
            res = Resource(f"t{next(self._ids)}", touched=self._clock(), **fields)
            self._items[res.id] = res
        for old in expired:
            self._release(old)
        return res

    def get(self, resource_id: str) -> Resource:
        with self._lock:
            expired = self._expired()
            res = self._items.get(resource_id)
            if res is not None:
                res.touched = self._clock()
        for old in expired:
            self._release(old)
        if res is None:
            raise OperationError("not_found", "That file is no longer open. Open it again.", {"resource": resource_id})
        return res

    def discard(self, resource_id: str) -> bool:
        """Let go of a resource and delete what it unpacked. False when it was already gone."""
        with self._lock:
            res = self._items.pop(resource_id, None)
        if res is not None:
            self._release(res)
        return res is not None

    def open_ids(self) -> list[str]:
        with self._lock:
            return list(self._items)

    def _expired(self) -> list[Resource]:  # caller holds the lock
        now = self._clock()
        gone = [r for r in self._items.values() if now - r.touched >= self._ttl]
        for r in gone:
            del self._items[r.id]
        return gone

    @staticmethod
    def _release(res: Resource) -> None:
        if res.incoming is not None:
            from bayle.modules.mods import profile_transfer as pt  # not at the top: pt builds a TransferResources

            pt.discard(res.incoming)
        if res.staging is not None:
            shutil.rmtree(res.staging, ignore_errors=True)
