"""The Activity page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). It holds
no decisions: it asks the engine's Activity interface on the host's worker thread, words what comes back with the
presenter and shows it; the Confirm Undo needs goes through the Notifier, and the undo itself runs as a job the host
follows on the event bus."""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Protocol

from bayle.modules.activity.service import ActivityService
from PySide6.QtCore import Property, QObject, Signal, Slot
from PySide6.QtGui import QGuiApplication

from bayle_qt.models import RowsModel
from bayle_qt.notifications import Notifier
from bayle_qt.pages.activity import presenter as view
from bayle_qt.pages.activity.presenter import ActivityPresenter, ActivityState, LogText
from bayle_qt.pages.undo import ask_undo
from bayle_qt.text import tr


class ActivityHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell, S9)."""

    @property
    def activity(self) -> ActivityService: ...

    def mark_seen(self) -> None:
        """The user looked at Activity: failures so far are no longer new."""

    def run_in_background(self, work, on_result) -> None:
        """work() on a worker thread, on_result(value) back on the UI thread (ui.jobs.Jobs.start)."""


class ActivityAdapter(QObject):
    changed = Signal()  # summary, empty text, filters
    logChanged = Signal()
    loadingChanged = Signal()

    def __init__(
        self,
        host: ActivityHost,
        notifier: Notifier,
        parent=None,
        now: Callable[[], datetime.datetime] = datetime.datetime.now,
    ):
        super().__init__(parent)
        self._now = now
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
        self._log = LogText((), "")
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
        presenter = ActivityPresenter(self.host.activity, self._now)
        self.host.run_in_background(lambda: presenter.refresh(game, kind, failed), self._apply)

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
        str, lambda self: self._log.plain or "\n".join(row[2] for row in self._log.rows), notify=logChanged
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
        self._open_job, self._source, self._log = "", "", LogText((), "")
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
        activity = self.host.activity

        def read() -> LogText:
            return ActivityPresenter.log_text(activity.log(want[0], want[1]), want[2])

        def shown(got: LogText) -> None:
            if want == (self._open_job, self._source, self._detail):  # not for a log the user has left
                self._log = got
                self.logChanged.emit()

        self.host.run_in_background(read, shown)

    @Slot(bool)
    def copyLog(self, for_support: bool) -> None:
        activity, job, source, detail = self.host.activity, self._open_job, self._source, self._detail

        def read() -> str:
            log = ActivityPresenter.log_text(activity.log(job, source), detail)
            return ActivityPresenter.copy_text(log, for_support)

        def shown(text: str) -> None:
            QGuiApplication.clipboard().setText(text)
            self.notifier.toast(tr("Copied with your user name and Steam IDs masked") if for_support else tr("Copied"))

        self.host.run_in_background(read, shown)

    @Slot()
    def openLogFile(self) -> None:
        activity, job, source = self.host.activity, self._open_job, self._source

        def shown(path) -> None:
            if path is None:
                self.notifier.toast(tr("That file is no longer there."), error=True)
                return
            from bayle.adapters.system import desktop

            desktop.open_path(path)

        self.host.run_in_background(lambda: activity.log_path(job, source), shown)

    # ---- Undo
    @Slot(str)
    def undo(self, job_id: str) -> None:
        ask_undo(self.host, self.notifier, job_id, refused=self.refresh)

    # ---- for tests and the self-test
    def snapshot(self) -> dict:
        return {"summary": self._summary.rows(), "days": self._days.rows(), "empty": self._state.empty}
