"""The Launch flow's ports as events: a question is a `prompt` event answered by id (Session.answer_prompt, or the
window's own dialog answering the same broker), a toast a `notice` event, a step a refresh of the shell, a job a session
job. The same ports serve the window and the API; nothing here knows either."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from bayle.errors import Busy

if TYPE_CHECKING:
    from bayle.session.shell.launch import Ask
    from bayle.session.shell.service import Shell


class EventPorts:
    def __init__(self, shell: Shell):
        self.s = shell

    def ask(self, ask: Ask, on_answer: Callable[[str], None]) -> None:
        self.s.jobs.prompts.ask(ask, on_answer)

    def toast(self, text: str, error: bool = False) -> None:
        self.s.notice(text, error=error)

    def progress(self, label: str) -> None:
        self.s.step = label
        self.s.invalidate("shell")

    def background(self, work: Callable[[], Any], on_result: Callable[[Any], None]) -> None:
        self.s.background.start(lambda _progress: work(), on_result=on_result)

    def run_job(self, job, label: str, kind: str, on_done: Callable[[bool], None] | None = None) -> None:
        try:
            self.s.start(job, label, kind, external=True, on_done=on_done)
        except Busy as e:
            self.s.notice(e.message, error=True)
            if on_done is not None:
                on_done(False)

    def save_pending(self) -> str | None:
        return self.s.save_pending()

    def show_activity(self) -> None:
        self.s.navigate("activity")
