"""Renaming an installed mod's folder and id, as one undoable operation (technical specification §8.3).

The folder (a package's, a native's) is renamed on its own drive, the profile's entry points at the new place (a
package's id becomes the new name too, and the entries that load after or before it follow), and the launcher's own
records that name the folder (the profile's settings.json, launcher_settings.json) follow. All of it is steps of one
merging.build.Operation: every refusal is worked out first, nothing is written until commit, a failure or an
interruption puts everything back, and Undo takes it back (mods.operations.take_back). A native keeps its DLL's file
name: that is its id in me3 and the key of its attached configs.

Never changed: the merged build's record (the moved inputs no longer match it, so the next Play rebuilds), the records
of earlier operations (their Undo then says it can no longer be taken back), the version history.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from roundtable_souls import overhauls
from roundtable_souls.config import settings as launcher_settings
from roundtable_souls.formats import me3_profile
from roundtable_souls.merging import build
from roundtable_souls.mods import checks, naming, operations, profile_edit, profile_settings
from roundtable_souls.mods import order as mod_order
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.mods.profile_writer import Plan as WriterPlan
from roundtable_souls.mods.profile_writer import ProfileWriter
from roundtable_souls.platform import filelock

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "rename"  # the operation's kind in its journal, and the Activity undo record's type
GAME_OPEN = "Close the game first: it has these files open."


@dataclass
class RenamePreview:
    """What renaming does, worked out with nothing written."""

    profile: Path
    kind: str = ""
    old_name: str = ""
    new_name: str = ""
    old_folder: Path | None = None
    new_folder: Path | None = None
    writer: ProfileWriter | None = None
    change: WriterPlan | None = None
    files: list[tuple[Path, bytes, str]] = field(default_factory=list)  # (file, new bytes, sha256 it must still have)
    info: dict[str, Any] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals and self.change is not None


# ----------------------------------------------------------------------------- helpers
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canon(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _inside(inner: Path | str, outer: Path | str) -> bool:
    a, b = _canon(inner), _canon(outer)
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def _overlap(a: Path, b: Path) -> bool:
    return _inside(a, b) or _inside(b, a)


def _folder_of(profile: Path, entry: dict) -> Path:
    where = profile_edit.resolve(profile, entry["path"])
    return where if entry["kind"] == "package" else where.parent


def _swap_component(path: str, depth: int, old: str, new: str) -> str | None:
    """path with its depth-th component from the end (1: the last) changed from old to new; None when that component
    is not old."""
    parts = re.split(r"([\\/]+)", path)
    at = [i for i in range(0, len(parts), 2) if parts[i]]
    if len(at) < depth or parts[at[-depth]].lower() != old.lower():
        return None
    parts[at[-depth]] = new
    return "".join(parts)


def _deepest(folder: Path) -> int:
    return max((len(p.relative_to(folder).as_posix()) for p in folder.rglob("*") if p.is_file()), default=0)


def _remap(value: str, old: Path, new: Path) -> str:
    """A path inside the old folder as it is in the new one; any other string as it is."""
    try:
        rel = Path(os.path.abspath(value)).relative_to(os.path.abspath(old))
    except ValueError, OSError:
        return value
    return str(new / rel)


def _edit(w: ProfileWriter, idx: int, kind: str, path: str, from_refs: set[str], to: str | None) -> None:
    """The profile edits of a rename (and of taking it back): the entry's path, a package's id, and the entries that
    load after or before it. from_refs: the names the others may use for it; to: the id it gets."""
    others = w.entries()
    w.set_path(idx, path)
    if kind != "package" or not to:
        return
    w.set_options(idx, {"id": to})
    low = {r.lower() for r in from_refs}
    renamed = dict.fromkeys(from_refs, to)
    for e in others:
        if e["index"] == idx:
            continue
        opts = {
            key: mod_order.rename_refs(e[key], renamed)
            for key in ("load_after", "load_before")
            if any(str(d.get("id", "")).lower() in low for d in e[key])
        }
        if opts:
            w.set_options(e["index"], opts)


def _unknown_reference(value: Any, names: set[str], folder: str) -> bool:
    if isinstance(value, str):
        return value.lower() in names or folder in value.lower().replace("\\", "/")
    if isinstance(value, dict):
        return any(_unknown_reference(v, names, folder) for v in value.values())
    if isinstance(value, list):
        return any(_unknown_reference(v, names, folder) for v in value)
    return False


# ----------------------------------------------------------------------------- preview
def preview(profile: Path, index: int, new_name: str, *, loc: Locations) -> RenamePreview:
    """What renaming the entry `index` of profile to new_name (its folder and, for a package, its id) would do.
    Raises ModError when the profile or the entry can't be read; every other reason is a refusal."""
    profile = Path(profile)
    out = RenamePreview(profile)
    refuse = out.refusals.append
    writer = ProfileWriter(profile, loc)
    found = writer.entries()
    entry = next((e for e in found if e["index"] == index), None)
    if entry is None or not entry["path"]:
        raise ModError("That entry is not in the profile any more.")
    new_name = new_name.strip()
    kind = entry["kind"]
    folder = _folder_of(profile, entry)
    old_name = folder.name
    out.kind, out.old_name, out.new_name, out.old_folder = kind, old_name, new_name, folder
    if loc.game_running():
        refuse(GAME_OPEN)
    if (why := operations.problem(profile)) is not None:
        refuse(f"Another change to this profile is not finished: {why}")
    if not folder.is_dir():
        refuse(f"{old_name} is not a folder the launcher can rename: it is not there.")
        return out
    pk_root, nt_root = profile_edit.roots(profile, writer.text)
    if not any(checks.same_folder(folder.parent, r) for r in (pk_root, nt_root, profile.parent)):
        refuse(f"{old_name} is outside this profile's mod folders, so the launcher does not move it.")
    if old_name.lower() in naming.RESERVED:
        refuse(f"{old_name} is a folder the launcher uses itself.")
    # the new name
    case_only = new_name != old_name and new_name.lower() == old_name.lower()
    if not new_name:
        refuse("Type a new name.")
    elif new_name == old_name:
        refuse("That is already its name.")
    elif (why := naming.unsafe(new_name)) is not None:
        refuse(f"{new_name} can't be used: {why}.")
    elif new_name.lower() in naming.RESERVED:
        refuse(f"{new_name} is a folder the launcher uses itself.")
    else:
        if not case_only and any(p.name.lower() == new_name.lower() for p in folder.parent.iterdir()):
            refuse(f"There is already a folder called {new_name} in {folder.parent.name}.")
        if kind == "package" and any(
            me3_profile.entry_ref(e).lower() == new_name.lower()
            for e in found
            if e["kind"] == "package" and e["index"] != index
        ):
            refuse(f"Another mod in this profile already has the id {new_name}.")
        if any(
            e["index"] != index
            and e["path"]
            and _folder_of(profile, e).name.lower() == new_name.lower()
            and e["kind"] == kind
            for e in found
        ):
            refuse(f"Another entry in this profile already uses a folder called {new_name}.")
        out.new_folder = folder.with_name(new_name)
        if (why := naming.path_problem(out.new_folder, _deepest(folder))) is not None:
            refuse(why)
    # who else uses the folder
    for e in found:
        if e["index"] != index and e["path"] and _overlap(_folder_of(profile, e), folder):
            refuse(f"{e['name']} in this profile uses the same folder, so it can't be renamed on its own.")
    for other in sorted(profile.parent.glob("*.me3")):
        if _canon(other) == _canon(profile):
            continue
        try:
            rows = me3_profile.entries(me3_profile.read_text(other))
        except OSError, ValueError:
            continue
        if any(r["path"] and _overlap(_folder_of(other, r), folder) for r in rows):
            refuse(f"{other.name} uses this folder too: renaming it would break that profile.")
    if operations._shared_folder(folder):
        refuse(f"{old_name} holds Seamless Co-op, which other mods rely on by its name.")
    tgt = writer.target
    if tgt is not None and any(_overlap(folder, Path(p)) for p in (tgt["folder"], *tgt["own"])):
        refuse(f"{old_name} is the mod that must stay last, and its rebuild tool names its folder.")
    if overhauls.requirements.owner(overhauls.load(loc.game.key), kind, entry) is not None:
        refuse(f"{old_name} belongs to an overhaul, whose recipe and rebuild tool name it.")
    if out.refusals or out.new_folder is None:
        return out
    # what changes
    depth = 1 if kind == "package" else 2
    new_path = _swap_component(entry["path"], depth, old_name, new_name)
    if new_path is None:
        refuse(f"The path {entry['path']} does not end in {old_name}, so it can't be followed to the new name.")
        return out
    old_ref = me3_profile.entry_ref(entry) if kind == "package" else ""
    refs = {old_ref} if kind == "package" else set()
    if kind == "package" and not entry["id"]:
        refs.add(mod_order.me3_path_id(profile.parent, entry["path"]))
    out.info = {
        "kind": KIND,
        "name": old_name,
        "new": new_name,
        "dest": str(out.new_folder),
        "old": str(folder),
        "case_only": case_only,
        "entry_kind": kind,
        "old_path": entry["path"],
        "new_path": new_path,
        "old_id": entry["id"],
        "entries": [],
    }
    try:
        _edit(writer, index, kind, new_path, refs, new_name)
    except ModError as e:
        refuse(str(e))
        return out
    out.change = writer.plan(f"before renaming {old_name} to {new_name}")
    out.writer = writer
    mine = f"'{new_name}'" if kind == "package" else f"'{Path(entry['path']).name}'"
    out.change.refusals = unmoved(out.change.refusals, mine)
    out.refusals += [r.message for r in out.change.refusals]
    dependents = 0
    if kind == "package":
        low = {r.lower() for r in refs}
        dependents = sum(
            1
            for e in found
            if e["index"] != index
            and any(str(d.get("id", "")).lower() in low for d in (*e["load_after"], *e["load_before"]))
        )
    _files(out, profile, kind, refs, new_name)
    out.lines = [
        f"The folder {old_name} is renamed to {new_name}" + (" (the id too)" if kind == "package" else ""),
        f"{profile.name} points at the new name",
    ]
    if dependents:
        out.lines.append(f"{dependents} mod{'s' if dependents != 1 else ''} that load around it follow the new id")
    n = len(out.files)
    if n:
        out.lines.append(f"{n} launcher settings file{'s' if n != 1 else ''} follow{'' if n != 1 else 's'} it")
    out.lines.append("The merged files are rebuilt before the next Play. Undo puts everything back")
    return out


def _files(out: RenamePreview, profile: Path, kind: str, refs: set[str], new_name: str) -> None:
    """The launcher's own records that name the folder, as (file, new bytes, sha256 it has now)."""
    old, new = out.old_folder, out.new_folder
    assert old is not None and new is not None
    # the profile's settings.json: after_overlay names; anything else holding the id or the folder is unknown
    try:
        file = profile_settings._current(profile)
        data = profile_settings._read(file)
    except profile_settings.Unreadable as e:
        out.refusals.append(str(e))
        return
    mine = dict((data.get("profiles") or {}).get(profile.name) or {})
    names = {r.lower() for r in refs} | {out.old_name.lower()}
    rel = _canon(old).replace("\\", "/").lower()
    unknown = {k: v for k, v in mine.items() if k not in ("overlay", "after_overlay")}
    if _unknown_reference(unknown, names, rel):
        out.refusals.append(
            f"{file.name} holds a setting that names {out.old_name}, and this version does not know how to rename it."
        )
        return
    after = [str(x) for x in mine.get("after_overlay") or []]
    if kind == "package" and any(x.lower() in names for x in after):
        mine["after_overlay"] = [new_name if x.lower() in names else x for x in after]
        data = {**data, "profiles": {**data["profiles"], profile.name: mine}}
        raw = file.read_bytes() if file.is_file() else b""
        out.files.append((file, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode(), _sha(raw)))
    # launcher_settings.json: the attached configs of a DLL in the folder, the legacy parameter overlays
    cur = launcher_settings.load_settings()
    configs = {_remap(k, old, new): [_remap(v, old, new) for v in vs] for k, vs in cur.native_configs.items()}
    overlays = {
        k: ({**v, "package": _remap(v["package"], old, new)} if isinstance(v, dict) and v.get("package") else v)
        for k, v in cur.parameter_overlays.items()
    }
    if configs != cur.native_configs or overlays != cur.parameter_overlays:
        changed = launcher_settings.LauncherSettings.model_validate(
            {**cur.to_file(), "native_configs": configs, "parameter_overlays": overlays}
        )
        path = launcher_settings.settings_path()
        raw = path.read_bytes() if path.is_file() else b""
        out.files.append((path, json.dumps(changed.to_file(), indent=1).encode(), _sha(raw) if raw else "missing"))


def unmoved(refusals: list, mine: str) -> list:
    """The refusals without "whose folder is missing" about the entry being moved: its folder moves only when the
    operation commits (shortcut: matched on the writer's wording, as mods.profile_import does)."""
    return [r for r in refusals if not ("whose folder is missing" in r.message and mine in r.message)]


# ----------------------------------------------------------------------------- apply
def apply(p: RenamePreview, *, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Rename as previewed, as one operation. Returns {operation, profile, name, new}. Raises ModError."""
    if not p.ok or p.change is None or p.writer is None or p.old_folder is None or p.new_folder is None:
        raise ModError("; ".join(p.refusals) or "Nothing to rename.")
    old, new = p.old_folder, p.new_folder
    case_only = bool(p.info["case_only"])

    def refuse_now() -> str | None:
        if loc.game_running():
            return GAME_OPEN
        if not old.is_dir():
            return f"{old.name} is not there any more."
        if new.exists() and not case_only:
            return f"{new.name} appeared in {new.parent.name} meanwhile."
        return None

    settings_changed = any(f == launcher_settings.settings_path() for f, _d, _e in p.files)
    with operations.lock(p.profile):
        operations.recover(p.profile)
        if (why := operations.problem(p.profile)) is not None:
            raise ModError(f"Another change to this profile is not finished: {why}")
        with filelock.locked(launcher_settings.settings_path()) if settings_changed else nullcontext():
            op = operations.start(p.profile, f"rename of {p.old_name} to {p.new_name}")
            try:
                p.writer.commit(p.change, operation=op)
                for live, data, expect in p.files:
                    op.write_file(live, data, expect=expect)
                op.note(**p.info)
                if case_only:  # the same folder on Windows: out of the way first
                    aside = old.with_name(f".{old.name}.rename-{op.id}")
                    op.move_folder(old, aside)
                    op.move_folder(aside, new)
                else:
                    op.move_folder(old, new)  # last: every cheaper failure comes before the folder moves
            except BaseException:
                op.discard()
                raise
            try:
                op.commit(refuse=refuse_now)
            except build.BuildError as e:
                raise ModError(str(e)) from e
        for other in operations._active(p.profile):  # an earlier operation names a folder that is not there now
            if other.id != op.id and other.info.get("dest") and checks.same_folder(Path(other.info["dest"]), old):
                other.release()
        operations._release_others(op)
    log(f"renamed {p.old_name} to {p.new_name}")
    return {"operation": str(op.dir), "profile": str(p.profile), "name": p.old_name, "new": p.new_name}


# ----------------------------------------------------------------------------- taking one back
def profile_back(op: build.Operation, profile: Path, notes: list[str]) -> tuple[bytes, str] | None:
    """The profile's bytes once the rename is taken back, and the sha256 of its bytes now (operations.take_back):
    its exact earlier bytes when it has not changed since; else the entry is pointed back at the old folder and the
    id and the entries that named it follow, whatever else the player changed staying. None: leave it as it is."""
    step = operations._profile_step(op)
    if step is None:
        return None
    now = profile.read_bytes()
    expect = _sha(now)
    if now == (op.dir / step["after"]).read_bytes():
        return ((op.dir / step["before"]).read_bytes() if step["before"] else b""), expect
    notes.append(f"{profile.name} changed since, so only the rename was taken out of it")
    info = op.info
    w = ProfileWriter(profile)
    want = str(info["new_path"]).replace("\\", "/").lower()
    idx = next((e["index"] for e in w.entries() if e["path"].replace("\\", "/").lower() == want), None)
    if idx is None:
        notes.append(f"the entry is no longer in {profile.name}")
        return None
    _edit(w, idx, info["entry_kind"], info["old_path"], {info["new"]}, info["old_id"] or info["name"])
    plan = w.plan(f"before taking back the rename of {info['name']}")
    plan.refusals = unmoved(plan.refusals, f"'{info['old_id'] or info['name']}'")
    if plan.refusals:
        raise operations.OperationError("; ".join(r.message for r in plan.refusals))
    return plan.bytes_to_write, expect
