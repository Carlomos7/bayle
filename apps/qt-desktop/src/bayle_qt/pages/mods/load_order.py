"""The Mods page's Load order panel (technical specification §8.10): the mod that must stay last and Fix order, the
files two packages both ship (who wins, what is combined), and the entries me3 would refuse. Plain Python, every
string through tr(); it reads one Load order scan (mods.conflicts.overview)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from bayle.mods import conflicts as mod_overview

from bayle_qt.text import plural, tr

SHOWN_CLASHES = 12  # files listed before "Show all"
LOST = ("replaced", "unreached")  # a loser's copy of the file does not reach the game: a clash


@dataclass(frozen=True)
class StaysLast:
    name: str
    text: str
    can_fix: bool
    problem: str


@dataclass(frozen=True)
class ClashFile:
    path: str
    winner: str
    losers: str  # "flora (replaced), birds (combined)"
    lost: bool  # a loser's copy does not reach the game


@dataclass(frozen=True)
class Refused:
    name: str
    why: str


@dataclass(frozen=True)
class LoadOrderPanel:
    title: str
    stays_last: StaysLast | None
    clashes: tuple[ClashFile, ...]
    clash_total: int
    clash_note: str
    refused: tuple[Refused, ...]
    error: str = ""


def clash_counts(scan: dict | None) -> dict[str, int]:
    """Per package id: how many of the files it ships lose to another package's copy (the row's Clash tag)."""
    out: dict[str, int] = {}
    for conflict in (scan or {}).get("overlaps", {}).get("conflicts") or []:
        for loser in conflict.get("losers") or []:
            if loser.get("outcome") in LOST:
                out[str(loser["id"])] = out.get(str(loser["id"]), 0) + 1
    return out


def lost_files(scan: dict | None) -> int:
    """Files whose losing copy does not reach the game (the header pill's "N files clash")."""
    return sum(
        1
        for conflict in (scan or {}).get("overlaps", {}).get("conflicts") or []
        if any(loser.get("outcome") in LOST for loser in conflict.get("losers") or [])
    )


def _names(names: list[str], most: int = 4) -> str:
    shown = ", ".join(names[:most])
    return shown if len(names) <= most else tr("{names} and {n} more").format(names=shown, n=len(names) - most)


def stays_last(status: dict | None) -> StaysLast | None:
    if not status:
        return None
    late, name = list(status.get("late") or []), status["name"]
    if late:
        text = plural(
            "{names} loads after {mod}, which must stay last: it replaces {mod}'s files.",
            "{names} load after {mod}, which must stay last: they replace {mod}'s files.",
            len(late),
        ).format(names=_names(late), mod=name)
    else:
        text = tr("{mod} loads last, as it must.").format(mod=name)
    problem = status.get("problem") or ""
    return StaysLast(name, text, bool(status.get("can_fix")) and bool(late) and not problem, problem)


def panel(scan: dict | None, show_all: bool = False) -> LoadOrderPanel:
    """The panel from one scan (None before the first scan lands)."""
    scan = scan or {}
    conflicts = scan.get("overlaps", {}).get("conflicts") or []
    files = []
    for conflict in conflicts:
        losers = conflict.get("losers") or []
        files.append(
            ClashFile(
                path=str(conflict.get("path") or ""),
                winner=str(conflict.get("winner") or ""),
                losers=", ".join(
                    f"{loser['id']} ({tr(mod_overview.OUTCOME_TEXT.get(loser.get('outcome'), loser.get('outcome') or ''))})"
                    for loser in losers
                ),
                lost=any(loser.get("outcome") in LOST for loser in losers),
            )
        )
    files.sort(key=lambda f: (not f.lost, f.path.lower()))
    shown = files if show_all else files[:SHOWN_CLASHES]
    if not files:
        note = tr("No two packages ship the same file.")
    else:
        lost = sum(1 for f in files if f.lost)
        note = plural(
            "{n} file is shipped by two packages", "{n} files are shipped by two packages", len(files)
        ).format(n=len(files))
        if lost:
            note += tr("; {n} of them reach the game from one package only").format(n=lost)
        note += "."
    refused = tuple(
        Refused(str(p["name"]), "; ".join(str(x) for x in p.get("problems") or [])) for p in scan.get("problems") or []
    )
    error = str((scan.get("scan") or {}).get("error") or "")
    return LoadOrderPanel(
        title=tr("Load order"),
        stays_last=stays_last(scan.get("stay_last")),
        clashes=tuple(shown),
        clash_total=len(files),
        clash_note=note,
        refused=refused,
        error=tr("The files could not be compared: {why}").format(why=error) if error else "",
    )


def shown(panel: LoadOrderPanel, show_all: bool) -> LoadOrderPanel:
    """The panel with the clash list cut to SHOWN_CLASHES unless show_all (the snapshot carries every clash)."""
    return panel if show_all else replace(panel, clashes=panel.clashes[:SHOWN_CLASHES])


def same_profile(scan: dict | None, profile) -> bool:
    """The scan is for this profile (an answer for one no longer shown is dropped)."""
    from bayle.mods import checks

    return bool(scan) and checks.same_folder(Path(scan.get("profile") or ""), Path(profile))
