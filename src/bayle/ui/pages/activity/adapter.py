"""The Activity page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). It holds
no decisions: it asks the session (snapshot of the page, the log operations, Undo as a plan) on the host's worker
thread and shows what comes back; the Confirm Undo needs goes through the Notifier, and the undo itself runs as a
session job the host follows on the event bus."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from bayle.platform.text import tr
from bayle.session import Session
from bayle.session.ops.activity import LogView
from bayle.ui.models import RowsModel
from bayle.ui.notifications import Notifier
from bayle.ui.pages.undo import ask_undo
from bayle.views import activity as view
from bayle.views.activity import ActivityState


class ActivityHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell, S9)."""

    @property
    def session(self) -> Session: ...

    def mark_seen(self) -> None:
        """The user looked at Activity: failures so far are no longer new."""

    def run_in_background(self, work, on_result) -> None:
        """work() on a worker thread, on_result(value) back on the UI thread (ui.jobs.Jobs.start)."""


class ActivityAdapter(QObject):
    changed = Signal()  # summary, empty text, filters
    logChanged = Signal()
    loadingChanged = Signal()

    def __init__(self, host: ActivityHost, notifier: Notifier, parent=None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.words_ = view.words()
        self._state = ActivityState((), (), "")
        self._game = ""
        self._kind = ""
        self._failed_only = False
        self._loading = False
        self._again = False
        self._open_job = ""
        self._source = ""
        self._detail = False
        self._log = LogView(rows=[], plain="")
        self._summary = RowsModel(("label", "value", "level"), self)
        self._days = RowsModel(("label", "jobs"), self)
        self._games = RowsModel(("key", "label"), self)
        self._kinds = RowsModel(("key", "label"), self)
        self._games.set_rows(view.game_choices())
        self._kinds.set_rows(view.kind_choices())

    # ---- the text the page carries (all from the presenter, through tr())
    title = Property(str, lambda self: self.words_.title, constant=True)
    subtitle = Property(str, lambda self: self.words_.subtitle, constant=True)
    failedOnlyText = Property(str, lambda self: self.words_.failed_only_text, constant=True)
    words = Property(
        dict,
        lambda self: {
            "showDetails": tr("Show details"),
            "showDetailsTip": tr("Every line, including the fine detail kept for tracking down problems."),
            "copy": tr("Copy"),
            "copyTip": tr("Copy what is shown."),
            "copySupport": tr("Copy for support"),
            "copySupportTip": tr("Copy what is shown with your user name and Steam IDs masked, to paste in a report."),
            "openFile": tr("Open file"),
            "showLog": tr("Show this job's log"),
            "hideLog": tr("Hide this job's log"),
            "copied": tr("Copied"),
        },
        constant=True,
    )

    # ---- models
    summary = Property(QObject, lambda self: self._summary, constant=True)
    days = Property(QObject, lambda self: self._days, constant=True)
    games = Property(QObject, lambda self: self._games, constant=True)
    kinds = Property(QObject, lambda self: self._kinds, constant=True)
    empty = Property(str, lambda self: self._state.empty, notify=changed)
    loading = Property(bool, lambda self: self._loading, notify=loadingChanged)

    # ---- filters
    def _label(self, model: RowsModel, key: str) -> str:
        return next((r["label"] for r in model.rows() if r["key"] == key), "")

    game = Property(str, lambda self: self._game, notify=changed)
    gameLabel = Property(str, lambda self: self._label(self._games, self._game), notify=changed)
    kind = Property(str, lambda self: self._kind, notify=changed)
    kindLabel = Property(str, lambda self: self._label(self._kinds, self._kind), notify=changed)
    failedOnly = Property(bool, lambda self: self._failed_only, notify=changed)

    @Slot(str)
    def setGame(self, key: str) -> None:
        self._game = key
        self.refresh()

    @Slot(str)
    def setKind(self, key: str) -> None:
        self._kind = key
        self.refresh()

    @Slot(bool)
    def setFailedOnly(self, on: bool) -> None:
        self._failed_only = on
        self.refresh()

    # ---- reading the jobs again (on the job runner's worker thread)
    @Slot()
    def refresh(self) -> None:
        if self._loading:
            self._again = True  # one more read when this one lands, with the filters as they are then
            return
        self._loading = True
        self.loadingChanged.emit()
        game, kind, failed = self._game, self._kind, self._failed_only
        session = self.host.session
        self.host.run_in_background(
            lambda: session.snapshot("activity", game=game, group=kind, failed_only=failed), self._apply
        )

    def _apply(self, state: ActivityState) -> None:
        self._loading = False
        self.loadingChanged.emit()
        if self._again:
            self._again = False
            self.refresh()
            return
        self._state = state
        self._summary.set_rows(state.summary)
        self._days.set_rows(state.days)
        self.changed.emit()
        if self._open_job and not any(j.id == self._open_job for d in state.days for j in d.jobs):
            self.closeLog()
        elif self._open_job:
            self._read_log()

    def state(self) -> ActivityState:
        """What the page shows now (tests and the self-test)."""
        return self._state

    @Slot()
    def seen(self) -> None:
        self.host.mark_seen()

    # ---- one job's log (one open at a time)
    openJob = Property(str, lambda self: self._open_job, notify=logChanged)
    logText = Property(
        str, lambda self: self._log.plain or "\n".join(r.text for r in self._log.rows), notify=logChanged
    )
    logNote = Property(str, lambda self: self._log.note, notify=logChanged)
    logSource = Property(str, lambda self: self._source, notify=logChanged)
    logDetail = Property(bool, lambda self: self._detail, notify=logChanged)
    logMissing = Property(bool, lambda self: self._log.missing, notify=logChanged)

    @Slot(str)
    def toggleLog(self, job_id: str) -> None:
        if job_id == self._open_job:
            self.closeLog()
            return
        self._open_job, self._source, self._detail = job_id, "", False
        self._read_log()

    @Slot()
    def closeLog(self) -> None:
        self._open_job, self._source, self._log = "", "", LogView(rows=[], plain="")
        self.logChanged.emit()

    @Slot(str)
    def setLogSource(self, source: str) -> None:
        self._source = source
        self._read_log()

    @Slot(bool)
    def setLogDetail(self, on: bool) -> None:
        self._detail = on
        self._read_log()

    def _read_log(self) -> None:
        want = (self._open_job, self._source, self._detail)
        session = self.host.session

        def read() -> LogView:
            return session.run("activity.log", {"job_id": want[0], "source": want[1], "detail": want[2]})

        def shown(got: LogView) -> None:
            if want == (self._open_job, self._source, self._detail):  # not for a log the user has left
                self._log = got
                self.logChanged.emit()

        self.host.run_in_background(read, shown)

    @Slot(bool)
    def copyLog(self, for_support: bool) -> None:
        session = self.host.session
        want = {"job_id": self._open_job, "source": self._source, "detail": self._detail, "for_support": for_support}

        def shown(got) -> None:
            QGuiApplication.clipboard().setText(got.text)
            self.notifier.toast(tr("Copied with your user name and Steam IDs masked") if for_support else tr("Copied"))

        self.host.run_in_background(lambda: session.run("activity.copy", want), shown)

    @Slot()
    def openLogFile(self) -> None:
        session = self.host.session
        want = {"job_id": self._open_job, "source": self._source}

        def shown(got) -> None:
            if got.path is None:
                self.notifier.toast(tr("That file is no longer there."), error=True)
                return
            from bayle.platform import desktop

            desktop.open_path(got.path)

        self.host.run_in_background(lambda: session.run("activity.log_file", want), shown)

    # ---- Undo
    @Slot(str)
    def undo(self, job_id: str) -> None:
        ask_undo(self.host, self.notifier, job_id, refused=self.refresh)

    # ---- for tests and the self-test
    def snapshot(self) -> dict:
        return {"summary": self._summary.rows(), "days": self._days.rows(), "empty": self._state.empty}
