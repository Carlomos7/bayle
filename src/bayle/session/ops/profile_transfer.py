"""The Export / Import profile page's operations: the export listing, opening a file or a download's bundled profile
(a backend resource with an id), previewing, discarding, and export / import as jobs with typed progress.

Every operation is handed straight to the session's ProfileTransferService (services.profile_transfer), with no
wording. A plan is a check and a start: check_export gives the size to confirm, export(expect=) starts it, stale when
the mods changed since. Temporary, as for Settings: the Qt page calls the service itself."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel

from bayle.errors import OperationError
from bayle.services.profile_transfer import ProfileTransferService
from bayle.session.operations import Call, Params, Result, Session, operation, registry


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
    kind: str  # json | zip | bundled
    name: str = ""
    version: str = ""
    author: str = ""
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
    serial: int  # what ImportParams.expect confirms
    bundled: bool = False
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
    expect: int | None = None  # the preview serial the client looked at


class TransferJob(Result):
    job_id: str  # the job's result: export {path, size}, import {name}


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
    expect: int | None = None  # the size check_export gave and the client confirmed


class CheckExportParams(Params):
    profile: str
    kind: str = "list"
    chosen: list[str] = []


class ExportChecked(Result):
    size: int
    big: bool


def _none() -> ProfileTransferService:
    raise OperationError("no_profile_transfer_service", "This session has no Profile transfer page.")


def _svc(session: Session) -> ProfileTransferService:
    return session.service("profile_transfer", _none)


@registry.page("profile_transfer", scope=ListScope, view=ExportListing)
def listing(session: Session, profile: str = "") -> ExportListing:
    return ExportListing.model_validate(asdict(_svc(session).listing(profile)))


@operation("profile_transfer.open_file", params=OpenFile, result=Opened, kind="command", writes=True)
def open_file(call: Call, p: OpenFile) -> Opened:
    return Opened.model_validate(asdict(_svc(call.session).open_file(p.path)))


@operation("profile_transfer.open_bundled", params=OpenBundled, result=Opened, kind="command", writes=True)
def open_bundled(call: Call, p: OpenBundled) -> Opened:
    return Opened.model_validate(asdict(_svc(call.session).open_bundled(p.unpacked, p.profiles, p.staging)))


@operation("profile_transfer.preview", params=PreviewParams, result=PreviewView, kind="command")
def preview(call: Call, p: PreviewParams) -> PreviewView:
    got = _svc(call.session).preview(
        p.resource, p.profile, new_profile=p.new_profile, new_name=p.new_name, choices=p.choices, which=p.which
    )
    return PreviewView.model_validate(asdict(got))


@operation("profile_transfer.discard", params=ResourceRef, result=Discarded, kind="command", writes=True)
def discard(call: Call, p: ResourceRef) -> Discarded:
    return Discarded(found=_svc(call.session).discard(p.resource))


@operation("profile_transfer.import", params=ImportParams, result=TransferJob, kind="command", writes=True)
def import_(call: Call, p: ImportParams) -> TransferJob:
    return TransferJob(job_id=_svc(call.session).import_(p.resource, p.skip, expect=p.expect))


@operation("profile_transfer.check_export", params=CheckExportParams, result=ExportChecked, kind="command")
def check_export(call: Call, p: CheckExportParams) -> ExportChecked:
    return ExportChecked(**asdict(_svc(call.session).check_export(p.profile, p.kind, p.chosen)))


@operation("profile_transfer.export", params=ExportParams, result=TransferJob, kind="command", writes=True)
def export(call: Call, p: ExportParams) -> TransferJob:
    return TransferJob(job_id=_svc(call.session).export(**p.model_dump()))
