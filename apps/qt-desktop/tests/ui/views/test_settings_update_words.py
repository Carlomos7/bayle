"""The update words (safety): Update now only for a packaged copy with a signed release, Restart now only after a
download was prepared, and nothing replaces the program while the game or a job runs. The engine sends codes and
facts (session.shell.updates); the sentences are ui/launcher/presenter.py."""

from bayle_qt.launcher import presenter
from bayle_qt.shell import updates as flow
from bayle_qt.updater import apply as updates

OFFER = {"version": "9.9.9", "url": "https://example.invalid", "notes": "", "assets": {}}


def keys(notice):
    return [a.key for a in notice.actions]


def test_update_now_needs_a_packaged_copy_and_a_signed_release_and_restart_needs_a_download(monkeypatch):
    monkeypatch.setattr(updates, "can_self_update", lambda info: True)
    assert keys(flow.offer_notice(OFFER, frozen=True)) == ["update", "notes", "skip"]
    assert keys(flow.offer_notice(OFFER, frozen=False)) == ["download", "notes", "skip"]  # from source
    monkeypatch.setattr(updates, "can_self_update", lambda info: False)
    assert keys(flow.offer_notice(OFFER, frozen=True)) == ["download", "notes", "skip"]  # unsigned release
    for notice in (flow.offer_notice(OFFER, frozen=True), flow.downloading_notice("9.9.9"), flow.failed_notice("x")):
        assert "restart" not in keys(notice)
    assert keys(flow.ready_notice("9.9.9", delta=False)) == ["restart", "later"]


def test_the_notices_are_worded_in_qt_with_the_same_sentences(monkeypatch):
    monkeypatch.setattr(updates, "can_self_update", lambda info: True)
    offer = presenter.notice(flow.offer_notice(OFFER, frozen=True))
    assert offer.title.endswith("9.9.9 is available") and offer.body == "One click, then a restart. Your settings stay."
    assert [(a.key, a.label, a.primary) for a in offer.actions] == [
        ("update", "Update now", True),
        ("notes", "Notes", False),
        ("skip", "Skip this version", False),
    ]
    assert presenter.notice(flow.downloading_notice("9.9.9")).body == "Starting..."
    assert presenter.notice(flow.downloading_notice("9.9.9", "5 of 9 MB")).body == "5 of 9 MB"
    ready = presenter.notice(flow.ready_notice("9.9.9", delta=True))
    assert ready.body.startswith("Signature and an update of package checked. Restart to finish.")
    assert [a.label for a in ready.actions] == ["Restart now", "Later"]
    failed = presenter.notice(flow.outcome_notice({"status": "rolled_back", "version": "9.9.9"}))
    assert failed.title.endswith("9.9.9 did not start; this version was put back") and "did not start." in failed.body
    assert flow.outcome_notice({"status": "ok"}) is None


def test_the_check_toasts_and_the_status_line_keep_their_sentences():
    ok = flow.Say("up_to_date", {"version": "1.0.0", "channel": "beta"})
    assert presenter.say_text(ok.code, ok.facts) == "Up to date: 1.0.0 is the newest on the Beta channel"
    assert presenter.say_text("update_available", {"version": "2.0.0"}) == (
        "Update available: 2.0.0 is ready to download in Settings."
    )
    assert presenter.say_text("updated", {"version": "2.0.0", "was": "1.0.0"}).endswith("2.0.0 is running (was 1.0.0).")
    assert presenter.launcher_status(flow.LauncherStatus()) == ("", "muted")
    assert presenter.launcher_status(flow.LauncherStatus("checking")) == ("Checking for updates...", "muted")
    line, tone = presenter.launcher_status(flow.LauncherStatus("offer", "beta", "source", "2.0.0"))
    assert line.endswith("running from source  ·  beta channel  ·  2.0.0 is available") and tone == "accent"
    line, tone = presenter.launcher_status(flow.LauncherStatus("failed", "stable", "installed", reason="No network"))
    assert "could not check: No network" in line and tone == "warning"


def test_nothing_is_replaced_while_the_game_or_a_job_runs():
    assert flow.cannot_update(True, "Elden Ring", False, "") == flow.Say("update_game_running", {"game": "Elden Ring"})
    assert flow.cannot_update(False, "Elden Ring", True, "") == flow.Say("update_busy")
    why = flow.cannot_update(False, "Elden Ring", False, "A Play from a shortcut runs.")
    assert why is not None and presenter.say_text(why.code, why.facts) == "A Play from a shortcut runs."
    assert flow.cannot_update(False, "Elden Ring", False, "") is None
    assert presenter.say_text("update_game_running", {"game": "Elden Ring"}) == "Close Elden Ring first."
    assert presenter.say_text("update_busy") == "Wait for the current job."
