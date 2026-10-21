"""The Settings page's presenter (technical specification §8.10, Settings; launcher-wide only): the words and rules
of the page, in plain Python with no Qt. The Widgets Settings page (ui/pages/tools) and the Qt Quick one
(adapter.py) both render from here, so a sentence exists once.

It holds the launcher status line, the me3 line, the switch table, and the update notices (offer, download, ready,
outcome, advisory, migration) as data: a notice has a level, words and actions, each action a key the window knows
how to run. Nothing here downloads or installs anything; "Update now" and "Restart now" stay the window's paths
(the Settings page: _start_update, _restart_updated), which check the program's identity before an update is applied.
Every string goes through tr()."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.config.settings import FROZEN, appimage, is_installed, is_portable
from roundtable_souls.services.play import TITLE, VERSION
from roundtable_souls.services.updates import RELEASES_URL
from roundtable_souls.ui.text import tr
from roundtable_souls.updates import apply as updates
from roundtable_souls.updates import feed

ME3_RELEASES_URL = "https://github.com/garyttierney/me3/releases"
LICENCE_FILES = ("LICENSE", "THIRD_PARTY_NOTICES.md")
GITHUB_BLOB = RELEASES_URL.removesuffix("/releases") + "/blob"  # + /v<version>/<file>


OPEN_WINDOW_TEXT = tr("Open new Settings window")
OPEN_WINDOW_TIP = tr("The new Settings page in a window of its own. This page stays until the new window replaces it.")


# ----------------------------------------------------------------------------- the switches
@dataclass(frozen=True)
class SwitchSpec:
    key: str  # the settings key (play_repair_after is the game's own, see play.repair_key)
    title: str
    blurb: str
    help: str
    group: str  # launch | updates | me3 | offline


def repair_blurb(game_key: str) -> str:
    """The Repair saves line, per game (game model, 2026-10-20)."""
    if game_key == "nightreign":
        return tr("Re-signs the save's encrypted sections after quitting. Leave it on.")
    return tr("Only save editors need this. The game never reads this part of the save back.")


def switches(overhaul_text: str = "", game_key: str = "eldenring") -> tuple[SwitchSpec, ...]:
    """Every switch of the page, in the order it is shown. overhaul_text is the overhaul switch's sentence for the
    game (empty when the game has no overhaul the launcher can install; the page then hides that row)."""
    return (
        SwitchSpec(
            "play_update_merge",
            tr("Rebuild merged mods automatically before launch"),
            tr(
                "When mods, their load order or the game changed, Launching rebuilds the merged ones first (combined "
                "parameters, and a mod's own rebuild tool such as the overhaul's), then starts the game."
            ),
            tr(
                "Off: Play asks first (rebuild, or play this once with the previous result); a Steam shortcut "
                "does not start the game and says why. A failed rebuild keeps the previous result and asks before "
                "starting. After an automatic rebuild only the newest 3 of a rebuild tool's backups are kept; older "
                "ones go to the Recycle Bin."
            ),
            "launch",
        ),
        SwitchSpec(
            "build_merges",
            tr("Build the overhaul in the launcher (preview)"),
            tr(
                "For a mod the launcher has a config for (the overhaul LITE 0.1.33), a rebuild merges it from "
                "its own download instead of running its installer: the launcher merges its animations, effects, "
                "menu text, grace menu and parameters itself, and runs nothing from the download."
            ),
            tr(
                "Still being compared with what its installer makes, and not yet checked in game: a preview. Your "
                "profile is never rewritten, OverhaulPrototype.ini keeps your values (a new version only adds its new "
                "settings), and one previous build is kept in .roundtable-build for Undo rebuild instead of a full "
                "backup on every run. Other versions still use their own installer. Off: the installer runs, as "
                "before."
            ),
            "launch",
        ),
        SwitchSpec(
            "overhaul_install",
            tr("Install overhauls with the launcher (preview)"),
            overhaul_text,
            tr(
                "Every change is shown before it happens, and each install or removal can be undone from Activity. "
                "The launcher keeps a copy of the download and its notes in its own folder in me3's profiles "
                "folder; the overhaul's own folder stays beside your profile. An overhaul its own installer set up "
                "isn't changed: remove it first. Off: the button is hidden; nothing installed with it changes."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_boot_boost",
            tr("Boot boost"),
            tr(
                "me3 keeps a decrypted copy of the game's archive indexes so the game starts faster. If DLC areas "
                "or items are sometimes missing, try turning this off."
            ),
            tr("Turn off only if a mod misbehaves with the cache; me3 passes --no-boot-boost."),
            "launch",
        ),
        SwitchSpec(
            "play_show_logos",
            tr("Show intro logos"),
            tr("Show the publisher logos me3 skips by default."),
            tr("Passes --show-logos to me3."),
            "launch",
        ),
        SwitchSpec(
            "play_diagnostics",
            tr("me3 diagnostics"),
            tr("Ask me3 for extra diagnostics on this launch (slower start, bigger log)."),
            tr("Passes --diagnostics; me3's output is kept with that launch in the logs folder."),
            "launch",
        ),
        SwitchSpec(
            "play_backup_before",
            tr("Back up saves before launch"),
            tr("A backup of every save before each session, listed under Backups on the Saves page."),
            tr(
                "Off by default: the game keeps its own .bak, and each repair makes a copy anyway. Turn it on for a "
                "copy before every session. When a backup fails, the game waits: you choose Retry, Launch without "
                "backup or Cancel (a Steam shortcut stops unless it has --allow-without-backup)."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_clear_before",
            tr("Clear leftover processes before launch"),
            tr("Closes copies of the game that are stuck in the background so Steam agrees to start it."),
            tr(
                "A leftover game process is a copy of the game with no window. Steam refuses to launch while one exists."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_repair_after",
            tr("Repair saves after quitting"),
            repair_blurb(game_key),
            tr(
                "Each game keeps its own setting. Elden Ring copies regulation.bin into the save so editors can "
                "read it; Nightreign never writes Game\\regulation.bin into the save (that file is a different "
                "encoding)."
            ),
            "launch",
        ),
        SwitchSpec(
            "play_clear_after",
            tr("Clear leftover processes after quitting"),
            tr("Closes stuck copies of the game so Discord and Steam stop showing it as running."),
            tr("Needs admin once. Turn it off if you prefer to handle processes yourself."),
            "launch",
        ),
        SwitchSpec(
            "warn_dead_shells",
            tr("Warn about leftover processes"),
            tr("A bar at the top of the window when a leftover game process is found."),
            tr("Clearing them by hand still works with the warning off."),
            "launch",
        ),
        SwitchSpec(
            "check_launcher_updates",
            tr("Check for updates on start"),
            tr("At most once an hour, from this project's GitHub releases. A notice only; you choose when to install."),
            tr(
                "Update now downloads the release, checks its signature and checksum, installs it and restarts. "
                "Skip hides one version."
            ),
            "updates",
        ),
        SwitchSpec(
            "check_me3_updates",
            tr("Check for me3 updates"),
            tr("Once a day, from me3's GitHub releases. A notice only; nothing is installed."),
            tr("Roundtable Souls never replaces me3 itself: the overhaul profiles ship their own copy."),
            "me3",
        ),
        SwitchSpec(
            "offline_strip_overhaul",
            tr("Skip the overhaul too"),
            tr("Leave the overhaul (an Elden Ring mod) off for this launch."),
            tr("Turns the overhaul packages and natives off in a temporary copy. Your real profile is not changed."),
            "offline",
        ),
        SwitchSpec(
            "offline_start_steam",
            tr("Start Steam if needed"),
            tr("Open Steam before launch if it is not running."),
            tr("Turn this off if Steam is already open. Seamless still stays off."),
            "offline",
        ),
        SwitchSpec(
            "offline_skip_confirm",
            tr("Skip the confirmation"),
            tr("Go straight to launch next time."),
            tr("Stops the Launch Offline prompt. You can turn this back off here."),
            "offline",
        ),
    )


def switch(key: str, game_key: str = "eldenring") -> SwitchSpec:
    return next(s for s in switches(game_key=game_key) if s.key == key)


OFFLINE_TITLE = tr("Offline play")
OFFLINE_BLURB = tr(
    "Starts this profile without Seamless Co-op and with online play off, so the game uses its standard save (.sl2) "
    "instead of Seamless's (.co2)."
)
OFFLINE_HELP = tr(
    "Steam still needs to be running; pick Start in Offline Mode if it asks. Co-op needs Steam online. A me3 "
    "savefile setting or Seamless's ersc_settings.ini can change the save names; the launcher follows them."
)


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


@dataclass(frozen=True)
class Me3Line:
    text: str
    tone: str  # muted | accent
    path: str
    folder: str  # "" when me3's folder is unknown
    logs: str
    profiles: str
    error: bool


def me3_line(f: dict) -> Me3Line:
    """The me3 line and the folders it can open, from services.mods.me3_facts."""
    if f.get("error"):
        return Me3Line(f"me3: {f['error']}", "muted", "", "", "", "", True)
    v = f.get("version")
    latest = (f.get("latest") or {}).get("version")
    text = f"me3 {v}" if v else tr("me3 version unknown")
    if f.get("update") and latest:
        text += "  ·  " + tr("{version} is available").format(version=latest)
    elif v and latest:
        text += "  ·  " + tr("up to date")
    info = f.get("info") or {}
    where = info.get("install_prefix") or (str(Path(f["path"]).parent) if f.get("path") else "")
    return Me3Line(
        text,
        "accent" if f.get("update") else "muted",
        f.get("path") or "",
        where if where and Path(where).is_dir() else "",
        info.get("logs_dir") or "",
        info.get("profile_dir") or "",
        False,
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
            tr("Download it, check its signature and checksum, install it and restart."),
        )
    else:
        signed = updates.can_self_update(info)
        tip = (
            tr("Open the releases page in the browser.")
            if signed or not frozen
            else tr(
                "This copy cannot update itself (or the release has no signed feed): install it from the releases page."
            )
        )
        go = NoticeAction("download", tr("Download"), False, tip, info.get("url") or RELEASES_URL)
    notes = NoticeAction(
        "notes", tr("Notes"), False, tr("The full release notes, on GitHub."), info.get("url") or RELEASES_URL
    )
    skip = NoticeAction(
        "skip", tr("Skip this version"), False, tr("Do not mention this version again; the next one will show.")
    )
    summary = feed.release_notes(info.get("notes", ""), lines=4)
    how = (
        tr("One click, then a restart. Settings stay.")
        if apply_ok
        else tr("Get it from the releases page. Settings stay.")
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
            "Checked: signature and {kind} package. Restart to finish; if it does not start, this version comes "
            "back by itself."
        ).format(kind=kind),
        (
            NoticeAction("restart", tr("Restart now"), True),
            NoticeAction(
                "later",
                tr("Later"),
                False,
                tr("Keep using this version; the download is kept and the notice returns next time."),
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
        return UpdateNotice(
            "migration", "warning", tr("The old Roundtable Souls is still open"), record.get("reason", "")
        )
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


def data_location() -> str:
    """Where this copy keeps its data, in words."""
    return updates.data_location_text()


# ----------------------------------------------------------------------------- about
def licence_url(file: str) -> str:
    """A licence file on GitHub at the tag of the running version (D8)."""
    return f"{GITHUB_BLOB}/v{VERSION}/{file}"
