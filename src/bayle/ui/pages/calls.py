"""A page's way to the session: run an operation off the UI thread, say its refusal, ask the question a plan or a
"needs confirmation" error carries through the page's Notifier, and follow a job to its end. No decision is made
here; the adapters hold no closure over work, only over what to do with the answer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from bayle.platform.text import tr
from bayle.platform.threads import as_worker
from bayle.services.errors import OperationError
from bayle.ui.notifications import Notifier
from bayle.views.common import Confirm, Pick, Refusal


def confirm_from(prompt: dict) -> Confirm:
    """The Confirm a "needs_confirmation" error carries in details["prompt"] (views.common.prompt_dict)."""
    return Confirm(
        title=prompt["title"],
        changes=tuple(prompt.get("changes") or ()),
        apply=prompt["apply"],
        warning=prompt.get("warning", ""),
        safety=prompt.get("safety", ""),
        detail=prompt.get("detail", ""),
        option=prompt.get("option", ""),
        option_checked=bool(prompt.get("option_checked")),
    )


def say_refusal(notifier: Notifier, refusal: Refusal) -> None:
    notifier.toast(f"{refusal.title}. {refusal.body}", error=not refusal.info)


class Calls:
    """host.session, run from a page. Everything lands on the UI thread."""

    def __init__(self, host: Any, notifier: Notifier):
        self.host, self.notifier = host, notifier

    def _follow(self, job_id: str, done: Callable[[bool, dict], None] | None) -> None:
        """done(ok, data) when the job ends: data is its result and undo, or the error (code, message, details)."""
        if done is None:
            return

        def ended(snap: Any) -> None:
            if snap is not None and snap.state == "done":
                done(True, {"result": snap.result, "undo": snap.undo})
            else:
                err = getattr(snap, "error", None)
                done(
                    False, {"error": {"code": err.code, "message": err.message, "details": err.details} if err else {}}
                )

        self.host.follow_job(job_id, ended)

    def say(self, e: OperationError) -> None:
        self.notifier.toast(e.message, error=True)

    def run(
        self,
        op: str,
        params: dict | None = None,
        then: Callable[[Any], None] | None = None,
        fail: Callable[[OperationError], None] | None = None,
        *,
        retry: Callable[[bool], dict] | None = None,
        destructive: bool = False,
        declined: Callable[[], None] | None = None,
    ) -> None:
        """Run op on the worker; then(result) on the UI thread. A refusal goes to fail (default: an error toast). When the
        operation asks for a confirmation (needs_confirmation) and retry is given, the player is asked and, on yes, it
        runs again with confirmed=True and retry(option ticked) added to its params (declined() on no)."""
        session = self.host.session

        def work() -> Any:
            try:
                with as_worker():  # a test host runs this inline
                    return session.run(op, params)
            except OperationError as e:
                return e

        def landed(got: Any) -> None:
            if not isinstance(got, OperationError):
                if then is not None:
                    then(got)
            elif got.code == "needs_confirmation" and retry is not None:
                extra = retry

                def answered(ok: bool, option: bool) -> None:
                    if ok:
                        again = {**(params or {}), "confirmed": True, **extra(option)}
                        self.run(op, again, then, fail, destructive=destructive)
                    elif declined is not None:
                        declined()

                self.notifier.ask(confirm_from(got.details["prompt"]), answered, destructive=destructive)
            else:
                (fail or self.say)(got)

        self.host.run_in_background(work, landed)

    def job(
        self,
        op: str,
        params: dict | None = None,
        done: Callable[[bool, dict], None] | None = None,
        fail: Callable[[OperationError], None] | None = None,
        *,
        retry: Callable[[bool], dict] | None = None,
        destructive: bool = False,
        declined: Callable[[], None] | None = None,
    ) -> None:
        """Run a job operation; done(ok, data) when it ends (data: its finished event, or its failed event's error)."""

        def started(job_id: str) -> None:
            self._follow(job_id, done)

        self.run(op, params, started, fail, retry=retry, destructive=destructive, declined=declined)

    def plan(
        self,
        op: str,
        params: dict | None = None,
        *,
        destructive: bool = False,
        done: Callable[[bool, dict], None] | None = None,
        after: Callable[[Any], None] | None = None,
        refused: Callable[[], None] | None = None,
        pick: Callable[[str, Pick], None] | None = None,
        plain: bool = False,
    ) -> None:
        """Ask the operation's plan: show its Confirm (plain: without the option and the other extra parts; or hand a
        Pick to pick(plan id, words)); on yes it runs: after(what it returned) and, when it started a job, done
        follows it. A refusal is said (and refused() called)."""

        def offered(got: Any) -> None:
            if isinstance(got, Refusal):
                say_refusal(self.notifier, got)
                if refused is not None:
                    refused()
            elif isinstance(got.words, Pick):
                if pick is not None:
                    pick(got.id, got.words)
            elif plain:
                self.notifier.confirm(
                    got.words, lambda ok: self.answer(got.id, ok, done=done, after=after), destructive
                )
            else:
                self.notifier.ask(
                    got.words,
                    lambda ok, option: self.answer(got.id, ok, option=option, done=done, after=after),
                    destructive,
                )

        self.run(op, params, offered)

    def ask_each(self, prompts: list[dict], then: Callable[[list[int]], None], destructive: bool = False) -> None:
        """Ask the Confirm prompts (as the session sent them) one at a time, in order; then(indexes answered yes)."""
        yes: list[int] = []

        def next_one(i: int) -> None:
            if i >= len(prompts):
                then(yes)
                return

            def answered(ok: bool, _option: bool) -> None:
                if ok:
                    yes.append(i)
                next_one(i + 1)

            self.notifier.ask(confirm_from(prompts[i]), answered, destructive=destructive)

        next_one(0)

    def answer(
        self,
        plan_id: str,
        ok: bool,
        *,
        option: bool = False,
        ticked: tuple[int, ...] = (),
        done: Callable[[bool, dict], None] | None = None,
        after: Callable[[Any], None] | None = None,
    ) -> None:
        session = self.host.session

        def work() -> Any:
            try:
                with as_worker():
                    return session.answer(plan_id, {"ok": ok, "option": option, "ticked": list(ticked)})
            except OperationError as e:  # busy, expired, or changed since
                return e

        def landed(got: Any) -> None:
            if isinstance(got, OperationError):
                self.say(got)
                return
            if ok and after is not None:
                after(got)
            if isinstance(got, str):
                self._follow(got, done)

        self.host.run_in_background(work, landed)


def failed_words(data: dict) -> str:
    """The words of a failed job's error, for a toast: "Could not ...: why"."""
    return str((data.get("error") or {}).get("message") or tr("It did not finish."))
