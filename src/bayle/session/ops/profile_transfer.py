"""The Export / Import profile page's operations: the export listing, opening a file or a download's bundled profile
(a backend resource with an id), previewing, discarding, and export / import as jobs with typed progress."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bayle.errors import Cancelled, OperationError
from bayle.mods import naming
from bayle.platform import logging as run_logging
from bayle.platform.text import tr
from bayle.services import mods as mod_service
from bayle.services import profile_transfer as pt
from bayle.services.settings import load_settings
from bayle.services.transfer_resources import Resource, TransferResources
from bayle.session.operations import Call, Params, Result, Session, operation, registry
from bayle.views.profile_transfer import ProfileTransferPresenter
from bayle.work.jobs import JobContext
from bayle.work.prompts import Proposal
from bayle.work.runner import run_job_result


class ListScope(Params):
    profile: str = ""  # the .me3 whose mods the export lists


class ModRow(BaseModel):
    key: str
    name: str
    enabled: bool
    size: int


class ExportListing(Result):
    mods: list[ModRow]
    save_name: str = ""  # the save this profile plays on, "" when none


class ResourceRef(Params):
    resource: str


class Opened(Result):
    resource: str
    file: str = ""  # one line about the file (name, version, author, kind)
    is_zip: bool = False
    folder: str = ""  # where the file is
    readme: str = ""
    new_profile: bool = True
    new_name: str = ""
    names: list[str] = []  # a download's .me3 paths


class OpenFile(Params):
    path: str


class OpenBundled(Params):
    unpacked: str
    profiles: list[str]
    staging: str = ""  # deleted with the resource


class PreviewParams(ResourceRef):
    profile: str
    new_profile: bool = True
    new_name: str = ""
    choices: dict[str, str] = {}
    which: int = 0  # a download with several profiles: which one


class PreviewView(Result):
    cards: list[dict[str, Any]] = []
    skipped: list[str] = []
    notes: list[str] = []
    refusals: list[str] = []
    clashes: list[dict[str, Any]] = []
    lines: list[str] = []  # a download's profile: what importing does
    undecided: bool = False  # a clashing mod still waits for the player's pick
    ok: bool = False


class Discarded(Result):
    found: bool


class ImportParams(ResourceRef):
    skip: list[str] = []  # card keys left unticked


class ImportResult(Result):
    name: str


class ExportParams(Params):
    profile: str
    kind: str = "list"  # list | full
    name: str
    version: str = ""
    author: str = ""
    readme: str = ""
    changelog: str = ""
    chosen: list[str] = []
    folder: str
    with_configs: bool = True
    with_save: bool = False
    password: bool = False


class BigExportParams(ExportParams):
    size: int  # the bytes the ticked mods hold


class ExportResult(Result):
    path: str
    size: int


def _resources(session: Session) -> TransferResources:
    return session.service("transfer_resources", TransferResources)


def _failed(code: str, e: Exception) -> OperationError:
    return OperationError(code, str(e) or type(e).__name__)


@registry.page("profile_transfer", scope=ListScope, view=ExportListing)
def listing(session: Session, profile: str = "") -> ExportListing:
    if not profile:
        return ExportListing(mods=[])
    path = Path(profile)
    save = pt.save_candidate(path, loc=session.locations())
    mods = [
        ModRow(key=i.key, name=i.entry["name"], enabled=bool(i.entry["enabled"]), size=i.size)
        for i in pt.items(path, full=True)
    ]
    return ExportListing(mods=mods, save_name=save.name if save else "")


@operation("profile_transfer.open_file", params=OpenFile, result=Opened, kind="command", writes=True)
def open_file(call: Call, p: OpenFile) -> Opened:
    """Read a share list or a full export; a zip's skeleton is unpacked into the launcher's temp folder (the resource)."""
    try:
        incoming = pt.read(Path(p.path), loc=call.session.locations())
    except OperationError:
        raise
    except Exception as e:
        raise _failed("unreadable", e) from e
    res = _resources(call.session).add(incoming=incoming)
    return Opened(
        resource=res.id,
        file=ProfileTransferPresenter().file_line(incoming),
        is_zip=incoming.kind == "zip",
        folder=str(incoming.path.parent),
        readme=incoming.readme,
        new_profile=incoming.kind == "zip",
        new_name=incoming.share.name or incoming.path.stem,
    )


@operation("profile_transfer.open_bundled", params=OpenBundled, result=Opened, kind="command", writes=True)
def open_bundled(call: Call, p: OpenBundled) -> Opened:
    """Take over a download's unpacked folder and its staging folder; both are let go with the resource."""
    res = _resources(call.session).add(
        unpacked=Path(p.unpacked), staging=Path(p.staging) if p.staging else None, names=list(p.profiles)
    )
    return Opened(resource=res.id, names=res.names, new_name=Path(p.profiles[0]).stem if p.profiles else "")


def _view(res: Resource, prev: Any, new_profile: bool) -> PreviewView:
    pres = ProfileTransferPresenter()
    if res.bundled:
        return PreviewView(
            lines=list(prev.lines),
            refusals=list(prev.refusals),
            clashes=pres.clashes(prev, new_profile),
            undecided=bool(prev.undecided),
            ok=bool(prev.ok),
        )
    zp = prev.zip_preview
    return PreviewView(
        cards=pres.cards(prev),
        skipped=list(prev.skipped),
        notes=list(prev.notes),
        refusals=list(prev.refusals),
        clashes=pres.clashes(zp, new_profile) if zp else [],
        undecided=bool(zp and zp.undecided),
        ok=not prev.refusals,
    )


@operation("profile_transfer.preview", params=PreviewParams, result=PreviewView, kind="command")
def preview(call: Call, p: PreviewParams) -> PreviewView:
    """What importing would do, file by file; nothing is written. The preview is kept on the resource for the import."""
    session = call.session
    res = _resources(session).get(p.resource)
    loc, profile, name = session.locations(), Path(p.profile), p.new_name.strip()
    new = p.new_profile and (res.bundled or res.incoming is not None and res.incoming.kind == "zip")
    if new and not (naming.mod_id(name) if name else ""):
        raise OperationError("name_needed", tr("Give the new profile a name."))
    try:
        if res.incoming is not None:
            prev = pt.preview(
                res.incoming,
                profile,
                loc=loc,
                settings=load_settings(),
                new_name=name if new else None,
                choices=dict(p.choices),
            )
        else:
            if not 0 <= p.which < len(res.names) or res.unpacked is None:
                raise OperationError("not_found", tr("That profile is not in the download."))
            prev = mod_service.preview_profile_import(
                res.unpacked,
                res.names[p.which],
                profile,
                loc=loc,
                new_name=name if new else None,
                choices=dict(p.choices),
            )
    except OperationError:
        raise
    except Exception as e:
        raise _failed("preview_failed", e) from e
    res.preview = prev
    return _view(res, prev, p.new_profile)


@operation("profile_transfer.discard", params=ResourceRef, result=Discarded, kind="command", writes=True)
def discard(call: Call, p: ResourceRef) -> Discarded:
    return Discarded(found=_resources(call.session).discard(p.resource))


def _logged(session: Session, title: str, fn: Callable[[], Any]) -> Any:
    """fn as a logged job of its own (its log, jobs-index record and Undo as before); its error or stop is re-raised."""
    done = run_job_result(lambda _launch, _loc: fn(), None, session.locations(), title)
    if done.state == "done":
        return done.result
    if done.state == "cancelled":
        raise Cancelled()
    raise OperationError.from_info(done.error)


@operation("profile_transfer.import", params=ImportParams, result=ImportResult, kind="job", writes=True)
def import_(call: Call, p: ImportParams) -> ImportResult:
    """Write the ticked cards (or the download's profile) as one undoable operation; the resource is let go when it worked.
    Progress is the bytes of the zip's mods unpacked."""
    session, ctx = call.session, call.job
    resources = _resources(session)
    prev = resources.get(p.resource).preview
    if prev is None:
        raise OperationError("no_preview", tr("Preview the file first."))
    bundled = resources.get(p.resource).bundled
    loc = session.locations()

    def progress(done: int, total: int) -> None:
        if ctx is not None:
            ctx.progress(done, total)

    def work() -> ImportResult:
        try:
            if bundled:
                run_logging.start_log(f"launcher: import profile {prev.profile.name}", loc.game.key)
                out = mod_service.import_profile(prev)
            else:
                run_logging.start_log(f"launcher: import a shared profile into {prev.profile.name}", loc.game.key)
                out = pt.apply(prev, set(p.skip), progress=progress)
        except OperationError:
            raise
        except Exception as e:
            raise _failed("import_failed", e) from e
        return ImportResult(name=Path(out["profile"]).name)

    got = _logged(session, tr("Importing a profile..."), work)
    resources.discard(p.resource)
    return got


def _export(ctx: JobContext | None, session: Session, p: ExportParams) -> ExportResult:
    loc, profile = session.locations(), Path(p.profile)
    args: dict[str, Any] = dict(
        loc=loc,
        settings=load_settings(),
        name=p.name.strip(),
        version=p.version.strip(),
        author=p.author.strip(),
        password=p.password,
    )

    def report(done: int, total: int, current: str, n: int, count: int) -> None:
        if ctx is not None:
            ctx.progress(done, total, current, {"n": n, "count": count})

    def work() -> ExportResult:
        run_logging.start_log(f"launcher: export profile {args['name']}", loc.game.key)
        try:
            if p.kind == "full":
                out = pt.full_export(
                    profile,
                    progress=report,
                    cancelled=ctx.cancelled if ctx else lambda: False,
                    readme=p.readme,
                    changelog=p.changelog,
                    chosen=set(p.chosen),
                    out_dir=Path(p.folder),
                    with_configs=p.with_configs,
                    with_save=p.with_save,
                    **args,
                )
            else:
                doc, _ = pt.share_list(profile, **args)
                if not p.with_configs:
                    doc["configs"] = {}
                out = pt.write_share_list(doc, Path(p.folder))
        except pt.ExportCancelled:
            run_logging.log("export cancelled; the partial zip was removed")
            raise Cancelled() from None
        except OperationError:
            raise
        except Exception as e:
            raise _failed("export_failed", e) from e
        return ExportResult(path=str(out), size=out.stat().st_size)

    return _logged(session, tr("Exporting a profile..."), work)


@operation("profile_transfer.export", params=ExportParams, result=ExportResult, kind="job", writes=True)
def export(call: Call, p: ExportParams) -> ExportResult:
    """Write a share list or a full export. A full one reports bytes written (detail: file n of count) and stops at
    the next chunk when the job is cancelled; the partial zip is removed."""
    return _export(call.job, call.session, p)


@operation("profile_transfer.confirm_export", params=BigExportParams, result=ExportResult, kind="plan", writes=True)
def confirm_export(call: Call, p: BigExportParams) -> Proposal:
    """A big full export is asked about once; answering the plan starts the export job."""
    session = call.session
    words = ProfileTransferPresenter().confirm_big(p.size, tr("Export"))
    params = ExportParams.model_validate(p.model_dump(exclude={"size"}))

    def run(_answer) -> str:
        return session.start(lambda ctx: _export(ctx, session, params), title=tr("Exporting a profile..."))

    return Proposal(words, run)
