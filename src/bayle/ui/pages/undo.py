"""Taking a job back, for every page that offers it: ask the engine's Activity interface whether it can be, show the
Confirm through the page's Notifier, and start the undo (a job of its own, which the host follows on the event bus)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bayle.errors import Busy, OperationError
from bayle.ui.notifications import Notifier
from bayle.ui.pages.activity.presenter import ActivityPresenter


def ask_undo(host: Any, notifier: Notifier, job_id: str, refused: Callable[[], None] | None = None) -> None:
    """refused: called when it cannot be taken back now (after the toast says why)."""
    activity = host.activity
    presenter = ActivityPresenter(activity)

    def words(e: OperationError) -> str:
        r = presenter.refusal(e)
        return f"{r.title}. {r.body}"

    def check() -> Any:
        try:
            return activity.check_undo(job_id)
        except OperationError as e:
            return e

    def start(rec: dict, progress: str) -> None:
        try:
            activity.undo(job_id, rec["undo"], progress)
        except OperationError as e:  # busy, or changed since
            notifier.toast(e.message if isinstance(e, Busy) or e.code == "stale" else words(e), error=True)

    def shown(got: Any) -> None:
        if isinstance(got, OperationError):
            notifier.toast(words(got), error=True)
            if refused is not None:
                refused()
            return
        plan = presenter.undo_plan(got)
        notifier.confirm(plan.confirm, lambda ok: start(got, plan.progress) if ok else None)

    host.run_in_background(check, shown)
