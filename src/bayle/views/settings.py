"""What the shell and the Qt Settings page share about the launcher itself: the launcher status line, the update
notices (offer, download, ready, outcome, advisory, migration) as data, and the check toast, in plain Python with no
Qt. A notice has a level, words and actions, each action a key the window knows how to run. Nothing here downloads or
installs anything; "Update now" and "Restart now" stay the window's paths, which check the program's identity before
an update is applied. The Settings page's own words are ui/pages/settings/presenter.py. Every string goes through
tr()."""

from __future__ import annotations

import time
from dataclasses import dataclass

from bayle.config.settings import FROZEN, appimage, is_installed, is_portable
from bayle.platform.text import tr
from bayle.services.play import TITLE, VERSION
from bayle.services.updates import RELEASES_URL
from bayle.updates import apply as updates
from bayle.updates import feed


# ----------------------------------------------------------------------------- the status lines
def install_kind() -> str:
    if not FROZEN:
        return tr("running from source")
    if is_installed():
        return tr("installed")
    if is_portable():
        return tr("portable")
    return tr("AppImage") if appimage() else tr("not installed")


def launcher_status(check, channel: str) -> tuple[str, str]:
    """The launcher line: version, kind of copy, and what the last check found (never 'up to date' after a check
    that failed). Returns (text, tone) with tone muted | accent | warning."""
    parts = [f"{TITLE} {VERSION}", install_kind()]
    if channel == "beta":
        parts.append(tr("beta channel"))
    tone = "muted"
    if check.offer:
        parts.append(tr("{version} is available").format(version=check.offer["version"]))
        tone = "accent"
    elif check.failed or check.status == "waiting":
        parts.append(
            tr("could not check: {reason}").format(reason=check.reason) if check.reason else tr("could not check")
        )
        tone = "warning"
    elif check.status == "off":
        parts.append(tr("update checks off"))
    else:
        parts.append(tr("up to date"))
    if check.checked:
        same_day = time.strftime("%Y%m%d", time.localtime(check.checked)) == time.strftime("%Y%m%d")
        stamp = time.strftime("%H:%M" if same_day else "%d %b %H:%M", time.localtime(check.checked))
        parts.append(tr("last checked {when}").format(when=stamp))
    return "  ·  ".join(parts), tone


def check_toast(check, channel: str = "stable") -> tuple[str, str, str]:
    """What a check the user asked for says: (title, body, kind) with kind error | info."""
    if check.failed:
        later = (
            " "
            + tr("The next automatic check is after {time}.").format(
                time=time.strftime("%H:%M", time.localtime(check.retry_at))
            )
            if check.retry_at
            else ""
        )
        return tr("Could not check"), f"{check.reason}.{later}", "error"
    if check.blocked:
        return (
            tr("Not offered again"),
            tr("{version} failed to start here and was undone. A newer release will be offered.").format(
                version=check.blocked
            ),
            "info",
        )
    if not check.offer:
        return (
            tr("Up to date"),
            tr("{version} is the newest on the {channel} channel").format(
                version=VERSION, channel=tr("Beta") if channel == "beta" else tr("Stable")
            ),
            "info",
        )
    return (
        tr("Update available"),
        tr("{version} is ready to download in Settings.").format(version=check.offer["version"]),
        "info",
    )


# ----------------------------------------------------------------------------- the update notices
@dataclass(frozen=True)
class NoticeAction:
    """key: what the window runs (update | download | notes | skip | restart | later | again | releases | details);
    url: for the keys that open a page."""

    key: str
    label: str
    primary: bool = False
    tip: str = ""
    url: str = ""


@dataclass(frozen=True)
class UpdateNotice:
    id: str  # flow | advisory | outcome | migration: a new notice with the same id replaces the old one
    level: str  # info | success | warning | error
    title: str
    body: str
    actions: tuple[NoticeAction, ...] = ()
    closable: bool = True


def can_apply(info: dict, frozen: bool | None = None) -> bool:
    """Whether Update now is offered: a packaged copy and a release with a signed feed. From source, or with an
    unsigned release, the only way is the releases page. frozen: whether this is a packaged build (default: it is
    asked of config.settings)."""
    return bool((FROZEN if frozen is None else frozen) and updates.can_self_update(info))


def cannot_update(game_running: bool, game_name: str, busy: bool, busy_reason: str) -> str:
    """Why the program cannot be replaced now, or ''."""
    if game_running:
        return tr("Close {game} first.").format(game=game_name)
    if busy:
        return tr("Wait for the current job.")
    return busy_reason


def offer_notice(info: dict, frozen: bool | None = None) -> UpdateNotice:
    version = info["version"]
    frozen = FROZEN if frozen is None else frozen
    apply_ok = can_apply(info, frozen)
    if apply_ok:
        go = NoticeAction(
            "update",
            tr("Update now"),
            True,
            tr("Checks the signature and checksum, installs it and restarts."),
        )
    else:
        signed = updates.can_self_update(info)
        tip = (
            tr("Opens the releases page.")
            if signed or not frozen
            else tr("This copy cannot update itself here. Install it from the releases page.")
        )
        go = NoticeAction("download", tr("Download"), False, tip, info.get("url") or RELEASES_URL)
    notes = NoticeAction(
        "notes", tr("Notes"), False, tr("Opens the full notes on GitHub."), info.get("url") or RELEASES_URL
    )
    skip = NoticeAction(
        "skip", tr("Skip this version"), False, tr("Stops mentioning this version. The next one still shows.")
    )
    summary = feed.release_notes(info.get("notes", ""), lines=4)
    how = (
        tr("One click, then a restart. Your settings stay.")
        if apply_ok
        else tr("Get it from the releases page. Your settings stay.")
    )
    kind = tr("pre-release") + " " if info.get("prerelease") else ""
    return UpdateNotice(
        "flow",
        "info",
        tr("{title} {kind}{version} is available").format(title=TITLE, kind=kind, version=version),
        f"{summary}\n\n{how}" if summary else how,
        (go, notes, skip),
    )


def downloading_notice(version: str, progress: str = "") -> UpdateNotice:
    return UpdateNotice(
        "flow",
        "info",
        tr("Downloading {title} {version}").format(title=TITLE, version=version),
        progress or tr("Starting..."),
        closable=False,
    )


def failed_notice(error: str) -> UpdateNotice:
    return UpdateNotice("flow", "error", tr("Update not applied"), error)


def ready_notice(version: str, delta: bool) -> UpdateNotice:
    kind = tr("an update of") if delta else tr("the full")
    return UpdateNotice(
        "flow",
        "success",
        tr("{title} {version} is ready").format(title=TITLE, version=version),
        tr(
            "Signature and {kind} package checked. Restart to finish. If it does not start, this version comes back."
        ).format(kind=kind),
        (
            NoticeAction("restart", tr("Restart now"), True),
            NoticeAction(
                "later",
                tr("Later"),
                False,
                tr("The download is kept and this notice returns next start."),
            ),
        ),
    )


def outcome_notice(result: dict) -> UpdateNotice | None:
    """How the last update went; None when it went well (the window says so in a toast, see outcome_ok_text)."""
    status, version = result.get("status"), result.get("version", "")
    if status == "ok":
        return None
    releases = NoticeAction("releases", tr("Releases"), False, "", RELEASES_URL)
    if status == "rolled_back":
        return UpdateNotice(
            "outcome",
            "error",
            tr("{title} {version} did not start; this version was put back").format(title=TITLE, version=version),
            tr(
                "{version} {why}. It is not offered again; a newer release will be. Your settings and data were not "
                "touched."
            ).format(version=version, why=result.get("error") or tr("did not start")),
            (releases,),
        )
    return UpdateNotice(
        "outcome",
        "error",
        tr("The update to {title} {version} did not finish").format(title=TITLE, version=version),
        result.get("error") or "",
        (NoticeAction("again", tr("Try again")), releases),
    )


def outcome_ok_text(result: dict) -> tuple[str, str]:
    was = tr(" (was {version})").format(version=result["from"]) if result.get("from") else ""
    return tr("Updated"), tr("{title} {version} is running{was}.").format(
        title=TITLE, version=result.get("version", ""), was=was
    )


def advisory_notice(advisory: dict, offer: dict | None) -> UpdateNotice:
    """The project asks everyone below a version to update (advisory.json on main). A notice only."""
    msg = advisory.get("message") or tr("This version has a known problem.")
    target = (
        " " + tr("Update to {version}.").format(version=offer["version"])
        if offer
        else " " + tr("Update to the newest release.")
    )
    return UpdateNotice(
        "advisory",
        "warning",
        tr("{title} {version} should be updated").format(title=TITLE, version=VERSION),
        msg + target,
        (NoticeAction("details", tr("Details"), False, "", advisory.get("url") or RELEASES_URL),),
    )


def migration_notice(record: dict | None) -> UpdateNotice | None:
    """The move from the old (Inno Setup) install, one notice per state."""
    if not record:
        return None
    status = record.get("status")
    if status == "waiting":
        return UpdateNotice("migration", "warning", tr("The old Bayle is still open"), record.get("reason", ""))
    if status == "failed":
        return UpdateNotice("migration", "error", tr("The old install could not be removed"), record.get("reason", ""))
    if status in ("done", "steam_pending"):
        steam = record.get("steam_changed") or []
        lines = [
            tr("The old install ({old}) was removed; settings, logs and backups stayed where they were.").format(
                old=record.get("old_version") or "Inno Setup"
            ),
            tr("Start menu shortcut updated")
            + (tr(" and desktop shortcut recreated.") if record.get("had_desktop") else "."),
        ]
        if steam:
            lines.append(tr("Steam shortcuts now start this copy: {names}.").format(names=", ".join(steam)))
        if status == "steam_pending":
            lines.append(tr("Close Steam, then Settings > Steam shortcut > Point Steam shortcuts here."))
        return UpdateNotice(
            "migration",
            "success" if status == "done" else "warning",
            tr("Moved to the new installer"),
            "\n".join(lines),
        )
    return None
