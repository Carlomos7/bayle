"""Asking a client before a change, without a callback into a window.

The question types a client words and shows, and PromptBroker: a running job that asks mid-way (the Launch flow's
Ports.ask) sends its question out as a prompt event and gets the answer back by id. No Qt, no event loop.
"""

from __future__ import annotations

import itertools
import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True)
class Confirm:
    """A confirmation's words: the title states the action, the changes are what happens, warning and safety the
    risk and the way back; option a check box (with its starting state); apply the button."""

    title: str
    changes: tuple[str, ...]
    apply: str
    warning: str = ""
    safety: str = ""
    detail: str = ""
    option: str = ""
    option_checked: bool = False


@dataclass(frozen=True)
class Refusal:
    """Why something cannot go ahead: a toast's title and body."""

    title: str
    body: str
    info: bool = False  # said as plain news, not as an error ("Nothing to trim")


@dataclass(frozen=True)
class Pick:
    """A tick list's words: none is the button that goes on with nothing ticked ("" when one must be ticked)."""

    title: str
    body: str
    apply: str
    none: str = ""
    ticked: tuple[int, ...] = ()  # rows ticked at first
    rows: tuple[str, ...] = ()  # the rows' labels, when the words travel with them (a plan's prompt)


@dataclass(frozen=True)
class Choice:
    key: str
    label: str
    role: Literal["primary", "danger", "normal"] = "normal"


@dataclass(frozen=True)
class Choose:
    """A fork: the title is the question, the lines say what happens, the choices are verbs (Cancel last)."""

    title: str
    lines: tuple[str, ...]
    choices: tuple[Choice, ...]
    warning: str = ""
    safety: str = ""


@dataclass(frozen=True)
class Option:
    key: str
    role: Literal["primary", "danger", "normal"] = "normal"


@dataclass(frozen=True)
class Question:
    """A fork with no words: the client words it from the code and the facts (JSON-clean) and answers with an
    option's key. The Launch flow asks these."""

    code: str
    facts: dict
    options: tuple[Option, ...]


Prompt = Confirm | Pick | Choose  # what a client can be asked; a Refusal is told, not asked


def prompt_dict(words: Confirm | Pick | Choose | Question | Refusal) -> dict:
    """The schema as a JSON-clean dict with its kind ("confirm" | "pick" | "choose" | "refusal")."""
    kind = {Confirm: "confirm", Pick: "pick", Choose: "choose", Question: "question", Refusal: "refusal"}[type(words)]
    return {"kind": kind, **json.loads(json.dumps(asdict(words)))}


class PromptBroker:
    """A job's question as an event and the answer as a call. publish(data) sends the prompt out (the data carries
    prompt_id, the words, and job_id when a job asks); answer(prompt_id, key) resolves it. ask() has the shape of the
    Launch flow's Ports.ask; wait() blocks a job thread (JobContext.ask)."""

    def __init__(self, publish: Callable[[dict], None]):
        self._publish = publish
        self._lock = threading.Lock()
        self._open: dict[str, tuple[Choose | Question, Callable[[str], None]]] = {}
        self._ids = itertools.count(1)

    def ask(self, words: Choose | Question, on_answer: Callable[[str], None], job_id: str | None = None) -> str:
        with self._lock:
            prompt_id = f"q{next(self._ids)}"
            self._open[prompt_id] = (words, on_answer)
        extra = {} if job_id is None else {"job_id": job_id}
        self._publish({"prompt_id": prompt_id, **extra, **prompt_dict(words)})
        return prompt_id

    def words(self, prompt_id: str) -> Choose | Question | None:
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
