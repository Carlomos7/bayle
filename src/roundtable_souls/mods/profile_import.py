"""Importing a me3 profile a download ships (a modpack's .me3 beside its mods): its entries go into the current
profile, or into a new profile beside it, with the mods they point at copied in; one undoable operation.

The bundled profile is read as configuration only: nothing in the download runs, and only the folders its entries
point at are copied (a me3.exe or an installer beside them is not). Each entry's path is read relative to the
.me3's place in the download and points at its installed copy afterwards; an entry pointing outside the download, or
at nothing, is left out and said. Each entry keeps its options (enabled, load_early, initializer, finalizer,
load_after, load_before). A package id the profile already has is renamed (-2, -3, ...) and every load_after /
load_before naming it is changed with it; a DLL is never renamed (me3 names DLLs by file name: two switched-on DLLs
with one name are refused by the profile writer, as is a required dependency that would be missing). A folder name
already taken where the mods go gets -2 the same way.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.formats import me3_profile
from roundtable_souls.mods import naming, operations
from roundtable_souls.mods.profile_edit import ModError, roots
from roundtable_souls.mods.profile_writer import Plan as WriterPlan
from roundtable_souls.mods.profile_writer import ProfileWriter

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

JUNK = {"__MACOSX", "Thumbs.db", ".DS_Store"}
NEW_PROFILE = 'profileVersion = "v1"\n\n[[supports]]\ngame = "{game}"\n'


def bundled(unpacked: Path) -> list[str]:
    """The .me3 profiles in an unpacked download, as paths from its top (what plan["profiles_inside"] lists)."""
    unpacked = Path(unpacked)
    return sorted((m.relative_to(unpacked).as_posix() for m in unpacked.rglob("*.me3")), key=str.lower)


@dataclass
class ImportPreview:
    """What importing does, worked out with nothing written."""

    profile: Path  # the profile written: the current one, or the new one
    new: bool
    writer: ProfileWriter
    change: WriterPlan | None
    copies: list[tuple[Path, Path]]  # (a folder or DLL in the download, the folder it becomes)
    renamed: dict[str, str]  # package id in the bundled profile -> the id it gets
    skipped: list[str]
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals


def _inside(path: Path, top: Path) -> bool:
    try:
        path.relative_to(top)
    except ValueError:
        return False
    return True


def _refs(deps: list, renamed: dict[str, str]) -> list:
    """load_after / load_before with the renamed package ids changed."""
    low = {k.lower(): v for k, v in renamed.items()}
    return [{**d, "id": low.get(str(d.get("id", "")).lower(), d.get("id"))} for d in deps]


def preview_import(
    unpacked: Path, me3: str, current: Path, *, loc: Locations, new_name: str | None = None
) -> ImportPreview:
    """What importing the bundled profile me3 (its path in the unpacked download) would do: into current, or, with
    new_name, into a new profile of that name beside current. Raises ModError when it can't be read."""
    unpacked, current = Path(unpacked).resolve(), Path(current)
    source = (unpacked / me3).resolve()
    if not _inside(source, unpacked) or not source.is_file():
        raise ModError(f"{me3} is not in the download.")
    try:
        found = me3_profile.entries(me3_profile.read_text(source))
    except ValueError as e:
        raise ModError(f"{Path(me3).name} could not be read: {e}") from e
    if new_name:
        target = current.parent / f"{naming.mod_id(new_name)}.me3"
        if target.exists():
            raise ModError(f"There is already a profile named {target.name}.")
        writer = ProfileWriter.create(target, NEW_PROFILE.format(game=loc.game.key), loc=loc)
    else:
        target = current
        writer = ProfileWriter(target, loc)
    pk_root, nt_root = roots(target, writer.text)
    taken_ids = {str(e.get("id") or "").lower() for e in writer.entries() if e["kind"] == "package"}
    taken_dirs = {p.name.lower() for root in (pk_root, nt_root) if root.is_dir() for p in root.iterdir()}
    out = ImportPreview(target, bool(new_name), writer, None, [], {}, [])
    place: dict[Path, Path] = {}  # a folder (or lone DLL) in the download -> where it goes
    rows: list[tuple[dict, Path]] = []
    for e in found:
        path = (source.parent / e["path"]).resolve() if e["path"] else None
        if path is None or not _inside(path, unpacked) or not path.exists():
            out.skipped.append(f"{e['name']}: {e['path'] or 'no path'} is not in the download, so it is left out")
            continue
        if e["kind"] == "package":
            item = path
        else:  # a DLL brings its folder, unless it sits loose beside the profile or at the download's top
            item = path if path.parent in (source.parent, unpacked) else path.parent
        if item not in place:
            root = pk_root if e["kind"] == "package" else nt_root
            name = naming.unique(naming.mod_id(item.stem if item.is_file() else item.name), taken_dirs)
            taken_dirs.add(name)
            place[item] = root / name
            out.copies.append((item, root / name))
        dest = place[item]
        rows.append(
            (e, dest if e["kind"] == "package" else dest / (path.name if item.is_file() else path.relative_to(item)))
        )
        ident = str(e["id"] or "") if e["kind"] == "package" else ""
        if ident and ident.lower() in taken_ids:
            out.renamed[ident] = naming.unique(ident, taken_ids)
        if ident:
            taken_ids.add(out.renamed.get(ident, ident).lower())
    for e, live in rows:
        row = {
            k: e[k] for k in ("enabled", "optional", "load_early", "initializer", "finalizer") if e.get(k) is not None
        }
        row["load_after"] = _refs(e["load_after"], out.renamed)
        row["load_before"] = _refs(e["load_before"], out.renamed)
        if e["kind"] == "package":
            row["id"] = out.renamed.get(e["id"], e["id"]) if e["id"] else None
        row["path"] = live
        writer.add_entry(e["kind"], row, deepest=_deepest(live))
    if not rows:
        out.refusals.append(f"None of {Path(me3).name}'s entries point at mods in the download.")
        return out
    out.change = writer.plan(f"before importing {Path(me3).name}")
    # the imported folders are copied in only when the operation commits: "whose folder is missing" about one of
    # them is not a problem (shortcut: matched on the writer's wording, which test_mod_operations pins)
    coming = {f"'{out.renamed.get(e['id'], e['id'])}'" for e, _ in rows if e["kind"] == "package" and e["id"]}
    coming |= {f"'{live.name}'" for e, live in rows if e["kind"] == "native"}
    out.change.refusals = [
        r
        for r in out.change.refusals
        if not ("whose folder is missing" in r.message and any(c in r.message for c in coming))
    ]
    out.refusals += [r.message for r in out.change.refusals]
    out.lines = [
        (f"A new profile {target.name} is made beside {current.name}" if new_name else f"{target.name} gets")
        + f" {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} from {Path(me3).name}, with their options",
        *(f"{src.name} is copied into {dest}" for src, dest in out.copies),
        *(f"{old} is called {new}: {target.name} already has a mod with that id" for old, new in out.renamed.items()),
        *out.skipped,
        "Nothing in the download runs; your other mods are not touched",
    ]
    return out


def _deepest(path: Path) -> int:
    return (
        max((len(p.relative_to(path).as_posix()) for p in path.rglob("*") if p.is_file()), default=0)
        if path.is_dir()
        else 0
    )


def apply_import(preview: ImportPreview, *, log=lambda s: None) -> dict:
    """Import as previewed, as one operation. Returns {operation, profile, new}."""
    p = preview
    if not p.ok or p.change is None:
        raise ModError("; ".join(p.refusals) or "Nothing to import.")
    with operations.lock(p.profile):
        operations.recover(p.profile)
        op = operations.start(p.profile, f"import into {p.profile.name}")
        made = {}
        try:
            for src, dest in p.copies:
                staged = dest.with_name(f".{dest.name}.staging-{op.id}")
                if src.is_file():
                    staged.mkdir(parents=True)
                    shutil.copy2(src, staged / src.name)
                else:
                    shutil.copytree(src, staged, ignore=shutil.ignore_patterns(*JUNK))
                made[str(dest)] = operations.manifest(staged)
                op.replace_folder(dest, staged)
            p.writer.commit(p.change, operation=op)
            op.note(
                kind="profile-import",
                name=p.profile.name,
                new_profile=p.new,
                made=made,
                entries=[c.path for c in p.change.changes if c.action == "add" and c.path],
            )
        except BaseException:
            op.discard()
            raise
        operations.commit(op)
    log(f"imported {len(p.copies)} mod folder(s) into {p.profile.name}")
    return {"operation": str(op.dir), "profile": str(p.profile), "new": p.new}


def undo_import(op_dir: Path, log=lambda s: None) -> str:
    """Take an import back (operations.take_back); a profile it made goes too."""
    from roundtable_souls.merging import build

    op = build.Operation.load(Path(op_dir))
    profile = Path(op.info["profile"])
    said = operations.take_back(Path(op_dir), log)
    if op.info.get("new_profile") and profile.is_file() and not profile.read_bytes():
        profile.unlink()  # take_back gives a file it made its earlier bytes: none
    return said
