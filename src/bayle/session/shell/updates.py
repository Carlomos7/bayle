"""The launcher's own update flow, as the shell runs it (ported from the Widgets window, same checks): looks for a
release on a schedule or when asked, keeps the launcher line and the notices (offer, download progress, ready,
failed, advisory, how the last update went, the move from the old installer) that the Settings page shows, downloads
and checks an offer, and hands a prepared package to the host to apply on restart.

The page never calls the updater: its notice buttons come back through notice_action(), which runs the same checks
as before (the game and jobs stopped, the program's identity, the prepared package). Nothing here shows anything
itself; the host passes the words on as toasts and the Settings page reads state()."""

from __future__ import annotations

from collections.abc import Callable

from bayle.config.settings import FROZEN, LauncherSettings
from bayle.platform.text import tr
from bayle.session.shell.background import Background
from bayle.updates import apply as updates
from bayle.updates import feed
from bayle.views import settings as sp


class UpdateFlow:
    def __init__(
        self,
        jobs: Background,
        settings: Callable[[], LauncherSettings],
        toast: Callable[[str, str, str], None],  # title, body, "info" | "error" | "ok"
        cannot_update: Callable[[], str],
        restart: Callable[[object], None],
        open_url: Callable[[str], None],
    ):
        self.jobs, self._settings, self._toast = jobs, settings, toast
        self._cannot, self._restart, self._open_url = cannot_update, restart, open_url
        self.line = ""
        self.tone = "muted"
        self.checking = False  # a check the user asked for is running (the button waits)
        self.notices: dict[str, sp.UpdateNotice] = {}
        self._offered: str | None = None  # the version the notice shows
        self._offer_info: dict | None = None
        self._prepared = None  # a downloaded and checked update, for Restart now
        self._advisory_shown = False
        self._listeners: list[Callable[[], None]] = []
        self.me3_note = ""  # the newer me3 version, said once a session (the status text)

    # ---- what the Settings page reads
    def state(self) -> dict:
        return {"line": self.line, "tone": self.tone, "checking": self.checking, "notices": list(self.notices.values())}

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
            self.checking, self.line, self.tone = True, tr("Checking for updates..."), "muted"
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
        self.line, self.tone = sp.launcher_status(check, channel)
        self._notify()
        if advisory and not self._advisory_shown:
            self._advisory_shown = True
            self._show(sp.advisory_notice(advisory, check.offer))
        said = sp.check_toast(check, channel) if force else None
        if said:
            self._toast(said[0], said[1], said[2])
        if check.offer and check.offer["version"] != self._offered:
            self._offered = check.offer["version"]
            self._offer_info = check.offer
            self._show(sp.offer_notice(check.offer, FROZEN))

    # ---- notices
    def _show(self, n: sp.UpdateNotice) -> None:
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
        if why:
            self._toast(tr("Cannot update now"), why, "error")
            return
        version = info["version"]
        self._show(sp.downloading_notice(version))

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
            self._show(sp.downloading_notice(self._offer_info["version"], text))

    def _downloaded(self, result: dict) -> None:
        if result.get("error"):
            self._offered = None  # the next check offers it again
            self._show(sp.failed_notice(result["error"]))
            return
        self._prepared = result["prepared"]
        self._show(sp.ready_notice(result["version"], bool(self._prepared.delta)))

    def cannot_update(self, game_running: bool, game_name: str, busy: bool) -> str:
        """Why the program cannot be replaced now, or ''."""
        return sp.cannot_update(game_running, game_name, busy, updates.busy_reason())

    # ---- after a start
    def outcome(self, result: dict | None) -> None:
        """How the last update went, shown once."""
        if not result:
            return
        updates.clear_outcome()
        n = sp.outcome_notice(result)
        if n is None:
            title, body = sp.outcome_ok_text(result)
            self._toast(title, body, "ok")
            return
        self._offered = None
        self._show(n)

    def migration(self, record: dict | None) -> None:
        """The move from the old (Inno Setup) install, reported once per state."""
        n = sp.migration_notice(record)
        if n is not None:
            self._show(n)
