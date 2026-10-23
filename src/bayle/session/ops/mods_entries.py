"""The Mods page's operations on the entries of a profile: on or off, remove (and take it back), move, rename, the
Mod options, the profile's earlier versions, Add existing, and editing the profile as text. See ops/mods.py for the
conventions (confirm-and-retry, plans, codes)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from bayle.errors import OperationError
from bayle.mods import order as mod_order
from bayle.platform.text import tr
from bayle.services import mods as mod_service
from bayle.services import mods_page, profile_mods
from bayle.session.operations import Call, Params, Result, operation
from bayle.session.ops.mods import (
    Changed,
    Done,
    EntryRef,
    ProfileRef,
    entry_of,
    idle,
    needs_confirmation,
    refusing,
    run_logged_job,
    stamp,
    start_logged,
)
from bayle.views.mods import ModsPresenter
from bayle.work.prompts import Proposal


# ----------------------------------------------------------------------------- an entry on or off, and its Undo
class EnabledParams(EntryRef):
    enabled: bool


@operation("mods.set_enabled", params=EnabledParams, result=Changed, kind="command", writes=True)
def set_enabled(call: Call, p: EnabledParams) -> Changed:
    idle(call.session)
    name = entry_of(p.profile, p.index)["name"]
    with refusing("profile_write_failed"):
        mod_service.set_mod_options(p.profile, p.index, {"enabled": p.enabled}, loc=call.session.locations())
    return Changed(note=f"profile: {name} {'on' if p.enabled else 'off'}", name=name)


@operation("mods.undo_change", params=ProfileRef, result=Done, kind="command", writes=True)
def undo_change(call: Call, p: ProfileRef) -> Done:
    """Put back the copy kept just before the last change to the profile."""
    with refusing("undo_failed"):
        profile_mods.undo_last_change(p.profile)
    return Done(note="profile: undid the last change")


# ----------------------------------------------------------------------------- removing an entry
class RemoveParams(EntryRef):
    name: str  # the entry's name when the player chose it: a changed profile is refused
    confirmed: bool = False
    delete_folder: bool | None = None  # the check box; None = the folder goes to the Recycle Bin when that is safe


class RemoveResult(Result):
    name: str
    undo: dict[str, Any]  # the record Undo takes back (mods.undo_removal)


def _removal(call: Call, p: RemoveParams) -> profile_mods.Removal:
    entry = entry_of(p.profile, p.index)
    if entry["name"] != p.name:
        raise OperationError("stale", tr("The profile changed; look again before removing."), {"index": p.index})
    return profile_mods.removal(p.profile, entry, loc=call.session.locations())


def _check_remove(call: Call, p: RemoveParams) -> None:
    plan = _removal(call, p)
    if not p.confirmed and not profile_mods.removal_undoable(p.profile, plan, loc=call.session.locations()):
        raise needs_confirmation(ModsPresenter().removal(p.profile, plan))  # Undo brings the rest back: no confirm


@operation(
    "mods.remove",
    params=RemoveParams,
    result=RemoveResult,
    kind="job",
    writes=True,
    quiet=True,
    title=lambda p: tr("Removing {name}...").format(name=p.name),
    check=_check_remove,
)
def remove(call: Call, p: RemoveParams) -> RemoveResult:
    """Take the entry out of the profile (its folder to the Recycle Bin when asked and nothing else loads from it).
    Without confirmed=True it raises needs_confirmation, unless Undo brings everything back."""
    plan = _removal(call, p)
    delete = plan.can_recycle if p.delete_folder is None else p.delete_folder
    out = run_logged_job(
        call.session.locations(),
        tr("Removing {name}...").format(name=p.name),
        f"launcher: remove {p.name}",
        lambda loc: profile_mods.remove_entry(p.profile, p.index, plan, delete_folder=delete, loc=loc),
    )
    return RemoveResult(name=p.name, undo=out["undo"])


class UndoParams(Params):
    undo: dict[str, Any]


@operation("mods.undo_removal", params=UndoParams, result=Changed, kind="command", writes=True)
def undo_removal(call: Call, p: UndoParams) -> Changed:
    with refusing("undo_failed"):
        profile_mods.undo_removal(p.undo, loc=call.session.locations())
    name = str(p.undo.get("name") or "")
    return Changed(note=f"profile: restored {name}", name=name)


@operation("mods.remove_holder", params=EntryRef, result=Changed, kind="plan", writes=True)
def remove_holder(call: Call, p: EntryRef) -> Proposal:
    """An entry that only points at a folder of mods: taking it out changes nothing in the game."""
    session = call.session
    entry = entry_of(p.profile, p.index)
    needs = profile_mods.holder_dependents(p.profile, entry)
    name = entry["name"]

    def work(loc: Any) -> dict:
        profile_mods.remove_holder(p.profile, p.index, entry, needs, loc=loc)
        return Changed(note=f"profile: removed {name} (a folder of mods)", name=name).model_dump()

    def run(_answer: Any) -> str:
        title = tr("Removing {name}...").format(name=name)
        return start_logged(session, title, f"launcher: remove {name} (a folder of mods)", work, quiet=True)

    return Proposal(ModsPresenter().holder(p.profile, name, needs), run, stale=lambda: stamp(p.profile))


# ----------------------------------------------------------------------------- the load order
class MoveParams(EntryRef):
    to: int  # 0-based position among its kind as the page shows them


class MoveResult(Result):
    moved: bool
    name: str = ""
    problem: str = ""  # why me3 would not keep it there (moved is False)
    decided_by: int = -1  # the entry whose options decide: "Edit options" opens it (-1: none)


@operation("mods.move", params=MoveParams, result=MoveResult, kind="command", writes=True)
def move(call: Call, p: MoveParams) -> MoveResult:
    idle(call.session)
    entry = entry_of(p.profile, p.index)
    with refusing("move_failed"):
        plan = profile_mods.move_entry(p.profile, entry["kind"], p.index, p.to, loc=call.session.locations())
    if plan.text is not None:
        return MoveResult(moved=True, name=entry["name"])
    by = next((e["index"] for e in mod_service.profile_entries(p.profile) if e["name"] == plan.decided_by), -1)
    return MoveResult(moved=False, name=entry["name"], problem=plan.problem, decided_by=by if plan.decided_by else -1)


@operation("mods.fix_order", params=ProfileRef, result=Changed, kind="command", writes=True)
def fix_order(call: Call, p: ProfileRef) -> Changed:
    """Put the mod that must stay last back last."""
    idle(call.session)
    with refusing("order_not_fixed"):
        problem = mod_order.fix(p.profile, loc=call.session.locations())
    if problem:
        raise OperationError("order_not_fixed", problem)
    return Changed(note="profile: fixed the order of the mod that must stay last")


# ----------------------------------------------------------------------------- renaming one mod
class RenameStart(Result):
    name: str  # the entry's folder name: where the Rename dialog starts ("" when the entry is gone)


@operation("mods.rename_start", params=EntryRef, result=RenameStart)
def rename_start(call: Call, p: EntryRef) -> RenameStart:
    entry = next((e for e in mod_service.profile_entries(p.profile) if e["index"] == p.index), None)
    return RenameStart(name="" if entry is None else mods_page.folder_name(p.profile, entry))


class RenameParams(EntryRef):
    name: str


class RenamePreview(Result):
    ok: bool
    lines: list[str]
    refusals: list[str]


@operation("mods.rename_preview", params=RenameParams, result=RenamePreview)
def rename_preview(call: Call, p: RenameParams) -> RenamePreview:
    """Whether renaming to the name is allowed and what it would change; nothing is written."""
    try:
        pre = profile_mods.rename_preview(p.profile, p.index, p.name, loc=call.session.locations())
    except Exception as e:
        return RenamePreview(ok=False, lines=[], refusals=[str(e)])
    return RenamePreview(ok=pre.ok, lines=list(pre.lines), refusals=list(pre.refusals))


def _entry_name(p: EntryRef) -> str:
    return next((e["name"] for e in mod_service.profile_entries(p.profile) if e["index"] == p.index), "")


def _check_entry(call: Call, p: EntryRef) -> None:
    entry_of(p.profile, p.index)


@operation(
    "mods.rename",
    params=RenameParams,
    result=Done,
    kind="job",
    writes=True,
    title=lambda p: tr("Renaming {name}...").format(name=_entry_name(p)),
    check=_check_entry,
)
def rename(call: Call, p: RenameParams) -> Done:
    old = _entry_name(p)
    run_logged_job(
        call.session.locations(),
        tr("Renaming {name}...").format(name=old),
        f"launcher: rename {old} to {p.name}",
        lambda loc: profile_mods.rename_mod(p.profile, p.index, p.name, loc=loc),
    )
    return Done(note=f"renamed {old} to {p.name}")


# ----------------------------------------------------------------------------- Mod options
class Dependency(Params):
    id: str
    optional: bool = False


class OptionsView(Result):
    """What the Mod options dialog shows for one entry. init_kind: 0 none, 1 call a function, 2 wait (ms); overlay: -1
    when it does not apply, else 0/1 (the parameter overlay set by hand)."""

    index: int
    name: str
    kind: str
    enabled: bool
    id: str
    load_after: list[Dependency]
    load_before: list[Dependency]
    optional: bool
    load_early: bool
    init_kind: int
    init_value: str
    finalizer: str
    others: list[str]
    overlay: int
    rebuild_file: str


@operation("mods.options", params=EntryRef, result=OptionsView)
def options(call: Call, p: EntryRef) -> OptionsView:
    entry = entry_of(p.profile, p.index)
    facts = profile_mods.options_facts(p.profile, entry)
    init = entry.get("initializer") or {}
    delay = init.get("delay") if isinstance(init.get("delay"), dict) else None

    def deps(key: str) -> list[Dependency]:
        return [Dependency(id=str(d["id"]), optional=bool(d.get("optional"))) for d in entry.get(key) or []]

    return OptionsView(
        index=p.index,
        name=entry["name"],
        kind=entry["kind"],
        enabled=entry.get("enabled", True) is not False,
        id=entry.get("id") or "",
        load_after=deps("load_after"),
        load_before=deps("load_before"),
        optional=bool(entry.get("optional")),
        load_early=bool(entry.get("load_early")),
        init_kind=1 if init.get("function") else 2 if delay is not None else 0,
        init_value=str(init.get("function") or (delay or {}).get("ms", "") or ""),
        finalizer=str(entry.get("finalizer") or ""),
        others=list(facts.others),
        overlay=-1 if facts.overlay is None else int(facts.overlay),
        rebuild_file=facts.rebuild_file,
    )


class OptionsInput(EntryRef):
    enabled: bool = True
    id: str = ""  # a package's id
    load_after: list[Dependency] = []
    load_before: list[Dependency] = []
    optional: bool = False  # natives from here on
    load_early: bool = False
    finalizer: str = ""
    init_kind: int = 0
    init_value: str = ""
    overlay: int = -1
    rebuild_file: str = ""


@operation("mods.save_options", params=OptionsInput, result=Changed, kind="command", writes=True)
def save_options(call: Call, p: OptionsInput) -> Changed:
    idle(call.session)
    entry = entry_of(p.profile, p.index)
    opts: dict[str, Any] = {
        "enabled": p.enabled,
        "load_after": [{"id": d.id, "optional": d.optional} for d in p.load_after],
        "load_before": [{"id": d.id, "optional": d.optional} for d in p.load_before],
    }
    if entry["kind"] == "package":
        opts["id"] = p.id.strip()
    else:
        value = p.init_value.strip()
        if p.init_kind == 2 and value and not value.isdigit():
            raise OperationError("invalid_wait", tr("The wait is a number of milliseconds."))
        opts["optional"], opts["load_early"], opts["finalizer"] = p.optional, p.load_early, p.finalizer.strip()
        opts["initializer"] = (
            {"function": value}
            if p.init_kind == 1 and value
            else {"delay": {"ms": int(value)}}
            if p.init_kind == 2 and value
            else None
        )
    with refusing("options_not_saved"):
        profile_mods.save_options(
            p.profile,
            p.index,
            entry,
            opts,
            loc=call.session.locations(),
            overlay=None if p.overlay == -1 else bool(p.overlay),
            rebuild_file=p.rebuild_file.strip(),
        )
    return Changed(note=f"profile: options saved for {entry['name']}", name=entry["name"])


# ----------------------------------------------------------------------------- the profile's own history and files
class VersionRow(Result):
    path: str
    when: str  # ISO time; the client formats it
    why: str


class VersionList(Result):
    versions: list[VersionRow]


@operation("mods.versions", params=ProfileRef, result=VersionList)
def versions(call: Call, p: ProfileRef) -> VersionList:
    return VersionList(
        versions=[
            VersionRow(path=str(v["path"]), when=v["when"].isoformat(timespec="minutes"), why=str(v.get("why") or ""))
            for v in profile_mods.versions(p.profile)
        ]
    )


class RestoreParams(ProfileRef):
    path: str  # one of mods.versions' paths


class Restored(Result):
    before: str | None  # the copy of the profile as it was: restoring it undoes this restore


@operation("mods.restore_version", params=RestoreParams, result=Restored, kind="command", writes=True)
def restore_version(call: Call, p: RestoreParams) -> Restored:
    idle(call.session)
    if p.path not in {str(v["path"]) for v in profile_mods.versions(p.profile)}:
        raise OperationError("unknown_version", tr("That earlier copy is no longer there."), {"path": p.path})
    with refusing("restore_failed"):
        before = profile_mods.restore_version(p.profile, p.path)
    return Restored(before=None if before is None else str(before))


class KindParams(ProfileRef):
    kind: str  # package | native


class Unlisted(Result):
    folders: list[dict[str, str]]  # {label, path}: in the profile's folders, loaded by no entry


@operation("mods.unlisted", params=KindParams, result=Unlisted)
def unlisted(call: Call, p: KindParams) -> Unlisted:
    return Unlisted(
        folders=[{"label": label, "path": str(path)} for label, path in profile_mods.unlisted(p.profile, p.kind)]
    )


class AddParams(KindParams):
    paths: list[str]


class Added(Result):
    names: list[str]
    loose_dlls: bool  # DLLs not in a folder of their own: the page offers to put them in folders


@operation("mods.add_existing", params=AddParams, result=Added, kind="command", writes=True)
def add_existing(call: Call, p: AddParams) -> Added:
    idle(call.session)
    with refusing("add_failed"):
        names = profile_mods.add_existing(p.profile, [Path(x) for x in p.paths], p.kind, loc=call.session.locations())
    return Added(names=names, loose_dlls=p.kind == "native" and bool(profile_mods.loose_dlls_of(Path(p.profile))))


# ----------------------------------------------------------------------------- Edit as text
class TextView(Result):
    text: str  # with LF line ends
    crlf: bool  # the file had CRLF: saving puts them back


@operation("mods.text", params=ProfileRef, result=TextView)
def read_text(call: Call, p: ProfileRef) -> TextView:
    try:
        raw = Path(p.profile).read_bytes()
    except OSError:
        raw = b""
    body = raw.decode("utf-8", errors="replace")
    return TextView(text=body.replace("\r\n", "\n"), crlf="\r\n" in body)


class CheckParams(Params):
    text: str


class TextCheck(Result):
    problem: str  # "" when it parses as TOML


def _toml_problem(body: str) -> str:
    try:
        tomllib.loads(body)
    except tomllib.TOMLDecodeError as e:
        return str(e)
    return ""


@operation("mods.check_text", params=CheckParams, result=TextCheck)
def check_text(call: Call, p: CheckParams) -> TextCheck:
    """The parse gate of the editor: pure, nothing is read from disk."""
    return TextCheck(problem=ModsPresenter.text_error(_toml_problem(p.text)))


class SaveTextParams(ProfileRef):
    text: str
    crlf: bool = False


@operation("mods.save_text", params=SaveTextParams, result=Changed, kind="command", writes=True)
def save_text(call: Call, p: SaveTextParams) -> Changed:
    """The profile as the player wrote it (a Version is kept first). Text that does not parse is refused."""
    idle(call.session)
    if why := _toml_problem(p.text):
        raise OperationError("invalid_toml", ModsPresenter.text_error(why), {"why": why})
    body = p.text.replace("\n", "\r\n") if p.crlf else p.text
    with refusing("profile_write_failed"):
        mod_service.save_profile_text(p.profile, body)
    return Changed(note="profile: saved as text")
