"""Take over, on the Mods page: an overhaul its own installer set up becomes the launcher's to manage. Pick what to
put back (nothing is ticked), see everything that changes, confirm; one logged job with Undo (all of it the session's:
mods.takeover_choices and mods.takeover); then offer to install the overhaul again through the launcher (the Install
mod flow; nothing installs by itself)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bayle.platform.text import tr
from bayle.views.common import Confirm

if TYPE_CHECKING:
    from bayle.ui.pages.mods.adapter import ModsAdapter


def reinstall_words(label: str) -> Confirm:
    return Confirm(
        title=tr("Install {label} with the launcher now?").format(label=label),
        changes=(tr("This opens Install mod: pick the download you unpacked, and the launcher sets it up."),),
        apply=tr("Install mod..."),
    )


def start(page: ModsAdapter) -> None:
    """The Mods ⋯ menu's Take over... for the current profile."""
    profile, has = page._ready(), page._view.overhaul_info if page._view else None
    if profile is None or not has or not has.takeover:
        return
    label = has.label

    def ask(chosen: list) -> None:
        def done(ok: bool, _data: dict) -> None:
            if ok:
                page.notifier.ask(reinstall_words(label), lambda go, _o: page.host.install(True) if go else None)

        page._calls.plan("mods.takeover", page._ref(chosen=chosen), destructive=True, done=done)

    page._calls.run(
        "mods.takeover_choices",
        page._ref(),
        lambda got: page._show_pick(got.prompt, ask) if got.prompt else ask([]),
    )
