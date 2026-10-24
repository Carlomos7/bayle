"""The shell's words: what the engine says as a code and facts (a toast, a Launch fork, the launcher status line, an
update notice) becomes the sentence the window shows. The engine side (session/shell) has no wording; every string
here goes through tr(). A notice has a level, words and actions, each action a key the window knows how to run;
"Update now" and "Restart now" stay the shell's paths, which check the program's identity before an update is applied.
The Settings page's own words are ui/pages/settings/presenter.py."""

from __future__ import annotations

import time
from dataclasses import dataclass

from bayle.platform.text import tr
from bayle.services.play import TITLE, VERSION
from bayle.work.prompts import Choice, Choose, Question

from bayle_qt.launcher import topbar
from bayle_qt.shell import launch
from bayle_qt.shell import updates as flow
from bayle_qt.shell.facts import Block
from bayle_qt.updater.service import RELEASES_URL


# ----------------------------------------------------------------------------- toasts
def _status_toast(code: str, f: dict) -> tuple[str, str] | None:
    """(title, body) of what a check the user asked for says."""
    if code == "check_failed":
        later = (
            " "
            + tr("The next automatic check is after {time}.").format(
                time=time.strftime("%H:%M", time.localtime(f["retry_at"]))
            )
            if f.get("retry_at")
            else ""
        )
        return tr("Could not check"), f"{f['reason']}.{later}"
    if code == "check_blocked":
        return (
            tr("Not offered again"),
            tr("{version} failed to start here and was undone. A newer release will be offered.").format(
                version=f["version"]
            ),
        )
    if code == "up_to_date":
        return tr("Up to date"), tr("{version} is the newest on the {channel} channel").format(
            version=f["version"], channel=tr("Beta") if f["channel"] == "beta" else tr("Stable")
        )
    if code == "update_available":
        return tr("Update available"), tr("{version} is ready to download in Settings.").format(version=f["version"])
    if code == "updated":
        was = tr(" (was {version})").format(version=f["was"]) if f.get("was") else ""
        return tr("Updated"), tr("{title} {version} is running{was}.").format(
            title=TITLE, version=f["version"], was=was
        )
    if code == "cannot_update":
        return tr("Cannot update now"), say_text(f["why"]["code"], f["why"]["facts"])
    return None


def say_text(code: str, facts: dict | None = None) -> str:
    """The sentence for a toast the engine sent as a code."""
    f = facts or {}
    if code == "text":
        return str(f.get("text") or "")
    if code == "blocked":
        return topbar.block_words(Block(**f))[0]
    if code == "launch_cancelled_rebuild":
        return tr("Launch cancelled: the rebuild finishes first, then the game does not start.")
    if code == "update_game_running":
        return tr("Close {game} first.").format(game=f["game"])
    if code == "update_busy":
        return tr("Wait for the current job.")
    said = _status_toast(code, f)
    if said is None:
        return code
    title, body = said
    return f"{title}: {body}" if body else title


# ----------------------------------------------------------------------------- the Launch flow's forks
def _stale_lines(f: dict) -> tuple[str, str]:
    """(reason, why) of a fork about merged mods that are out of date and cannot be rebuilt now."""
    reason = f["reason"] or tr("The merged mods are out of date")
    cause = f["cause"]
    if cause == "check_error":
        return tr("The merged mods could not be checked"), f["detail"]
    if cause == "blocked":
        return reason, tr("They cannot be rebuilt now: {why}").format(why=f["detail"])
    if cause == "last_failed":
        return reason, tr("The last rebuild with these mods failed; its log is on Activity.")
    if cause == "tool_problem":
        return reason, f["detail"]
    return reason, tr("{tool} has not been allowed to run yet; allow it on the Mods page.").format(tool=f["tool"])


def question_words(q: Question) -> Choose:
    """The fork the Launch flow asked, in words: the same title, lines and verbs for each option, in the order given."""
    f = q.facts
    labels = {
        launch.RETRY: tr("Retry"),
        launch.WITHOUT_BACKUP: tr("Launch without backup"),
        launch.CANCEL: tr("Cancel"),
        launch.REBUILD: tr("Rebuild now"),
        launch.PLAY_ANYWAY: tr("Launch anyway this once"),
        launch.DETAILS: tr("View details"),
        launch.OFFLINE_INSTEAD: tr("Launch Offline instead"),
        launch.ONLINE_ANYWAY: tr("Launch online anyway"),
        launch.GO: tr("Launch Offline"),
    }
    choices = tuple(Choice(o.key, labels[o.key], o.role) for o in q.options)
    stale_warning = tr("Launching anyway uses the previous result. A removed or changed mod may still be in it.")
    if q.code == "backup_failed":
        return Choose(
            tr("Backing up your saves failed"),
            tuple(f["failed"]),
            choices,
            warning=tr("The game has not started: 'Back up saves before launch' is on."),
            safety=tr(
                "Retry tries the backup again. Launch without backup starts the game without a fresh copy of the "
                "saves listed above."
            ),
        )
    if q.code == "stale_rebuild":
        reason = f["reason"] or tr("The merged mods are out of date")
        return Choose(tr("Your merged mods are out of date"), (reason,), choices, warning=stale_warning)
    if q.code == "stale_blocked":
        return Choose(
            tr("Your merged mods are out of date"),
            _stale_lines(f),
            choices,
            warning=stale_warning + " " + tr("Rebuild on the Mods page brings it up to date."),
        )
    if q.code == "rebuild_failed":
        return Choose(
            tr("The merged mods could not be updated"),
            (f["message"] or tr("The rebuild stopped; its log is on Activity."),),
            choices,
            safety=tr(
                "Nothing was replaced: the previous result is still in place, so the game starts with it (without "
                "the latest changes)."
            ),
        )
    if q.code == "online_risk":
        return Choose(
            tr("Launch online with changed game data?"),
            (
                tr(
                    "When you play online, the game sends a fingerprint of its game data to FromSoftware's servers. "
                    "Changed data can be detected. Roundtable starts modded profiles with online play off."
                ),
                tr("This profile has online play on."),
            ),
            choices,
            safety=tr("Launch Offline uses a temporary copy of the profile; your real profile is not changed."),
        )
    if q.code == "offline_confirm":
        bits = [tr("Seamless stays off, so the game uses the standard save")]
        if f["strip_overhaul"]:
            bits.append(tr("The overhaul stays off too"))
        if f["start_steam"]:
            bits.append(tr("Steam is started if it is not running"))
        return Choose(
            tr("Launch Offline"),
            tuple(bits),
            choices,
            safety=tr("A temporary .offline.me3 copy is used; your real profile is not changed."),
        )
    return Choose(q.code, (), choices)


# ----------------------------------------------------------------------------- the launcher status line
def install_kind(kind: str) -> str:
    return {
        "source": tr("running from source"),
        "installed": tr("installed"),
        "portable": tr("portable"),
        "appimage": tr("AppImage"),
    }.get(kind, tr("not installed"))


def launcher_status(st: flow.LauncherStatus) -> tuple[str, str]:
    """The launcher line: version, kind of copy, and what the last check found. Returns (text, tone) with tone muted |
    accent | warning. Empty before the first check."""
    if st.kind == "none":
        return "", "muted"
    if st.kind == "checking":
        return tr("Checking for updates..."), "muted"
    parts = [f"{TITLE} {VERSION}", install_kind(st.install)]
    if st.channel == "beta":
        parts.append(tr("beta channel"))
    tone = "muted"
    if st.kind == "offer":
        parts.append(tr("{version} is available").format(version=st.offer))
        tone = "accent"
    elif st.kind == "failed":
        parts.append(tr("could not check: {reason}").format(reason=st.reason) if st.reason else tr("could not check"))
        tone = "warning"
    elif st.kind == "off":
        parts.append(tr("update checks off"))
    else:
        parts.append(tr("up to date"))
    if st.checked:
        same_day = time.strftime("%Y%m%d", time.localtime(st.checked)) == time.strftime("%Y%m%d")
        stamp = time.strftime("%H:%M" if same_day else "%d %b %H:%M", time.localtime(st.checked))
        parts.append(tr("last checked {when}").format(when=stamp))
    return "  ·  ".join(parts), tone


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
    id: str
    level: str  # info | success | warning | error
    title: str
    body: str
    actions: tuple[NoticeAction, ...] = ()
    closable: bool = True


def _action(a: flow.NoticeAction, f: dict) -> NoticeAction:
    url = a.url
    if a.key == "update":
        return NoticeAction(
            "update", tr("Update now"), True, tr("Checks the signature and checksum, installs it and restarts.")
        )
    if a.key == "download":
        tip = (
            tr("Opens the releases page.")
            if f["signed"] or not f["frozen"]
            else tr("This copy cannot update itself here. Install it from the releases page.")
        )
        return NoticeAction("download", tr("Download"), False, tip, url or RELEASES_URL)
    labels = {
        "notes": (tr("Notes"), tr("Opens the full notes on GitHub.")),
        "skip": (tr("Skip this version"), tr("Stops mentioning this version. The next one still shows.")),
        "restart": (tr("Restart now"), ""),
        "later": (tr("Later"), tr("The download is kept and this notice returns next start.")),
        "again": (tr("Try again"), ""),
        "releases": (tr("Releases"), ""),
        "details": (tr("Details"), ""),
    }
    label, tip = labels[a.key]
    return NoticeAction(a.key, label, a.key == "restart", tip, url)


def notice(n: flow.UpdateNotice) -> UpdateNotice:
    """An update notice in words."""
    f, code = n.facts, n.code
    if code == "offer":
        summary = f["summary"]
        how = (
            tr("One click, then a restart. Your settings stay.")
            if f["apply"]
            else tr("Get it from the releases page. Your settings stay.")
        )
        kind = tr("pre-release") + " " if f["prerelease"] else ""
        title = tr("{title} {kind}{version} is available").format(title=TITLE, kind=kind, version=f["version"])
        body = f"{summary}\n\n{how}" if summary else how
    elif code == "downloading":
        title = tr("Downloading {title} {version}").format(title=TITLE, version=f["version"])
        body = f["progress"] or tr("Starting...")
    elif code == "update_failed":
        title, body = tr("Update not applied"), f["error"]
    elif code == "ready":
        kind = tr("an update of") if f["delta"] else tr("the full")
        title = tr("{title} {version} is ready").format(title=TITLE, version=f["version"])
        body = tr(
            "Signature and {kind} package checked. Restart to finish. If it does not start, this version comes back."
        ).format(kind=kind)
    elif code == "rolled_back":
        title = tr("{title} {version} did not start; this version was put back").format(
            title=TITLE, version=f["version"]
        )
        body = tr(
            "{version} {why}. It is not offered again; a newer release will be. Your settings and data were not "
            "touched."
        ).format(version=f["version"], why=f["error"] or tr("did not start"))
    elif code == "not_finished":
        title = tr("The update to {title} {version} did not finish").format(title=TITLE, version=f["version"])
        body = f["error"]
    elif code == "advisory":
        msg = f["message"] or tr("This version has a known problem.")
        target = (
            " " + tr("Update to {version}.").format(version=f["offer"])
            if f["offer"]
            else " " + tr("Update to the newest release.")
        )
        title, body = tr("{title} {version} should be updated").format(title=TITLE, version=VERSION), msg + target
    elif code == "migration_waiting":
        title, body = tr("The old Bayle is still open"), f["reason"]
    elif code == "migration_failed":
        title, body = tr("The old install could not be removed"), f["reason"]
    else:  # migration_done
        lines = [
            tr("The old install ({old}) was removed; settings, logs and backups stayed where they were.").format(
                old=f["old_version"] or "Inno Setup"
            ),
            tr("Start menu shortcut updated") + (tr(" and desktop shortcut recreated.") if f["had_desktop"] else "."),
        ]
        if f["steam_changed"]:
            lines.append(
                tr("Steam shortcuts now start this copy: {names}.").format(names=", ".join(f["steam_changed"]))
            )
        if f["steam_pending"]:
            lines.append(tr("Close Steam, then Settings > Steam shortcut > Point Steam shortcuts here."))
        title, body = tr("Moved to the new installer"), "\n".join(lines)
    return UpdateNotice(n.id, n.level, title, body, tuple(_action(a, f) for a in n.actions), n.closable)


def update_state(state: dict) -> dict:
    """UpdateFlow.state() in words: what the Settings page reads (line, tone, checking, notices)."""
    line, tone = launcher_status(state["status"])
    return {
        "line": line,
        "tone": tone,
        "checking": state["checking"],
        "notices": [notice(n) for n in state["notices"]],
    }
