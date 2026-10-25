"""The Activity page's presenter (technical specification §8.10, Activity): what the launcher did, one entry per job
(Play, a repair, an install, a rebuild...), newest first and grouped by day, with how each ended; a summary row (last
Play, last install, last failure); filters by game, kind and failure; a job's log one click down; Undo where the job
can still be taken back.

Plain Python, no Qt: the adapter (adapter.py) hands what this returns to QML, and the Widgets window uses the same
Undo plans. Every string goes through tr(). Background housekeeping is not listed; it is in launcher.log."""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from bayle.errors import OperationError
from bayle.game import catalog as games
from bayle.mods import kinds
from bayle.mods import undo as mod_undo
from bayle.platform import logging as run_logging
from bayle.services.activity import JobLog
from bayle.work.prompts import Confirm, Refusal

from bayle_qt.text import plural, tr

SHOWN = 100  # entries listed at most (retention keeps about this many anyway)
FAILED = ("failed", "interrupted")

# outcome -> (pill text, pill level); levels are the QML Pill's (success | warning | danger | info | muted)
OUTCOMES = {
    "running": ("Running", "info"),
    "done": ("Done", "success"),
    "warnings": ("Done, with warnings", "warning"),
    "failed": ("Failed", "danger"),
    "interrupted": ("Interrupted", "danger"),
    "stopped": ("Stopped", "muted"),
}


# ----------------------------------------------------------------------------- what the page shows
@dataclass(frozen=True)
class Choice:
    """One entry of a filter drop-down: the value it filters by ("" for all) and its label."""

    key: str
    label: str


@dataclass(frozen=True)
class SummaryCard:
    label: str
    value: str
    level: str  # success | danger | muted


@dataclass(frozen=True)
class JobItem:
    """One job's row."""

    id: str
    when: str  # HH:MM
    title: str
    outcome: str  # the pill's text
    level: str  # the pill's level
    meta: str  # duration and game
    line: str  # the one-line result (the problem, for a failure)
    failed: bool
    undo_label: str  # "" when it cannot be taken back
    undo_tip: str
    sources: tuple[Choice, ...]  # the log, then other programs' output kept with it


@dataclass(frozen=True)
class Day:
    label: str
    jobs: tuple[JobItem, ...]


@dataclass(frozen=True)
class ActivityState:
    summary: tuple[SummaryCard, ...]
    days: tuple[Day, ...]
    empty: str  # what to say when no job is shown ("" when some are)
    unseen: int = 0  # failures since Activity was last looked at (the rail badge)


@dataclass(frozen=True)
class LogText:
    """A job's log (or an attachment) as shown: rows of (time, level, text), the plain text Copy takes, and a note
    (lines hidden, only the end shown, the file gone)."""

    rows: tuple[tuple[str, str, str], ...]
    plain: str
    note: str = ""
    missing: bool = False


@dataclass(frozen=True)
class UndoPlan:
    """What taking a job back does, for the confirmation, and the job that does it."""

    title: str
    changes: tuple[str, ...]
    safety: str
    apply_text: str
    progress: str  # the status while it runs
    undo: dict = field(default_factory=dict)
    job_id: str = ""
    name: str = ""

    @property
    def confirm(self) -> Confirm:
        return Confirm(self.title, self.changes, self.apply_text, safety=self.safety)


class ActivityFacts(Protocol):
    """What the presenter is told about the world (services.activity.ActivityService reads it from disk): the views
    do no I/O of their own."""

    def jobs(self) -> list[dict]: ...
    def undo_available(self, undo: dict) -> bool: ...
    def in_trash(self, path: object) -> bool: ...


# ----------------------------------------------------------------------------- small words
def when_of(rec: dict) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(rec.get("start") or "")
    except ValueError:
        return None


def day_label(day: datetime.date, today: datetime.date) -> str:
    if day == today:
        return tr("Today")
    if day == today - datetime.timedelta(days=1):
        return tr("Yesterday")
    return day.strftime("%A %d %B %Y").replace(" 0", " ")


def day_word(day: datetime.date, today: datetime.date) -> str:
    """The day inside a sentence: today, yesterday, or Mon 5 Oct."""
    if day == today:
        return tr("today")
    if day == today - datetime.timedelta(days=1):
        return tr("yesterday")
    return day.strftime("%a %d %b").replace(" 0", " ")


def duration_text(seconds) -> str:
    if seconds is None:
        return ""
    s = int(round(float(seconds)))
    if s < 1:
        return tr("under a second")
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


def title_text(rec: dict) -> str:
    t = str(rec.get("title") or tr("Job")).strip()
    return t[:1].upper() + t[1:]


def game_name(key: str) -> str:
    try:
        return games.resolve(key).name if key else ""
    except Exception:
        return key


def matches(rec: dict, game: str, group: str, failed_only: bool) -> bool:
    if game and rec.get("game") and rec.get("game") != game:
        return False
    if group and run_logging.group_of(rec.get("kind") or "") != group:
        return False
    return not failed_only or rec.get("outcome") in FAILED


# (pattern in the recorded problem, plain words): the record keeps its raw text, only the row is reworded
PROBLEM_WORDS = (
    (r"clash|conflict", tr("Two mods change the same game data file. Details are in the log.")),
    (
        r"permission|access is denied|in use|being used|locked",
        tr("A file was in use. Close the game and other programs using it, then try again."),
    ),
    (r"game is running|is running|still running", tr("The game was running. Close it, then try again.")),
    (r"disk|no space|not enough space", tr("There was not enough disk space.")),
    (r"no such file|not found|does not exist|missing", tr("A file it needed was missing. Details are in the log.")),
)


def plain_problem(raw: str) -> str:
    """A failed job's recorded problem in words for the player; the log keeps the original."""
    for pattern, words in PROBLEM_WORDS:
        if re.search(pattern, raw, re.IGNORECASE):
            return words
    return tr("It did not finish. Details are in the log.")


def result_line(rec: dict) -> str:
    """The one line under a job: its problem when it failed, else its summary."""
    line = rec.get("problem") if rec.get("outcome") in FAILED else ""
    line = plain_problem(line) if line else rec.get("summary") or ""
    if rec.get("outcome") == "interrupted" and not line:
        line = tr("The launcher closed before this job finished.")
    return line


def log_row(e: dict) -> tuple[str, str, str]:
    """A log entry for the viewer. The job's own start and end lines read as quiet notes, not as output."""
    text = e["text"]
    if e["source"] == "job" and text.startswith("=== ") and text.endswith(" ==="):
        return (e["time"], "debug", text[4:-4])
    return (e["time"], e["level"], text)


# ----------------------------------------------------------------------------- the words the page carries
@dataclass(frozen=True)
class ActivityWords:
    title: str
    subtitle: str
    open_window_text: str
    open_window_tip: str
    failed_only_text: str


def words() -> ActivityWords:
    return ActivityWords(
        tr("Activity"),
        tr("What the launcher did: every launch, repair, install and rebuild, with how it went and its log."),
        tr("Open new Activity window"),
        tr("A preview of the new Activity page, in its own window."),
        tr("Failed only"),
    )


def game_choices() -> tuple[Choice, ...]:
    return (Choice("", tr("All games")), *(Choice(g.key, g.name) for g in games.GAMES))


def kind_choices() -> tuple[Choice, ...]:
    return (Choice("", tr("All kinds")), *(Choice(g, tr(g)) for g in run_logging.GROUPS))


# ----------------------------------------------------------------------------- the presenter
class ActivityPresenter:
    """The page's state from the jobs index. refresh() reads it again; the filters are its arguments."""

    def __init__(self, facts: ActivityFacts, now: Callable[[], datetime.datetime] = datetime.datetime.now):
        self._facts, self._now = facts, now

    # ---- the list
    def refresh(self, game: str = "", group: str = "", failed_only: bool = False) -> ActivityState:
        recs = self._facts.jobs()
        today = self._now().date()
        shown = [r for r in recs if matches(r, game, group, failed_only)][:SHOWN]
        days: list[Day] = []
        current: list[JobItem] = []
        label = None
        for rec in shown:
            when = when_of(rec)
            this = day_label(when.date(), today) if when else tr("Unknown date")
            if this != label:
                if current:
                    days.append(Day(label or "", tuple(current)))
                label, current = this, []
            current.append(self._item(rec))
        if current:
            days.append(Day(label or "", tuple(current)))
        if not recs:
            empty = tr("Nothing yet. Launches, repairs, installs and rebuilds show up here.")
        elif not shown:
            empty = tr("Nothing matches these filters.")
        else:
            empty = ""
        return ActivityState(self._summary(recs, today), tuple(days), empty)

    def _item(self, rec: dict) -> JobItem:
        when = when_of(rec)
        outcome = rec.get("outcome") or ""
        text, level = OUTCOMES.get(outcome, (str(outcome or "?").capitalize(), "muted"))
        meta = [duration_text(rec.get("seconds")), game_name(rec.get("game") or "")]
        undo = rec.get("undo")
        can_undo = bool(undo) and outcome in ("done", "warnings") and self._facts.undo_available(undo or {})
        sources = [Choice(rec.get("log") or "", tr("Log"))]
        for name in rec.get("attachments") or []:
            label = name.rsplit(".", 2)[-2] if name.count(".") >= 2 else name
            sources.append(Choice(name, tr("{program} output").format(program=label)))
        return JobItem(
            id=str(rec.get("id") or ""),
            when=when.strftime("%H:%M") if when else "",
            title=title_text(rec),
            outcome=tr(text),
            level=level,
            meta="  ·  ".join(m for m in meta if m),
            line=result_line(rec),
            failed=outcome in FAILED,
            undo_label=tr(mod_undo.label(undo)) if can_undo else "",
            undo_tip=tr("Take this back: {what}").format(what=rec.get("summary") or title_text(rec))
            if can_undo
            else "",
            sources=tuple(sources),
        )

    def _summary(self, recs: list[dict], today: datetime.date) -> tuple[SummaryCard, ...]:
        """Last Play, last install, last failure (the index is newest first)."""

        def first(test) -> dict | None:
            return next((r for r in recs if test(r)), None)

        def when(rec: dict) -> str:
            w = when_of(rec)
            return day_word(w.date(), today) if w else ""

        play = first(lambda r: r.get("kind") == "play")
        install = first(lambda r: r.get("kind") == "install")
        failure = first(lambda r: r.get("outcome") in FAILED)
        none = tr("None yet")
        cards = []
        if play:
            w = when_of(play)
            bits = [f"{day_word(w.date(), today).capitalize()} {w.strftime('%H:%M')}" if w else ""]
            bits.append(duration_text(play.get("seconds")))
            level = "danger" if play.get("outcome") in FAILED else "success"
            cards.append(SummaryCard(tr("Last launch"), "  ·  ".join(b for b in bits if b), level))
        else:
            cards.append(SummaryCard(tr("Last launch"), none, "muted"))
        if install:
            value = "  ·  ".join(b for b in (title_text(install), when(install)) if b)
            cards.append(SummaryCard(tr("Last install"), value, "muted"))
        else:
            cards.append(SummaryCard(tr("Last install"), none, "muted"))
        if failure:
            value = "  ·  ".join(b for b in (title_text(failure), when(failure)) if b)
            cards.append(SummaryCard(tr("Last failure"), value, "danger"))
        else:
            cards.append(SummaryCard(tr("Last failure"), none, "muted"))
        return tuple(cards)

    # ---- one job's log
    @staticmethod
    def log_text(got: JobLog, detail: bool = False) -> LogText:
        """A job's log (information and up, or every line with detail), or another program's output kept with it."""
        notes: list[str] = []
        if not got.attachment:
            if got.missing:
                return LogText((("", "warning", tr("This job's log file is no longer there.")),), "", missing=True)
            rows = tuple(log_row(e) for e in got.entries if detail or e["level"] != "debug")
            hidden = 0 if detail else sum(1 for e in got.entries if e["level"] == "debug")
            if hidden:
                notes.append(
                    plural(
                        "{n} detail line hidden; turn on Show details to see it.",
                        "{n} detail lines hidden; turn on Show details to see them.",
                        hidden,
                    ).format(n=hidden)
                )
            plain = "\n".join(f"{t}  {lvl.upper():7}  {x}" for t, lvl, x in rows)
        else:
            if got.missing:
                return LogText((("", "warning", tr("This output file is no longer there.")),), "", missing=True)
            plain = got.text
            rows = (("", "info", plain),)
        if got.cut:
            notes.insert(0, tr("Only the end of a long file is shown; Open file has all of it."))
        return LogText(rows, plain, " ".join(notes))

    @staticmethod
    def copy_text(log: LogText, for_support: bool = False) -> str:
        """What Copy puts on the clipboard; for support, with the user name and Steam IDs masked."""
        return run_logging.redact(log.plain) if for_support else log.plain

    @staticmethod
    def refusal(e: OperationError) -> Refusal:
        """Why the engine would not take a job back, in words."""
        match e.code:
            case "busy":
                return Refusal(tr("Wait for the current job"), tr("Undo runs as a job of its own."))
            case "gone":
                return Refusal(tr("It cannot be taken back any more"), tr("What it needs is gone."))
            case "game_running":
                return Refusal(tr("Close the game first"), tr("The rebuild's files are in use while it runs."))
            case _:
                return Refusal(tr("It cannot be taken back"), e.message)

    # ---- Undo
    def undo_plan(self, rec: dict) -> UndoPlan:
        """What taking rec back would do (the engine has checked that it can be)."""
        u = dict(rec.get("undo") or {})
        prof = Path(u.get("profile") or "")
        job_id = str(rec.get("id") or "")
        if u.get("type") == "rebuild":
            redo = bool(u.get("redo"))
            title = tr("Redo the rebuild") if redo else tr("Undo the rebuild")
            changes = (
                tr("The rebuild tool's output is swapped with the backup it kept") if u.get("tool_restore") else "",
                tr("The combined parameters are swapped with the ones kept before") if u.get("combined_before") else "",
                (
                    tr("{profile} goes back as it was after the rebuild")
                    if redo
                    else tr("{profile} goes back as it was before the rebuild")
                ).format(profile=prof.name)
                if u.get("profile_before")
                else "",
            )
            return UndoPlan(
                title,
                tuple(c for c in changes if c),
                tr(
                    "Nothing is deleted: each is swapped with its copy, so this can be done again the other way. "
                    "Load order will say the parameters are out of date until you rebuild."
                ),
                title,
                tr("Redoing the rebuild...") if redo else tr("Undoing the rebuild..."),
                u,
                job_id,
                "the rebuild",
            )
        if u.get("type") in kinds.OVERHAUL:
            return self._overhaul_undo_plan(u, prof, job_id, self._facts.in_trash)
        if u.get("type") == "profile-import":
            name = u.get("name") or tr("the profile")
            return UndoPlan(
                tr("Undo the import into {name}").format(name=name),
                (
                    tr("{name} goes back to exactly what it was before the import (a profile it made goes)").format(
                        name=name
                    ),
                    tr(
                        "The mod folders it copied in are removed; files you changed or added since stay, and are listed"
                    ),
                ),
                tr("If {name} changed since, only the imported entries are taken out of it.").format(name=name),
                tr("Undo import"),
                tr("Undoing the import..."),
                u,
                job_id,
                name,
            )
        if u.get("type") == "rename":
            name = u.get("name") or tr("the mod")
            return UndoPlan(
                tr("Undo the rename of {name}").format(name=name),
                (
                    tr("Its folder and the profile's entry go back to the old name"),
                    tr("The mods that load after it, and its attached configs, follow it back"),
                ),
                tr("If something changed since, it is left as it is and you are told why."),
                tr("Undo rename"),
                tr("Undoing the rename..."),
                u,
                job_id,
                name,
            )
        if u.get("type") == "profile-rename":
            name = u.get("name") or tr("the profile")
            return UndoPlan(
                tr("Undo the rename of profile {name}").format(name=name),
                (
                    tr("The profile, its settings, backup copy and version history go back to the old name"),
                    tr("The mods are not moved or copied"),
                ),
                tr("If the profile changed since, it keeps its changes; nothing is deleted."),
                tr("Undo rename"),
                tr("Undoing the rename..."),
                u,
                job_id,
                name,
            )
        if u.get("type") in ("layout-relocate", "layout-rename"):
            moved = u.get("type") == "layout-relocate"
            name = u.get("name") or tr("the folders")
            return UndoPlan(
                tr("Undo the move of the profiles folders") if moved else tr("Undo the rename of the folders"),
                (
                    tr("The profiles and their mods go back to the old Profiles folder")
                    if moved
                    else tr("The folders go back to their old names, and the profiles' paths with them"),
                ),
                tr("If something changed since, nothing is moved and you are told why."),
                tr("Undo move") if moved else tr("Undo rename"),
                tr("Undoing the move...") if moved else tr("Undoing the rename..."),
                u,
                job_id,
                name,
            )
        if u.get("type") == "profile-move-in":
            name = u.get("name") or tr("the profile")
            return UndoPlan(
                tr("Undo the move of profile {name}").format(name=name),
                (
                    tr("The profile, its settings and its mods go back to where they were"),
                    tr("The copies made for the move go to the Recycle Bin"),
                ),
                tr("If the profile changed since, everything is left as it is and you are told why."),
                tr("Undo move"),
                tr("Undoing the move..."),
                u,
                job_id,
                name,
            )
        if u.get("type") in ("folder-rename", "folder-split"):
            name = u.get("name") or tr("the profile")
            split = u.get("type") == "folder-split"
            return UndoPlan(
                (tr("Undo the split of {name}") if split else tr("Undo the folder rename of {name}")).format(name=name),
                (
                    tr("The profiles and their mods go back into the old folder")
                    if split
                    else tr("The folder goes back to its old name"),
                ),
                tr("If a profile changed since, nothing is changed and you are told why."),
                tr("Undo split") if split else tr("Undo rename"),
                tr("Undoing the split...") if split else tr("Undoing the rename..."),
                u,
                job_id,
                name,
            )
        if u.get("type") == "dll-folders":
            name = u.get("name") or tr("the profile")
            return UndoPlan(
                tr("Undo the DLL folders in {name}").format(name=name),
                (tr("The DLLs and their files go back where they were; the new folders go to the Recycle Bin"),),
                tr("If a file in a new folder or the profile changed since, nothing is changed and you are told why."),
                tr("Undo move"),
                tr("Undoing the move..."),
                u,
                job_id,
                name,
            )
        if u.get("type") == "profile-duplicate":
            name = u.get("name") or tr("the copy")
            return UndoPlan(
                tr("Remove the copy {name}").format(name=name),
                (tr("The copy of the profile is removed; the original is not touched"),),
                tr("If the copy was changed since, it stays and you are told why."),
                tr("Undo copy"),
                tr("Removing the copy..."),
                u,
                job_id,
                name,
            )
        if u.get("type") in kinds.OPERATIONS:
            name = u.get("name") or tr("the mod")
            fresh = u.get("type") == "install"
            changes = (
                tr("{profile} goes back to exactly what it was before the install").format(profile=prof.name)
                if fresh
                else tr("{name}'s folder and its entries go back to the version before").format(name=name),
                tr("The files the install added are removed; any you changed since stay, and are listed")
                if fresh
                else tr("The version it replaces is kept aside, with any changes you made to it"),
                tr("The merged mods are rebuilt for it") if u.get("rebuild") and not fresh else "",
            )
            return UndoPlan(
                (tr("Undo the install of {name}") if fresh else tr("Roll {name} back")).format(name=name),
                tuple(c for c in changes if c),
                tr(
                    "Seamless Co-op and your other mods are not touched. If the profile changed since, only {name}'s "
                    "entries are taken out of it."
                ).format(name=name),
                tr("Undo install") if fresh else tr("Roll back"),
                tr("Restoring {name}...").format(name=name),
                u,
                job_id,
                name,
            )
        name = u.get("name") or tr("it")
        changes = (
            tr("Its entry goes back into {profile}, where it was").format(profile=prof.name),
            tr("Its folder comes back from the Recycle Bin") if self._facts.in_trash(u.get("trash")) else "",
            tr("Launch rebuilds the merged mods with it first") if u.get("merged") else "",
        )
        return UndoPlan(
            tr("Restore {name}").format(name=name),
            tuple(c for c in changes if c),
            tr("The profile as it is now is kept in its versions."),
            tr("Restore"),
            tr("Restoring {name}...").format(name=name),
            u,
            job_id,
            name,
        )

    @staticmethod
    def _overhaul_undo_plan(u: dict, prof: Path, job_id: str, in_trash: Callable[[object], bool]) -> UndoPlan:
        """An overhaul installed, updated or removed with the launcher (mods.overhaul_install)."""
        name = u.get("name") or tr("the overhaul")
        kind = u.get("type")
        if kind in ("overhaul-remove", "overhaul-turn-off"):
            back = any(in_trash(t) for t in u.get("trash") or [])
            off = kind == "overhaul-turn-off"
            return UndoPlan(
                (tr("Undo turning {name} off") if off else tr("Restore {name}")).format(name=name),
                tuple(
                    c
                    for c in (
                        (
                            tr("{profile} goes back to exactly what it was before it was turned off")
                            if off
                            else tr("{profile} goes back to exactly what it was before the removal")
                        ).format(profile=prof.name),
                        tr("Its folders come back from the Recycle Bin") if back else "",
                        tr("The launcher's notes on it come back"),
                        tr("Its setup is back, and the ordinary copy made when it was turned off goes") if off else "",
                    )
                    if c
                ),
                tr(
                    "If {profile} changed since the removal, nothing is changed: install {name} again instead. "
                    "Seamless Co-op and your other mods are not touched."
                ).format(profile=prof.name, name=name),
                tr("Undo turn off") if off else tr("Restore"),
                tr("Restoring {name}...").format(name=name),
                u,
                job_id,
                name,
            )
        fresh = kind == "overhaul-install"
        changes = (
            tr("{profile} goes back to exactly what it was before the install").format(profile=prof.name)
            if fresh
            else tr(
                "{name}'s folder, its entries and the launcher's copy of its download go back to the version before"
            ).format(name=name),
            tr(
                "{name}'s folder and the launcher's copy of its download are removed; files you changed or added "
                "since stay, and are listed"
            ).format(name=name)
            if fresh
            else "",
        )
        return UndoPlan(
            (tr("Undo the install of {name}") if fresh else tr("Roll {name} back")).format(name=name),
            tuple(c for c in changes if c),
            tr(
                "Seamless Co-op and your other mods are not touched. If the profile changed since, only {name}'s "
                "entries are taken out of it."
            ).format(name=name),
            tr("Undo install") if fresh else tr("Roll back"),
            tr("Restoring {name}...").format(name=name),
            u,
            job_id,
            name,
        )
