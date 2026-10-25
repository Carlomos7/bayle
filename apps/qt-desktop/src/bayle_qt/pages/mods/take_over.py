"""Take over, on the Mods page: an overhaul its own installer set up becomes the launcher's to manage. Pick what to
put back (nothing is ticked), see everything that changes, confirm; one logged job with Undo (all of it the engine's
ModInstallService: take_over_choices, check_take_over, take_over); then offer to install the overhaul again through the
launcher (the Install mod flow; nothing installs by itself). The words are here; the engine sends facts and the
profile's stamp, which goes back with the start (if the profile changed meanwhile, the page asks once more)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from bayle.errors import OperationError
from bayle.work.prompts import Confirm, Pick, Refusal, prompt_dict

from bayle_qt.notifications import say_refusal
from bayle_qt.pages.mods.install_adapter import query
from bayle_qt.text import tr

if TYPE_CHECKING:
    from bayle.services.mod_install import OverhaulChoices, OverhaulPlan

    from bayle_qt.pages.mods.adapter import ModsAdapter


def reinstall_words(label: str) -> Confirm:
    return Confirm(
        title=tr("Install {label} with the launcher now?").format(label=label),
        changes=(tr("This opens Install mod: pick the download you unpacked, and the launcher sets it up."),),
        apply=tr("Install mod..."),
    )


def pick_prompt(choices: OverhaulChoices) -> dict:
    """The tick list of what the installer changed (the rows the engine gave), the ones it copied ticked."""
    words = Pick(
        title=tr("Take over {label}: what to put back?").format(label=choices.label),
        body=tr(
            "Its installer changed these in your profile (compared with its oldest backup of it), and kept backups of "
            "your profile. Tick what to put back or move to the Recycle Bin; the rest stays as it is now."
        ),
        apply=tr("Continue"),
        none=tr("Leave them"),
        rows=choices.rows,
        ticked=choices.ticked,
    )
    return prompt_dict(words)


def failed(label: str, why: str) -> Refusal:
    return Refusal(tr("Can't take over {label}").format(label=label), why)


def confirm_words(profile: Path, plan: OverhaulPlan) -> Confirm:
    asked = ", ".join(plan.asked)
    return Confirm(
        title=tr("Take over {label} in {profile}").format(label=plan.label, profile=profile.name),
        changes=plan.lines,
        apply=tr("Take over"),
        safety=tr(
            "Your other mods' files are not touched. Undo in Activity puts it all back. Folders go to the Recycle Bin."
        ),
        option=tr("Also switch {names} back off, as it was before the install").format(names=asked) if asked else "",
    )


def start(page: ModsAdapter) -> None:
    """The Mods ⋯ menu's Take over... for the current profile."""
    profile, has = page._ready(), page._view.overhaul_info if page._view else None
    if profile is None or not has or not has.takeover:
        return
    host: Any = page.host  # the Mods page's host; its features are the engine's interfaces
    notifier = page.notifier
    service = host.features.mod_install
    label = has.label

    def say(refusal: Refusal) -> None:
        say_refusal(notifier, refusal)

    def refused(e: OperationError) -> None:
        # the check's and the start's refusal name their reasons; the rest (no overhaul, ...) speaks for itself
        if e.code == "cannot_take_over":
            refusals = (e.details or {}).get("refusals")
            say(failed(label, " ".join(refusals) if refusals else e.message))
        else:
            notifier.toast(e.message, error=True)

    def ended(snap: Any) -> None:
        if snap is not None and snap.state == "done":
            notifier.ask(reinstall_words(label), lambda go, _o: host.install(True) if go else None)
        elif snap is not None and snap.state == "failed" and snap.error is not None:
            say(failed(label, snap.error.message))

    def ask(chosen: list[int], again: bool = True) -> None:
        def checked(plan: OverhaulPlan) -> None:
            if not plan.ok:
                say(failed(plan.label, " ".join(plan.refusals)))
                return

            def answered(ok: bool, revert: bool) -> None:
                if not ok:
                    return

                def stale(e: OperationError) -> None:
                    if e.code == "stale" and again:
                        ask(chosen, again=False)  # it changed since: the player sees the fresh words
                    else:
                        refused(e)

                query(
                    host,
                    lambda: service.take_over(str(profile), chosen, revert, plan.stamp),
                    lambda job_id: host.follow_job(job_id, ended),
                    stale,
                )

            notifier.ask(confirm_words(profile, plan), answered, destructive=True)

        query(host, lambda: service.check_take_over(str(profile), chosen), checked, refused)

    def offered(got: OverhaulChoices) -> None:
        if got.rows:
            page._show_pick(pick_prompt(got), ask)
        else:
            ask([])

    query(host, lambda: service.take_over_choices(str(profile)), offered, refused)
