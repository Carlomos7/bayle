"""The Mods page's operations on overhauls the launcher installs (a preview feature): install from an unpacked
download, remove (and what its installer changed to put back), take over a setup its own installer made, and clean up
what the installers left. A tick list travels as a Pick whose rows are in the prompt; the answer is the ticked
indexes, and the server derives the same list again from the profile (so the indexes mean the same rows).
See ops/mods.py for the conventions."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from bayle.platform.text import tr
from bayle.services import mods as mod_service
from bayle.services.errors import OperationError
from bayle.session.operations import Call, Result, operation
from bayle.session.ops.mods import Done, ProfileRef, run_logged_job, stamp, start_logged
from bayle.session.plans import Answer, Proposal
from bayle.views.common import Pick, Refusal, prompt_dict
from bayle.views.mods import ModsPresenter


class PickOffer(Result):
    """A tick list to show: its words and rows (kind "pick"), or None when there is nothing to choose."""

    label: str = ""
    prompt: dict[str, Any] | None = None


def _pick(words: Pick, rows: list[str], ticked: tuple[int, ...] = ()) -> dict[str, Any]:
    return prompt_dict(dataclasses.replace(words, rows=tuple(rows), ticked=ticked))


def _overhaul(call: Call, profile: str) -> dict:
    has = mod_service.profile_overhaul(profile, loc=call.session.locations())
    if has is None:
        raise OperationError("no_overhaul", tr("This profile has no overhaul the launcher knows."))
    return has


# ----------------------------------------------------------------------------- install
class InstallFolder(ProfileRef):
    folder: str  # the folder the download was unpacked into


@operation("mods.overhaul_install", params=InstallFolder, result=Done, kind="plan", writes=True)
def overhaul_install(call: Call, p: InstallFolder) -> Proposal | Refusal:
    """Preview installing an overhaul from the folder it was unpacked into; answering starts the install."""
    session, pres, loc = call.session, ModsPresenter(), call.session.locations()
    try:
        preview = mod_service.preview_overhaul_install(p.profile, p.folder, loc=loc)
    except Exception as e:  # not a download the launcher installs: said, nothing written
        return pres.overhaul_unreadable(p.folder, str(e))
    words = pres.overhaul_install(p.profile, preview)
    if isinstance(words, Refusal):
        return words

    def work(jloc: Any) -> dict:
        mod_service.install_overhaul(preview, loc=jloc)
        return Done(note=f"installed {preview.label}").model_dump()

    def run(_answer: Answer) -> str:
        verb = "update" if preview.update else "install"
        return start_logged(
            session, pres.overhaul_installing(preview), f"launcher: {verb} overhaul {preview.label}", work
        )

    return Proposal(words, run, stale=lambda: stamp(p.profile))


# ----------------------------------------------------------------------------- remove
@operation("mods.overhaul_remove_choices", params=ProfileRef, result=PickOffer)
def overhaul_remove_choices(call: Call, p: ProfileRef) -> PickOffer:
    """For an overhaul its own installer set up: the changes it made that can be put back, offered unticked."""
    has = _overhaul(call, p.profile)
    label = has["label"]
    choices = mod_service.legacy_overhaul_choices(p.profile, loc=call.session.locations()) if has["legacy"] else []
    prompt = _pick(ModsPresenter().overhaul_put_back(label), [text for text, _ in choices]) if choices else None
    return PickOffer(label=label, prompt=prompt)


class RemoveChosen(ProfileRef):
    chosen: list[int] = []  # the ticked rows of overhaul_remove_choices


@operation("mods.overhaul_remove", params=RemoveChosen, result=Done, kind="plan", writes=True)
def overhaul_remove(call: Call, p: RemoveChosen) -> Proposal | Refusal:
    """Preview removing the profile's overhaul; the confirm's check box switches a shared dependency back off."""
    session, pres, loc = call.session, ModsPresenter(), call.session.locations()
    has = _overhaul(call, p.profile)
    label = has["label"]
    choices = mod_service.legacy_overhaul_choices(p.profile, loc=loc) if has["legacy"] else []
    picked = [choices[i][1] for i in p.chosen if 0 <= i < len(choices)]
    try:
        preview = mod_service.preview_overhaul_removal(p.profile, loc=loc, legacy_choices=picked)
    except Exception as e:
        return pres.overhaul_remove_failed(label, str(e))
    words = pres.overhaul_remove(p.profile, label, preview)
    if isinstance(words, Refusal):
        return words

    def run(answer: Answer) -> str:
        final = preview
        if answer.option:  # switch the shared dependency back off: previewed again with it
            final = mod_service.preview_overhaul_removal(p.profile, loc=loc, revert_asked=True, legacy_choices=picked)
            if not final.ok:
                raise OperationError(
                    "overhaul_not_removed", pres.overhaul_remove_failed(label, " ".join(final.refusals)).body
                )

        def work(_jloc: Any) -> dict:
            mod_service.remove_overhaul(final)
            return Done(note=f"removed {label}").model_dump()

        return start_logged(session, pres.overhaul_removing(label), f"launcher: remove overhaul {label}", work)

    return Proposal(words, run, stale=lambda: stamp(p.profile))


# ----------------------------------------------------------------------------- take over
@operation("mods.takeover_choices", params=ProfileRef, result=PickOffer)
def takeover_choices(call: Call, p: ProfileRef) -> PickOffer:
    """For Take over: what the player may also choose (a change to put back, or the installer's backups), the entries
    the installer copied already ticked."""
    has = _overhaul(call, p.profile)
    if not has.get("takeover"):
        raise OperationError("no_takeover", tr("The launcher made this setup, so there is nothing to take over."))
    label = has["label"]
    choices = mod_service.take_over_choices(p.profile, loc=call.session.locations())
    if not choices:
        return PickOffer(label=label)
    ticked = tuple(i for i, c in enumerate(choices) if getattr(c, "copied", False))
    rows = [mod_service.choice_text(c) for c in choices]
    return PickOffer(label=label, prompt=_pick(ModsPresenter.takeover_pick(label), rows, ticked))


@operation("mods.takeover", params=RemoveChosen, result=Done, kind="plan", writes=True)
def takeover(call: Call, p: RemoveChosen) -> Proposal | Refusal:
    """Preview taking over a setup its own installer made (one logged job with Undo)."""
    session, pres, loc = call.session, ModsPresenter(), call.session.locations()
    has = _overhaul(call, p.profile)
    label = has["label"]
    choices = mod_service.take_over_choices(p.profile, loc=loc)
    picked = [choices[i] for i in p.chosen if 0 <= i < len(choices)]
    try:
        preview = mod_service.preview_take_over(p.profile, loc=loc, chosen=picked)
    except Exception as e:
        return pres.takeover_failed(label, str(e))
    words = pres.takeover_confirm(p.profile, label, preview)
    if isinstance(words, Refusal):
        return words

    def run(answer: Answer) -> str:
        final = preview
        if answer.option:
            final = mod_service.preview_take_over(p.profile, loc=loc, chosen=picked, revert_asked=True)
            if not final.ok:
                raise OperationError("takeover_refused", pres.takeover_failed(label, " ".join(final.refusals)).body)

        def work(_jloc: Any) -> dict:
            mod_service.remove_overhaul(final)
            return Done(note=f"took over {label}").model_dump()

        return start_logged(
            session, tr("Taking over {label}...").format(label=label), f"launcher: take over overhaul {label}", work
        )

    return Proposal(words, run, stale=lambda: stamp(p.profile))


# ----------------------------------------------------------------------------- installer leftovers
class Leftovers(Result):
    folders: dict[str, Any] | None  # a Pick: folders no profile uses any more (None when there are none)
    backups: list[dict[str, Any]]  # a Confirm each, asked one at a time and last: the installers' profile backups


def _leftovers(call: Call, profile: str) -> tuple[list, list]:
    left = mod_service.overhaul_leftovers(profile, loc=call.session.locations())
    return [x for x in left if not x.backups], [x for x in left if x.backups]


@operation("mods.leftovers", params=ProfileRef, result=Leftovers)
def leftovers(call: Call, p: ProfileRef) -> Leftovers:
    """What overhauls' own installers left beside the profile that no profile uses any more."""
    pres = ModsPresenter()
    folders, backups = _leftovers(call, p.profile)
    return Leftovers(
        folders=_pick(pres.leftovers(bool(backups)), [x.label for x in folders]) if folders else None,
        backups=[prompt_dict(pres.leftover_backups(x)) for x in backups],
    )


class CleanParams(ProfileRef):
    folders: list[int] = []  # the ticked rows of Leftovers.folders
    backups: list[int] = []  # the backups confirmed, by their order in Leftovers.backups


def _check_clean(call: Call, p: CleanParams) -> None:
    if not (p.folders or p.backups):
        raise OperationError("nothing_chosen", tr("Nothing was chosen."))


@operation(
    "mods.leftovers_clean",
    params=CleanParams,
    result=Done,
    kind="job",
    writes=True,
    title=lambda _p: ModsPresenter().leftovers_moving(),
    check=_check_clean,
)
def leftovers_clean(call: Call, p: CleanParams) -> Done:
    """Send the chosen leftovers to the Recycle Bin (one logged job)."""
    folders, backups = _leftovers(call, p.profile)
    paths = [Path(folders[i].path) for i in p.folders if 0 <= i < len(folders)]
    paths += [Path(backups[i].path) for i in p.backups if 0 <= i < len(backups)]

    def work(_loc: Any) -> None:
        mod_service.remove_overhaul_leftovers(paths)

    run_logged_job(
        call.session.locations(),
        ModsPresenter().leftovers_moving(),
        "launcher: clean up overhaul installer leftovers",
        work,
    )
    return Done(note=f"{len(paths)} moved to the Recycle Bin")
