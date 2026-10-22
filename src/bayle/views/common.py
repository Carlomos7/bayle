"""The words every client shows when the launcher must ask or refuse: one schema for all presenters (Qt-free, frozen,
JSON-clean through prompt_dict). A Confirm asks before a change, a Pick asks which rows of a list, a Choose asks which
way to go (named verbs), a Refusal says why something cannot go ahead. The strings are final (tr() already applied)."""

from __future__ import annotations

import json
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


@dataclass(frozen=True)
class Pick:
    """A tick list's words: none is the button that goes on with nothing ticked ("" when one must be ticked)."""

    title: str
    body: str
    apply: str
    none: str = ""
    ticked: tuple[int, ...] = ()  # rows ticked at first


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


Prompt = Confirm | Pick | Choose  # what a client can be asked; a Refusal is told, not asked


def prompt_dict(words: Confirm | Pick | Choose | Refusal) -> dict:
    """The schema as a JSON-clean dict with its kind ("confirm" | "pick" | "choose" | "refusal")."""
    kind = {Confirm: "confirm", Pick: "pick", Choose: "choose", Refusal: "refusal"}[type(words)]
    return {"kind": kind, **json.loads(json.dumps(asdict(words)))}
