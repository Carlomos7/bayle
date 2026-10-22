"""Taking a job back, for every page that offers it: ask the session for the plan, show its Confirm through the page's
Notifier, and send the answer back. The undo itself runs as a session job; the host follows it on the event bus."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bayle.platform.text import tr
from bayle.services.errors import OperationError
from bayle.ui.notifications import Notifier
from bayle.views.common import Refusal


def ask_undo(host: Any, notifier: Notifier, job_id: str, refused: Callable[[], None] | None = None) -> None:
    """refused: called when it cannot be taken back now (after the toast says why)."""
    session = host.session

    def offer() -> Any:
        try:
            return session.run("activity.undo", {"job_id": job_id})
        except OperationError as e:
            return Refusal(tr("It cannot be taken back"), e.message)

    def answered(plan_id: str, ok: bool) -> None:
        try:
            session.answer(plan_id, {"ok": ok})
        except OperationError as e:  # busy, expired, or changed since
            notifier.toast(e.message, error=True)

    def shown(got: Any) -> None:
        if isinstance(got, Refusal):
            notifier.toast(f"{got.title}. {got.body}", error=True)
            if refused is not None:
                refused()
            return
        notifier.confirm(got.words, lambda ok: answered(got.id, ok))

    host.run_in_background(offer, shown)
