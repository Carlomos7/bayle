"""Export / Import profile over HTTP: the export listing, opening a file or a download's bundled profile (a backend
resource with an id), previewing, discarding, and export / import as jobs with typed progress, each handed straight to
the engine's ProfileTransferService (services.profile_transfer), with no wording. A plan is a check and a start:
check_export gives the size to confirm, export(expect=) starts it, stale when the mods changed since."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from bayle.api.deps import service
from bayle.api.models import Params, Result
from bayle.services.profile_transfer import ProfileTransferService

router = APIRouter(prefix="/profile_transfer", tags=["profile_transfer"])
Transfer = Annotated[ProfileTransferService, Depends(service("profile_transfer"))]


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


class OpenedResource(Result):
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


class PreviewImportParams(ResourceRef):
    profile: str
    new_profile: bool = True
    new_name: str = ""
    choices: dict[str, str] = {}
    which: int = 0  # a download with several profiles: which one


class PreviewView(Result):
    serial: int  # what ImportProfileParams.expect confirms
    bundled: bool = False
    cards: list[dict[str, Any]] = []
    skipped: list[str] = []
    notes: list[str] = []
    refusals: list[str] = []
    clashes: list[dict[str, Any]] = []
    lines: list[str] = []  # a download's profile: what importing does
    undecided: bool = False  # a clashing mod still waits for the player's pick
    ok: bool = False


class ResourceDiscarded(Result):
    found: bool


class ImportProfileParams(ResourceRef):
    skip: list[str] = []  # card keys left unticked
    expect: int | None = None  # the preview serial the client looked at


class TransferJob(Result):
    job_id: str  # the job's result: export {path, size}, import {name}


class ExportProfileParams(Params):
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


@router.get("", name="profile_transfer")
def page(s: Transfer, q: Annotated[ListScope, Query()]) -> ExportListing:
    return ExportListing.model_validate(asdict(s.listing(q.profile)))


@router.post("/open_file", name="profile_transfer_open_file")
def open_file(s: Transfer, p: OpenFile) -> OpenedResource:
    return OpenedResource.model_validate(asdict(s.open_file(p.path)))


@router.post("/open_bundled", name="profile_transfer_open_bundled")
def open_bundled(s: Transfer, p: OpenBundled) -> OpenedResource:
    return OpenedResource.model_validate(asdict(s.open_bundled(p.unpacked, p.profiles, p.staging)))


@router.post("/preview", name="profile_transfer_preview")
def preview(s: Transfer, p: PreviewImportParams) -> PreviewView:
    got = s.preview(
        p.resource, p.profile, new_profile=p.new_profile, new_name=p.new_name, choices=p.choices, which=p.which
    )
    return PreviewView.model_validate(asdict(got))


@router.post("/discard", name="profile_transfer_discard")
def discard(s: Transfer, p: ResourceRef) -> ResourceDiscarded:
    return ResourceDiscarded(found=s.discard(p.resource))


@router.post("/import", name="profile_transfer_import")
def import_(s: Transfer, p: ImportProfileParams) -> TransferJob:
    return TransferJob(job_id=s.import_(p.resource, p.skip, expect=p.expect))


@router.post("/check_export", name="profile_transfer_check_export")
def check_export(s: Transfer, p: CheckExportParams) -> ExportChecked:
    return ExportChecked(**asdict(s.check_export(p.profile, p.kind, p.chosen)))


@router.post("/export", name="profile_transfer_export")
def export(s: Transfer, p: ExportProfileParams) -> TransferJob:
    return TransferJob(job_id=s.export(**p.model_dump()))
