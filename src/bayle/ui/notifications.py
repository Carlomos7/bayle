"""The notification helpers every QML page uses (technical specification §8.10, "how the launcher talks"): the
status text (the one place launcher state shows), the page InfoBar (a lasting condition on this page), a toast (the
result of what the user just did; errors stay until closed) and the confirmation dialog (before a change). A page's
adapter calls them; the window (or, from S9, the shell) shows them with the QML components of the same names.

Plain Python callers: status(), info(), clear_info(), toast(), confirm(). QML reads statusText / infoText /
infoSeverity, listens to toastRequested and confirmRequested, and answers a confirmation with answer()."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from bayle.views.common import Choose, Confirm


class Notifier(QObject):
    statusChanged = Signal()
    infoChanged = Signal()
    toastRequested = Signal(str, bool)  # text, is an error
    # token, title, the changes (one per line), the safety line, the apply button's text, destructive
    confirmRequested = Signal(int, str, list, str, str, bool)
    toastActionRequested = Signal(str, bool, str, int)  # text, is an error, the action's words, token
    confirmFullRequested = Signal(int, dict)  # token, the words (see ask)
    chooseRequested = Signal(int, dict)  # token, the words (see choose)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._status = ""
        self._info = ("", "info")
        self._waiting: dict[int, Callable[[bool], None]] = {}
        self._full: dict[int, Callable[[bool, bool], None]] = {}
        self._actions: dict[int, Callable[[], None]] = {}
        self._choosing: dict[int, Callable[[str], None]] = {}
        self._next = 0

    # ---- the status text
    def status(self, text: str) -> None:
        if text != self._status:
            self._status = text
            self.statusChanged.emit()

    statusText = Property(str, lambda self: self._status, notify=statusChanged)

    # ---- the InfoBar
    def info(self, text: str, severity: str = "info") -> None:
        """Show a lasting condition (severity info | success | warning | error) until clear_info()."""
        if (text, severity) != self._info:
            self._info = (text, severity)
            self.infoChanged.emit()

    @Slot()
    def clear_info(self) -> None:
        self.info("")

    infoText = Property(str, lambda self: self._info[0], notify=infoChanged)
    infoSeverity = Property(str, lambda self: self._info[1], notify=infoChanged)

    # ---- toasts
    def toast(self, text: str, error: bool = False) -> None:
        self.toastRequested.emit(text, error)

    def toast_action(self, text: str, action: str, on_action: Callable[[], None], error: bool = False) -> int:
        """A toast with one action (Undo, Edit options): on_action() runs when it is clicked."""
        self._next += 1
        self._actions[self._next] = on_action
        self.toastActionRequested.emit(text, error, action, self._next)
        return self._next

    @Slot(int)
    def toastAction(self, token: int) -> None:
        call = self._actions.pop(token, None)
        if call is not None:
            call()

    # ---- the confirmation dialog, all its parts (views.common.Confirm and the like)
    def ask(self, words, on_answer: Callable[[bool, bool], None], destructive: bool = False) -> int:
        """Ask before a change in the words given (title, changes, apply, warning, safety, detail, option,
        option_checked); on_answer(applied, option ticked)."""
        self._next += 1
        self._full[self._next] = on_answer
        self.confirmFullRequested.emit(
            self._next,
            {
                "title": words.title,
                "changes": list(words.changes),
                "apply": words.apply,
                "warning": getattr(words, "warning", ""),
                "safety": getattr(words, "safety", ""),
                "detail": getattr(words, "detail", ""),
                "option": getattr(words, "option", ""),
                "optionChecked": bool(getattr(words, "option_checked", False)),
                "destructive": destructive,
            },
        )
        return self._next

    @Slot(int, bool, bool)
    def answerWith(self, token: int, ok: bool, option_on: bool) -> None:
        call = self._full.pop(token, None)
        if call is not None:
            call(ok, option_on)

    # ---- a fork with named choices (Retry / Launch without backup / Cancel)
    def choose(self, words: Choose, on_answer: Callable[[str], None], cancel: str = "cancel") -> int:
        """Ask which way to go. Cancel is last in words.choices; on_answer(key) gets the chosen key, or `cancel`
        when the dialog is closed (Esc)."""
        self._next += 1
        self._choosing[self._next] = on_answer
        self.chooseRequested.emit(
            self._next,
            {
                "title": words.title,
                "lines": list(words.lines),
                "choices": [{"key": c.key, "label": c.label, "role": c.role} for c in words.choices],
                "warning": words.warning,
                "safety": words.safety,
                "cancel": cancel,
            },
        )
        return self._next

    @Slot(int, str)
    def chosen(self, token: int, key: str) -> None:
        call = self._choosing.pop(token, None)
        if call is not None:
            call(key)

    # ---- the plain confirmation dialog (the same words as ask, shown without the extra parts)
    def confirm(self, words: Confirm, on_answer: Callable[[bool], None], destructive: bool = False) -> int:
        """Ask before a change; on_answer(True) when the user applies it, (False) when they cancel."""
        self._next += 1
        self._waiting[self._next] = on_answer
        self.confirmRequested.emit(self._next, words.title, list(words.changes), words.safety, words.apply, destructive)
        return self._next

    @Slot(int, bool)
    def answer(self, token: int, ok: bool) -> None:
        call = self._waiting.pop(token, None)
        if call is not None:
            call(ok)

    def waiting(self) -> int:
        """How many confirmations are still unanswered."""
        return len(self._waiting) + len(self._full) + len(self._choosing)

    def drop_pending(self) -> None:
        """Forget every unanswered question and toast action. Their callbacks close over the page's adapter, which owns
        this Notifier: left in place they are a reference cycle that frees the adapter at some later garbage collection."""
        for pending in (self._waiting, self._full, self._actions, self._choosing):
            pending.clear()
