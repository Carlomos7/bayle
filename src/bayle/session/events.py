"""The event bus: one ordered stream of structured events for every client (the window, the HTTP layer's SSE), no Qt
and no event loop. publish() may be called from any thread; each subscriber reads its own bounded queue.

Guarantees: seq is strictly increasing and gap-free in the ring buffer; a subscriber that starts at ``since`` gets the
buffered events after it, then live ones, with none missed or doubled; progress and log events are dropped (oldest
first) when a subscriber falls behind, terminal events and prompts never are; a subscriber asking for a seq the ring
no longer holds first gets a ``resync`` event (refetch your state, then continue).
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

TERMINAL = frozenset({"finished", "failed", "cancelled"})
DROPPABLE = ("progress", "log")  # dropped in this order when a subscriber's queue is full


@dataclass(frozen=True)
class Event:
    seq: int
    type: str  # started|progress|log|prompt|finished|failed|cancelled, or a push (game.state, invalidated, resync...)
    job_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class Subscription:
    """One client's queue. get() blocks (timeout seconds, None = forever) and returns None on timeout or once closed."""

    def __init__(self, bus: EventBus, maxsize: int, notify: Callable[[], None] | None):
        self._bus, self._max, self._notify = bus, maxsize, notify
        self._items: deque[Event] = deque()
        self._cond = threading.Condition()
        self.closed = False

    def _push(self, event: Event) -> None:
        with self._cond:
            if self.closed:
                return
            self._items.append(event)
            for kind in DROPPABLE:  # shortcut: protected events are never dropped, so a stuck client's queue can grow
                while len(self._items) > self._max:
                    for i, e in enumerate(self._items):
                        if e.type == kind:
                            del self._items[i]
                            break
                    else:
                        break
            self._cond.notify_all()
        if self._notify is not None:
            self._notify()  # e.g. loop.call_soon_threadsafe(...) for an asyncio reader

    def get(self, timeout: float | None = 0) -> Event | None:
        with self._cond:
            if not self._items and not self.closed and timeout != 0:
                self._cond.wait_for(lambda: self._items or self.closed, timeout)
            return self._items.popleft() if self._items else None

    def __len__(self) -> int:
        return len(self._items)

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()
        self._bus._drop(self)


class EventBus:
    def __init__(self, buffer: int = 1000):
        self._lock = threading.Lock()
        self._ring: deque[Event] = deque(maxlen=buffer)
        self._seq = 0
        self._subs: set[Subscription] = set()

    @property
    def seq(self) -> int:
        return self._seq

    def publish(self, type: str, data: dict[str, Any] | None = None, job_id: str | None = None) -> Event:
        with self._lock:
            self._seq += 1
            event = Event(self._seq, type, job_id, dict(data or {}))
            self._ring.append(event)
            for sub in list(self._subs):
                sub._push(event)
        return event

    def subscribe(
        self, since: int | None = None, maxsize: int = 256, notify: Callable[[], None] | None = None
    ) -> Subscription:
        """since None: live events only. since N: the buffered events with seq > N first (Last-Event-ID)."""
        sub = Subscription(self, maxsize, notify)
        with self._lock:
            if since is not None:
                oldest = self._ring[0].seq if self._ring else self._seq + 1
                if since < oldest - 1 or since > self._seq:  # events lost, or a client from before a restart
                    sub._push(
                        Event(oldest - 1, "resync", None, {"requested": since, "oldest": oldest, "seq": self._seq})
                    )
                for e in self._ring:
                    if e.seq > since:
                        sub._push(e)
            self._subs.add(sub)
        return sub

    def _drop(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)
