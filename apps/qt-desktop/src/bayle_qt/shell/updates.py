"""The launcher's own update flow, as the shell runs it: looks for a release on a schedule or when asked, keeps the
launcher status and the notices (offer, download progress, ready, failed, advisory, how the last update went, the move
from the old installer) that the Settings page shows, downloads and checks an offer, and hands a prepared package to the
host to apply on restart.

The page never calls the updater: its notice buttons come back through notice_action(), which runs the same checks
as before (the game and jobs stopped, the program's identity, the prepared package). Nothing here has words: a status,
a notice and a toast are a code and facts, and the window words them (ui/launcher/presenter.py)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field

from bayle.config.app_paths import FROZEN, appimage, is_installed, is_portable
from bayle.config.settings import LauncherSettings
from bayle.services.play import VERSION

from bayle_qt.shell.background import Background
from bayle_qt.updater import apply as updates
from bayle_qt.updater import feed
from bayle_qt.updater.service import RELEASES_URL


@dataclass(frozen=True)
class Say:
    """Something to tell the player: a code the window words, and the facts the words need."""

    code: str
    facts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class LauncherStatus:
    """The launcher line. kind: none | checking | offer | failed | off | current."""

    kind: str = "none"
    channel: str = "stable"
    install: str = ""  # source | installed | portable | appimage | not_installed
    offer: str = ""  # the offered version
    reason: str = ""
    checked: float = 0.0  # when the last check ran (epoch seconds), 0: never


@dataclass(frozen=True)
class NoticeAction:
    """key: what the window runs (update | download | notes | skip | restart | later | again | releases | details);
    url: for the keys that open a page."""

    key: str
    url: str = ""


@dataclass(frozen=True)
class UpdateNotice:
    id: str  # flow | advisory | outcome | migration: a new notice with the same id replaces the old one
    level: str  # info | success | warning | error
    code: str
    facts: dict = field(default_factory=dict)
    actions: tuple[NoticeAction, ...] = ()
    closable: bool = True


def install_kind() -> str:
    if not FROZEN:
        return "source"
    if is_installed():
        return "installed"
    if is_portable():
        return "portable"
    return "appimage" if appimage() else "not_installed"


def launcher_status(check, channel: str) -> LauncherStatus:
    """What the last check found (never 'up to date' after a check that failed)."""
    if check.offer:
        kind = "offer"
    elif check.failed or check.status == "waiting":
        kind = "failed"
    elif check.status == "off":
        kind = "off"
    else:
        kind = "current"
    return LauncherStatus(
        kind, channel, install_kind(), (check.offer or {}).get("version", ""), check.reason or "", check.checked or 0.0
    )


def check_say(check, channel: str = "stable") -> tuple[Say, str]:
    """What a check the user asked for says, and its kind (error | info)."""
    if check.failed:
        return Say("check_failed", {"reason": check.reason, "retry_at": check.retry_at or 0}), "error"
    if check.blocked:
        return Say("check_blocked", {"version": check.blocked}), "info"
    if not check.offer:
        return Say("up_to_date", {"version": VERSION, "channel": channel}), "info"
    return Say("update_available", {"version": check.offer["version"]}), "info"


def can_apply(info: dict, frozen: bool | None = None) -> bool:
    """Whether Update now is offered: a packaged copy and a release with a signed feed. From source, or with an
    unsigned release, the only way is the releases page. frozen: whether this is a packaged build (default: it is
    asked of config.settings)."""
    return bool((FROZEN if frozen is None else frozen) and updates.can_self_update(info))


def offer_notice(info: dict, frozen: bool | None = None) -> UpdateNotice:
    frozen = FROZEN if frozen is None else frozen
    apply_ok = can_apply(info, frozen)
    page = info.get("url") or RELEASES_URL
    go = NoticeAction("update") if apply_ok else NoticeAction("download", page)
    facts = {
        "version": info["version"],
        "prerelease": bool(info.get("prerelease")),
        "apply": apply_ok,
        "signed": bool(updates.can_self_update(info)),
        "frozen": frozen,
        "summary": feed.release_notes(info.get("notes", ""), lines=4),
    }
    return UpdateNotice("flow", "info", "offer", facts, (go, NoticeAction("notes", page), NoticeAction("skip")))


def downloading_notice(version: str, progress: str = "") -> UpdateNotice:
    return UpdateNotice("flow", "info", "downloading", {"version": version, "progress": progress}, closable=False)


def failed_notice(error: str) -> UpdateNotice:
    return UpdateNotice("flow", "error", "update_failed", {"error": error})


def ready_notice(version: str, delta: bool) -> UpdateNotice:
    actions = (NoticeAction("restart"), NoticeAction("later"))
    return UpdateNotice("flow", "success", "ready", {"version": version, "delta": delta}, actions)


def outcome_notice(result: dict) -> UpdateNotice | None:
    """How the last update went; None when it went well (the window says so in a toast: the `updated` code)."""
    status, version = result.get("status"), result.get("version", "")
    if status == "ok":
        return None
    releases = NoticeAction("releases", RELEASES_URL)
    facts = {"version": version, "error": result.get("error") or ""}
    if status == "rolled_back":
        return UpdateNotice("outcome", "error", "rolled_back", facts, (releases,))
    return UpdateNotice("outcome", "error", "not_finished", facts, (NoticeAction("again"), releases))


def advisory_notice(advisory: dict, offer: dict | None) -> UpdateNotice:
    """The project asks everyone below a version to update (advisory.json on main). A notice only."""
    facts = {"message": advisory.get("message") or "", "offer": offer["version"] if offer else ""}
    details = NoticeAction("details", advisory.get("url") or RELEASES_URL)
    return UpdateNotice("advisory", "warning", "advisory", facts, (details,))


def migration_notice(record: dict | None) -> UpdateNotice | None:
    """The move from the old (Inno Setup) install, one notice per state."""
    if not record:
        return None
    status = record.get("status")
    if status == "waiting":
        return UpdateNotice("migration", "warning", "migration_waiting", {"reason": record.get("reason", "")})
    if status == "failed":
        return UpdateNotice("migration", "error", "migration_failed", {"reason": record.get("reason", "")})
    if status in ("done", "steam_pending"):
        facts = {
            "old_version": record.get("old_version") or "",
            "had_desktop": bool(record.get("had_desktop")),
            "steam_changed": list(record.get("steam_changed") or []),
            "steam_pending": status == "steam_pending",
        }
        return UpdateNotice("migration", "success" if status == "done" else "warning", "migration_done", facts)
    return None


def cannot_update(game_running: bool, game_name: str, busy: bool, busy_reason: str) -> Say | None:
    """Why the program cannot be replaced now, or None."""
    if game_running:
        return Say("update_game_running", {"game": game_name})
    if busy:
        return Say("update_busy")
    return Say("text", {"text": busy_reason}) if busy_reason else None


class UpdateFlow:
    def __init__(
        self,
        jobs: Background,
        settings: Callable[[], LauncherSettings],
        toast: Callable[[Say, str], None],  # what to say, "info" | "error" | "ok"
        cannot_update: Callable[[], Say | None],
        restart: Callable[[object], None],
        open_url: Callable[[str], None],
    ):
        self.jobs, self._settings, self._toast = jobs, settings, toast
        self._cannot, self._restart, self._open_url = cannot_update, restart, open_url
        self.status = LauncherStatus()
        self.checking = False  # a check the user asked for is running (the button waits)
        self.notices: dict[str, UpdateNotice] = {}
        self._offered: str | None = None  # the version the notice shows
        self._offer_info: dict | None = None
        self._prepared = None  # a downloaded and checked update, for Restart now
        self._advisory_shown = False
        self._listeners: list[Callable[[], None]] = []
        self.me3_note = ""  # the newer me3 version, said once a session (the status text)

    # ---- what the Settings page reads
    def state(self) -> dict:
        return {"status": self.status, "checking": self.checking, "notices": list(self.notices.values())}

    def watch(self, call: Callable[[], None]) -> None:
        self._listeners.append(call)

    def _notify(self) -> None:
        for call in list(self._listeners):
            try:
                call()
            except RuntimeError:  # the page is gone
                self._listeners.remove(call)

    # ---- checking
    def check(self, force: bool = False) -> None:
        if force:
            if self.checking:
                return
            self.checking, self.status = True, LauncherStatus("checking")
            self._notify()

        def work(_progress):
            try:
                check = feed.check_launcher_update(force=force)
            except Exception as e:
                check = feed.UpdateCheck("error", reason=str(e))
            try:
                advisory = feed.check_advisory(force=force)
            except Exception:
                advisory = None
            return {"check": check, "advisory": advisory, "force": force}

        self.jobs.start(work, on_result=self._checked, name="launcher-update")

    def channel_changed(self) -> None:
        """The channel was switched: what was offered is forgotten and the feed is asked again."""
        self._offered = None
        self.check(force=True)

    def forget_offer(self) -> None:
        self._offered = None

    def _checked(self, payload) -> None:
        check, advisory, force = payload["check"], payload.get("advisory"), payload.get("force")
        self.checking = False
        channel = self._settings().launcher_channel
        self.status = launcher_status(check, channel)
        self._notify()
        if advisory and not self._advisory_shown:
            self._advisory_shown = True
            self._show(advisory_notice(advisory, check.offer))
        if force:
            self._toast(*check_say(check, channel))
        if check.offer and check.offer["version"] != self._offered:
            self._offered = check.offer["version"]
            self._offer_info = check.offer
            self._show(offer_notice(check.offer, FROZEN))

    # ---- notices
    def _show(self, n: UpdateNotice) -> None:
        self.notices[n.id] = n  # a new notice with the same id replaces the old one
        self._notify()

    def dismiss(self, notice_id: str) -> None:
        if self.notices.pop(notice_id, None) is not None:
            self._notify()

    def notice_action(self, notice_id: str, key: str) -> None:
        n = self.notices.get(notice_id)
        a = next((a for a in (n.actions if n else ()) if a.key == key), None)
        if a is None:
            return
        if a.url:
            self._open_url(a.url)
        elif a.key == "update" and self._offer_info:
            self._start(self._offer_info)
        elif a.key == "skip" and self._offer_info:
            feed.skip_update(self._offer_info["version"])
            self.dismiss(notice_id)
        elif a.key == "restart":
            self._restart(self._prepared)
        elif a.key == "later":
            self.dismiss(notice_id)
        elif a.key == "again":
            self.check(force=True)

    # ---- downloading
    def _start(self, info: dict) -> None:
        why = self._cannot()
        if why is not None:
            self._toast(Say("cannot_update", {"why": asdict(why)}), "error")
            return
        version = info["version"]
        self._show(downloading_notice(version))

        def work(report):
            def progress(done, total):
                mb = done / 1_000_000
                report(f"{mb:.0f} of {total / 1_000_000:.0f} MB" if total else f"{mb:.0f} MB")

            try:
                prepared = updates.download_update(info, progress=progress)
                report("Keeping this version, to put it back if the new one does not start")
                prepared.rollback = updates.stage_rollback()
                return {"prepared": prepared, "version": version}
            except Exception as e:
                return {"error": str(e)}

        self.jobs.start(work, on_result=self._downloaded, on_progress=self._progress, name="launcher-download")

    def _progress(self, text: str) -> None:
        if "flow" in self.notices and self._offer_info:
            self._show(downloading_notice(self._offer_info["version"], text))

    def _downloaded(self, result: dict) -> None:
        if result.get("error"):
            self._offered = None  # the next check offers it again
            self._show(failed_notice(result["error"]))
            return
        self._prepared = result["prepared"]
        self._show(ready_notice(result["version"], bool(self._prepared.delta)))

    def cannot_update(self, game_running: bool, game_name: str, busy: bool) -> Say | None:
        """Why the program cannot be replaced now, or None."""
        return cannot_update(game_running, game_name, busy, updates.busy_reason())

    # ---- after a start
    def outcome(self, result: dict | None) -> None:
        """How the last update went, shown once."""
        if not result:
            return
        updates.clear_outcome()
        n = outcome_notice(result)
        if n is None:
            self._toast(Say("updated", {"version": result.get("version", ""), "was": result.get("from") or ""}), "ok")
            return
        self._offered = None
        self._show(n)

    def migration(self, record: dict | None) -> None:
        """The move from the old (Inno Setup) install, reported once per state."""
        n = migration_notice(record)
        if n is not None:
            self._show(n)
