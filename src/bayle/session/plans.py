"""Asking a client before a change, without a callback into a window.

PlanStore: plan/execute. A client asks for a plan (the words to show, an id), shows them, and sends the answer to
execute(plan_id, answer). A plan lives for a TTL, runs once, and is refused when what it was made from changed
(its staleness token differs). PromptBroker: the same for a running job, which asks mid-way (the Launch flow's
Ports.ask): the question goes out as a prompt event and the answer comes back by id. No Qt, no event loop.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from bayle.services.errors import OperationError
from bayle.views.common import Choose, Prompt, prompt_dict

DEFAULT_TTL = 300.0  # seconds a plan waits for its answer


class PlanError(OperationError):
    """The plan cannot be executed: unknown, used, expired or stale (the code says which)."""


@dataclass(frozen=True)
class Answer:
    """What the client says back: ok False = cancelled; option = the check box; choice = a Choose key; ticked = Pick rows."""

    ok: bool = True
    option: bool = False
    choice: str = ""
    ticked: tuple[int, ...] = ()


@dataclass(frozen=True)
class Plan:
    id: str
    words: Prompt
    expires_at: float  # on the store's clock

    def to_dict(self) -> dict:
        return {"id": self.id, "expires_at": self.expires_at, "prompt": prompt_dict(self.words)}


@dataclass(frozen=True)
class Proposal:
    """What a plan operation returns: the words to show, what to do with the answer (run returns the id of the job
    it started, or None), and an optional cheap read of what the plan was made from (see PlanStore.add)."""

    words: Prompt
    run: Callable[[Answer], Any]
    stale: Callable[[], object] | None = None


@dataclass
class _Entry:
    plan: Plan
    run: Callable[[Answer], Any]
    stale: Callable[[], object] | None
    token: object


class PlanStore:
    def __init__(self, clock: Callable[[], float] = time.monotonic, ttl: float = DEFAULT_TTL):
        self._clock, self._ttl = clock, ttl
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._ids = itertools.count(1)

    def add(self, words: Prompt, run: Callable[[Answer], Any], stale: Callable[[], object] | None = None) -> Plan:
        """Keep a question and what to do with its answer. stale: a cheap read of what the plan was made from (a
        profile's mtime, a version); execute() refuses when it no longer equals what it was now."""
        with self._lock:
            self._drop_expired()
            plan = Plan(f"p{next(self._ids)}", words, self._clock() + self._ttl)
            self._entries[plan.id] = _Entry(plan, run, stale, None if stale is None else stale())
        return plan

    def get(self, plan_id: str) -> Plan | None:
        with self._lock:
            self._drop_expired()
            entry = self._entries.get(plan_id)
            return None if entry is None else entry.plan

    def execute(self, plan_id: str, answer: Answer) -> Any:
        """Run the plan with the answer, once. A cancelled answer (ok False) drops the plan and runs nothing and
        returns None. Raises PlanError: unknown_plan (also a plan already executed), plan_expired, plan_stale."""
        with self._lock:
            entry = self._entries.pop(plan_id, None)
            if entry is None:
                raise PlanError("unknown_plan", "That question is no longer open.")
            if self._clock() >= entry.plan.expires_at:
                raise PlanError("plan_expired", "That question timed out. Ask again.")
        if not answer.ok:
            return None
        if entry.stale is not None and entry.stale() != entry.token:
            raise PlanError("plan_stale", "Things changed since you were asked. Ask again.")
        return entry.run(answer)

    def answer(self, plan_id: str, answers: Mapping[str, Any]) -> Any:
        """execute() with the answer given as plain data (ok, option, choice, ticked): what a client sends."""
        try:
            given = Answer(**{**answers, "ticked": tuple(answers.get("ticked") or ())})
        except TypeError as e:
            raise OperationError("invalid_params", f"That answer is not valid: {e}") from None
        return self.execute(plan_id, given)

    def _drop_expired(self) -> None:
        now = self._clock()
        for key in [k for k, e in self._entries.items() if now >= e.plan.expires_at]:
            del self._entries[key]


class PromptBroker:
    """A job's question as an event and the answer as a call. publish(data) sends the prompt out (the data carries
    prompt_id, the words, and job_id when a job asks); answer(prompt_id, key) resolves it. ask() has the shape of the
    Launch flow's Ports.ask; wait() blocks a job thread (JobContext.ask)."""

    def __init__(self, publish: Callable[[dict], None]):
        self._publish = publish
        self._lock = threading.Lock()
        self._open: dict[str, tuple[Choose, Callable[[str], None]]] = {}
        self._ids = itertools.count(1)

    def ask(self, words: Choose, on_answer: Callable[[str], None], job_id: str | None = None) -> str:
        with self._lock:
            prompt_id = f"q{next(self._ids)}"
            self._open[prompt_id] = (words, on_answer)
        extra = {} if job_id is None else {"job_id": job_id}
        self._publish({"prompt_id": prompt_id, **extra, **prompt_dict(words)})
        return prompt_id

    def words(self, prompt_id: str) -> Choose | None:
        """The question still open under prompt_id (a window shows it in its own way)."""
        with self._lock:
            got = self._open.get(prompt_id)
        return None if got is None else got[0]

    def answer(self, prompt_id: str, key: str) -> bool:
        """False when nobody is waiting for it (unknown or already answered)."""
        with self._lock:
            got = self._open.pop(prompt_id, None)
        if got is None:
            return False
        got[1](key)
        return True

    def wait(
        self,
        words: Choose,
        timeout: float | None = None,
        default: str = "cancel",
        job_id: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Ask and block the calling (job) thread for the answer; `default` when the timeout passes or the job is
        cancelled meanwhile."""
        got: list[str] = []
        done = threading.Event()
        prompt_id = self.ask(words, lambda key: (got.append(key), done.set()), job_id)
        waited = 0.0
        while not done.wait(0.1):
            waited += 0.1
            if (cancelled is not None and cancelled()) or (timeout is not None and waited >= timeout):
                with self._lock:
                    self._open.pop(prompt_id, None)
                return default
        return got[0]

    def pending(self) -> int:
        with self._lock:
            return len(self._open)
