"""Take over, on the Mods page: an overhaul its own installer set up becomes the launcher's to manage. Pick what to
put back (nothing is ticked), see everything that changes, confirm; one logged job with Undo; then offer to install
the overhaul again through the launcher (the Install mod flow; nothing installs by itself)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.platform.text import tr
from bayle.services import mods as mod_service
from bayle.ui.pages.mods.presenter import Confirm, Pick, Refusal

if TYPE_CHECKING:
    from bayle.ui.pages.mods.adapter import ModsAdapter


def pick_words(label: str) -> Pick:
    return Pick(
        title=tr("Take over {label}: what to put back?").format(label=label),
        body=tr(
            "Its installer changed these in your profile (compared with its oldest backup of it), and kept backups of "
            "your profile. Tick what to put back or move to the Recycle Bin; the rest stays as it is now."
        ),
        apply=tr("Continue"),
        none=tr("Leave them"),
    )


def confirm_words(profile: Path, label: str, preview) -> Confirm | Refusal:
    if not preview.ok:
        return Refusal(tr("Can't take over {label}").format(label=label), " ".join(preview.refusals))
    asked = ", ".join(str(e.entry) for e in preview.asked)
    return Confirm(
        title=tr("Take over {label} in {profile}").format(label=label, profile=profile.name),
        changes=tuple(preview.lines),
        apply=tr("Take over"),
        safety=tr(
            "Your other mods' files are not touched. Undo in Activity puts it all back. Folders go to the Recycle Bin."
        ),
        option=tr("Also switch {names} back off, as it was before the install").format(names=asked) if asked else "",
    )


def reinstall_words(label: str) -> Confirm:
    return Confirm(
        title=tr("Install {label} with the launcher now?").format(label=label),
        changes=(tr("This opens Install mod: pick the download you unpacked, and the launcher sets it up."),),
        apply=tr("Install mod..."),
    )


def start(page: ModsAdapter) -> None:
    """The Mods ⋯ menu's Take over... for the current profile."""
    profile, has = page._ready(), page._overhaul[1]
    if profile is None or not has or not has.get("takeover"):
        return
    loc, label = page.host.locations, has["label"]

    def preview_and_ask(chosen: list) -> None:
        try:
            preview = mod_service.preview_take_over(profile, loc=loc, chosen=chosen)
        except Exception as e:
            page._refuse(Refusal(tr("Can't take over {label}").format(label=label), str(e)))
            return
        words = confirm_words(Path(profile), label, preview)
        if isinstance(words, Refusal):
            page._refuse(words)
            return

        def answered(ok: bool, switch_back: bool) -> None:
            if not ok or page.host.busy:
                return
            final = preview
            if switch_back:
                final = mod_service.preview_take_over(profile, loc=loc, chosen=chosen, revert_asked=True)
                if not final.ok:
                    page._refuse(Refusal(tr("Can't take over {label}").format(label=label), " ".join(final.refusals)))
                    return

            def job(_launch, loc):
                from bayle.platform import logging as run_logging

                run_logging.start_log(f"launcher: take over overhaul {label}", loc.game.key)
                mod_service.remove_overhaul(final)

            def done(outcome) -> None:
                if outcome.ok:
                    page.notifier.ask(reinstall_words(label), lambda go, _o: page.host.install(True) if go else None)

            page.host.run_job(job, tr("Taking over {label}...").format(label=label), done)

        page.notifier.ask(words, answered, destructive=True)

    choices = mod_service.take_over_choices(profile, loc=loc)
    if choices:
        page._pick(
            replace(pick_words(label), ticked=tuple(i for i, c in enumerate(choices) if getattr(c, "copied", False))),
            [mod_service.choice_text(c) for c in choices],
            lambda ticked: preview_and_ask([choices[i] for i in ticked]),
        )
    else:
        preview_and_ask([])
