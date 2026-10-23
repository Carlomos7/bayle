"""The Settings presenter's update words (safety): Update now only for a packaged copy with a signed release,
Restart now only after a download was prepared, and nothing replaces the program while the game or a job runs."""

from bayle.updates import apply as updates
from bayle.views import settings as sp  # the update notices stay shared

OFFER = {"version": "9.9.9", "url": "https://example.invalid", "notes": "", "assets": {}}


def keys(notice):
    return [a.key for a in notice.actions]


def test_update_now_needs_a_packaged_copy_and_a_signed_release_and_restart_needs_a_download(monkeypatch):
    monkeypatch.setattr(updates, "can_self_update", lambda info: True)
    assert keys(sp.offer_notice(OFFER, frozen=True)) == ["update", "notes", "skip"]
    assert keys(sp.offer_notice(OFFER, frozen=False)) == ["download", "notes", "skip"]  # from source
    monkeypatch.setattr(updates, "can_self_update", lambda info: False)
    assert keys(sp.offer_notice(OFFER, frozen=True)) == ["download", "notes", "skip"]  # unsigned release
    for notice in (sp.offer_notice(OFFER, frozen=True), sp.downloading_notice("9.9.9"), sp.failed_notice("x")):
        assert "restart" not in keys(notice)
    assert keys(sp.ready_notice("9.9.9", delta=False)) == ["restart", "later"]


def test_nothing_is_replaced_while_the_game_or_a_job_runs():
    assert sp.cannot_update(True, "Elden Ring", False, "")
    assert sp.cannot_update(False, "Elden Ring", True, "")
    assert sp.cannot_update(False, "Elden Ring", False, "A Play from a shortcut runs.")
    assert sp.cannot_update(False, "Elden Ring", False, "") == ""
