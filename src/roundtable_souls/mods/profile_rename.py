"""Renaming a profile (its .me3) and duplicating it, each as one undoable operation (technical specification §8.10).

me3 knows a profile by its file name only, so nothing inside the file changes, but the launcher keys several things by
the profile's path or name. A rename moves them together:

    in the journal    the .me3, its <name>.offline.me3 and .me3.bak (beside it, or in .roundtable/backups), the
                      profile's entry in .roundtable/settings.json, and (a library profile) the folders under
                      builds/<what>/<name>/ with the paths in the .me3 that point into them. Files are written under
                      the new name and removed from the old (their bytes are kept in the journal); folders are moved
                      (merging.build.Operation.move_folder: nothing is ever deleted by an older launcher's rollback).
    after the commit  launcher_settings.json (the remembered profile of the game, the parameter overlay marks) and
                      the profile's history copies, which are copied, not moved. Re-keyed by a mapping that can be
                      applied twice (a recovery after an interruption does, finish_state), and mapped back by an undo.

Steam shortcuts name the game they play, not a profile, so they need no change. Earlier operations on the profile keep
their old path: their Undo then says it can no longer be taken back.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.config import settings as launcher_settings
from roundtable_souls.formats import me3_profile
from roundtable_souls.merging import build
from roundtable_souls.mods import history, library, naming, operations
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.mods.profile_writer import ProfileWriter

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "profile-rename"  # the operation's kind in its journal, and the Activity undo record's type
GAME_OPEN = "Close the game first: it has these files open."
OFFLINE = ".offline.me3"
GENERATED = ("-default", ".offline")  # name endings me3 and the launcher give their own files


class ProfileRenameError(ModError):
    pass


@dataclass
class ProfileRenamePreview:
    """What renaming a profile does, worked out with nothing written."""

    profile: Path
    new_profile: Path | None = None
    old_name: str = ""
    new_name: str = ""
    case_only: bool = False
    moves: list[tuple[Path, Path]] = field(default_factory=list)  # (old, new) files moved as they are, .me3 first
    builds: list[tuple[Path, Path]] = field(default_factory=list)  # build folders renamed with the profile
    profile_bytes: bytes = b""  # the .me3 as it is now
    new_bytes: bytes = b""  # and as it is under the new name
    settings: tuple[Path, bytes, bytes] | None = None  # (settings.json, its bytes now, its bytes re-keyed)
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals and self.new_profile is not None


# ----------------------------------------------------------------------------- helpers
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canon(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _clean(name: str) -> str:
    name = name.strip()
    return name[:-4].rstrip() if name.lower().endswith(".me3") else name


def name_problem(profile: Path, name: str) -> str | None:
    """Why `name` can't be the profile's new name (plain words), or None. Cheap: reads the folder, nothing else."""
    profile = Path(profile)
    name = _clean(name)
    if not name:
        return "Type a new name."
    if name == profile.stem:
        return "That is already its name."
    if (why := naming.unsafe(name)) is not None:
        return f"{name} can't be used: {why}."
    if name.lower() in naming.RESERVED or name.lower().endswith(GENERATED):
        return f"{name} is a name the launcher or me3 uses itself."
    target = profile.with_name(name + ".me3")
    if name.lower() != profile.stem.lower():
        try:
            taken = any(p.name.lower() == target.name.lower() for p in profile.parent.iterdir())
        except OSError:
            taken = target.exists()
        if taken:
            return f"There is already a profile called {name}."
    return naming.path_problem(target, 0)


def _build_folders(profile: Path) -> list[Path]:
    lib = library.library_of(profile)
    if lib is None or not lib.builds.is_dir():
        return []
    return [
        lib.builds / w / profile.stem for w in library._folders(lib.builds) if (lib.builds / w / profile.stem).is_dir()
    ]


def _inside(inner: Path, outer: Path) -> bool:
    a, b = _canon(inner), _canon(outer)
    return a == b or a.startswith(b + os.sep)


def _siblings(profile: Path, new: Path) -> list[tuple[Path, Path]]:
    old_state, new_state = library.state_of(profile), library.state_of(new)
    pairs = [
        (profile.with_name(profile.stem + OFFLINE), new.with_name(new.stem + OFFLINE)),
        (profile.with_name(profile.name + ".bak"), new.with_name(new.name + ".bak")),
        (old_state.backups / (profile.name + ".bak"), new_state.backups / (new.name + ".bak")),
    ]
    return [(a, b) for a, b in pairs if a.is_file()]


def _rekeyed(data: dict, old: str, new: str) -> dict:
    """data with the profile's settings under the new name, at the same place in the file."""
    profiles = data.get("profiles") or {}
    return {**data, "profiles": {(new if k == old else k): v for k, v in profiles.items()}}


def _dump(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


# ----------------------------------------------------------------------------- preview
def preview(profile: Path, new_name: str, *, loc: Locations) -> ProfileRenamePreview:
    """What renaming the profile to new_name does. Raises ProfileRenameError when the profile can't be read; every
    other reason is a refusal."""
    profile = Path(profile)
    out = ProfileRenamePreview(profile, old_name=profile.stem, new_name=_clean(new_name))
    refuse = out.refusals.append
    if not profile.is_file():
        raise ProfileRenameError(f"{profile.name} is not there any more.")
    if profile.name.lower().endswith("-default.me3") or profile.name.lower().endswith(OFFLINE):
        refuse(f"{profile.name} is made by me3 itself, so it can't be renamed.")
        return out
    if loc.game_running():
        refuse(GAME_OPEN)
    if (why := operations.problem(profile)) is not None:
        refuse(f"Another change to this profile is not finished: {why}")
    if (why := name_problem(profile, out.new_name)) is not None:
        refuse(why)
        return out
    new = profile.with_name(out.new_name + ".me3")
    out.new_profile = new
    out.case_only = _canon(new) == _canon(profile)
    out.profile_bytes = profile.read_bytes()
    out.moves = [(profile, new), *_siblings(profile, new)]
    for _old, dest in out.moves[1:]:
        if dest.exists() and not out.case_only:
            refuse(f"{dest.name} is already there, so the launcher does not overwrite it.")
    # the folders named after the profile, and the paths in the .me3 that point into them
    lib = library.library_of(profile)
    out.new_bytes = out.profile_bytes
    found = _build_folders(profile)
    if found and lib is not None:
        try:
            out.new_bytes = _repoint(profile, found, out, lib)
        except ModError as e:
            refuse(str(e))
    # the profile's own settings (settings.json is shared by the folder's profiles, keyed by file name)
    try:
        file = ps._current(profile)
        data = ps._read(file)
    except ps.Unreadable as e:
        refuse(str(e))
        return out
    profiles = data.get("profiles") or {}
    if profile.name in profiles:
        if new.name in profiles:
            refuse(f"{file.name} already holds settings for a profile called {new.name}.")
        else:
            out.settings = (file, file.read_bytes(), _dump(_rekeyed(data, profile.name, new.name)))
    out.lines = [
        f"{profile.name} is renamed to {new.name}",
        "Its settings, backup copy and version history follow it; the mods are not moved or copied",
    ]
    if out.builds:
        out.lines.append(f"{len(out.builds)} build folder{'s' if len(out.builds) != 1 else ''} named after it follow")
    out.lines.append("Undo puts everything back")
    return out


def _repoint(profile: Path, found: list[Path], out: ProfileRenamePreview, lib: library.ModLibrary) -> bytes:
    """The .me3's bytes with each entry that points into a build folder named after the profile pointing at the folder
    under the new name (a package keeps the id it had). Fills out.builds."""
    new_stem = out.new_name
    writer = ProfileWriter(profile)
    before = {r.message for r in writer.plan("before").refusals}
    for folder in found:
        out.builds.append((folder, folder.with_name(new_stem)))
        if folder.with_name(new_stem).exists() and _canon(folder.with_name(new_stem)) != _canon(folder):
            raise ModError(f"{folder.with_name(new_stem)} is already there, so the launcher does not overwrite it.")
    for e in writer.entries():
        if not e["path"]:
            continue
        where = Path(os.path.abspath(me3_profile.resolve(profile, e["path"])))
        hit = next((f for f in found if _inside(where, f)), None)
        if hit is None:
            continue
        if e["kind"] == "package" and not e["id"]:
            writer.set_options(e["index"], {"id": me3_profile.entry_ref(e)})
        rel = where.relative_to(hit)
        writer.set_path(e["index"], os.path.relpath(hit.with_name(new_stem) / rel, profile.parent).replace("\\", "/"))
    plan = writer.plan(f"before renaming {profile.name}")
    # the folder moves only when the operation commits: "folder is missing" is not a reason to refuse
    left = [r.message for r in plan.refusals if r.message not in before and "whose folder is missing" not in r.message]
    if left:
        raise ModError("; ".join(left))
    return plan.bytes_to_write


# ----------------------------------------------------------------------------- the file moves
def _move(op: build.Operation, old: Path, new: Path, data: bytes, case_only: bool) -> None:
    """old's bytes under the new name, old removed (a case-only change goes through a name in between: on Windows both
    are one file)."""
    sha = _sha(old.read_bytes())
    if case_only:
        aside = old.with_name(f".{old.name}.rename-{op.id}")
        op.write_file(aside, data, expect="missing")
        op.write_file(old, None, expect=sha)
        op.write_file(new, data, expect="missing")
        op.write_file(aside, None, expect=_sha(data))
    else:
        op.write_file(new, data, expect="missing")
        op.write_file(old, None, expect=sha)


# ----------------------------------------------------------------------------- apply
def apply(p: ProfileRenamePreview, *, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Rename as previewed, as one operation. Returns {operation, profile, name, new, notes}. Raises ProfileRenameError
    (or merging.build.BuildError when something changed meanwhile) with nothing changed."""
    if not p.ok or p.new_profile is None:
        raise ProfileRenameError("; ".join(p.refusals) or "Nothing to rename.")
    old, new = p.profile, p.new_profile

    def refuse_now() -> str | None:
        if loc.game_running():
            return GAME_OPEN
        if any(dest.exists() for _o, dest in [*p.moves, *p.builds] if not p.case_only):
            return "A file with the new name appeared meanwhile."
        return None

    with operations.lock(old):
        operations.recover(old)
        if (why := operations.problem(old)) is not None:
            raise ProfileRenameError(f"Another change to this profile is not finished: {why}")
        if not old.is_file() or old.read_bytes() != p.profile_bytes:
            raise ProfileRenameError(f"{old.name} changed since the preview; try again.")
        op = operations.start(old, f"rename of profile {p.old_name} to {p.new_name}")
        try:
            for src, dest in p.moves:
                _move(op, src, dest, p.new_bytes if src == old else src.read_bytes(), p.case_only)
            if p.settings is not None:
                file, now, rekeyed = p.settings
                op.write_file(file, rekeyed, expect=_sha(now))
            for src, dest in p.builds:
                if p.case_only:
                    aside = src.with_name(f".{src.name}.rename-{op.id}")
                    op.move_folder(src, aside)
                    op.move_folder(aside, dest)
                else:
                    op.move_folder(src, dest)
            op.note(
                kind=KIND,
                name=p.old_name,
                new=p.new_name,
                profile=str(new),
                old_profile=str(old),
                game=loc.game.key,
                moves=[{"old": str(a), "new": str(b)} for a, b in p.moves],
                builds=[{"old": str(a), "new": str(b)} for a, b in p.builds],
                settings=str(p.settings[0]) if p.settings else "",
                new_sha=_sha(p.new_bytes),
                state_done=False,
            )
        except BaseException:
            op.discard()
            raise
        try:
            op.commit(refuse=refuse_now)
        except build.BuildError as e:
            raise ProfileRenameError(str(e)) from e
        notes = finish_state(op)
    log(f"renamed profile {p.old_name} to {p.new_name}")
    return {"operation": str(op.dir), "profile": str(new), "name": p.old_name, "new": p.new_name, "notes": notes}


# ----------------------------------------------------------------------------- the launcher's records
def finish_state(op: build.Operation) -> list[str]:
    """Re-key the launcher's own records for a rename that is done, then say so in its journal. Safe to run again.
    Returns what could not be moved, in plain words."""
    state = library.state_of(Path(op.info["profile"]))
    with build.ops_lock(state.root, ops=library.OPS):
        notes = _apply_state(op.info)
        op.note(state_done=True)
    return notes


def _apply_state(info: dict, *, back: bool = False) -> list[str]:
    from roundtable_souls.mods.backends import builtin
    from roundtable_souls.mods.rebuild import _key

    old, new = Path(info["old_profile"]), Path(info["profile"])
    if back:
        old, new = new, old
    game = info["game"]
    notes: list[str] = []

    def change(cur):
        out: dict = {}
        marks = {(_key(new) if k == _key(old) else k): v for k, v in cur.parameter_overlays.items()}
        if marks != cur.parameter_overlays:
            out["parameter_overlays"] = marks
        now = launcher_settings.game_setting(cur, game, "setup")
        if now and os.path.normcase(str(now)) == os.path.normcase(str(old)):
            if game == "eldenring":
                out["setup"] = str(new)
            else:
                out["games"] = {**cur.games, game: {**(cur.games.get(game) or {}), "setup": str(new)}}
        return out

    try:
        launcher_settings.change_settings(change)
    except OSError as e:
        notes.append(f"The launcher's settings could not be updated ({e})")
    for src, dest in (
        (history.folder(old), history.folder(new)),
        (builtin.history_root(old), builtin.history_root(new)),
    ):
        try:
            if src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
        except OSError as e:
            notes.append(f"The version history of {new.name} could not be copied ({e})")
    return notes


# ----------------------------------------------------------------------------- taking it back
def undo_rename(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Put the profile and what follows it back (see the module notes). Raises ProfileRenameError, nothing changed,
    when the old name is taken again or the renamed profile changed in a way that makes the folders unsafe to move."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise ProfileRenameError("This rename can no longer be taken back.")
    old, new = Path(info["old_profile"]), Path(info["profile"])
    case_only = _canon(old) == _canon(new)
    moves = [(Path(m["new"]), Path(m["old"])) for m in info["moves"]]
    builds = [(Path(m["new"]), Path(m["old"])) for m in info["builds"]]
    with operations.lock(new):
        if not new.is_file():
            raise ProfileRenameError(f"{new.name} is not there any more, so the rename can't be taken back.")
        if builds and _sha(new.read_bytes()) != info["new_sha"]:
            raise ProfileRenameError(
                f"{new.name} changed after it was renamed, and it points at the renamed build folders. Undoing would "
                "break it, so everything is left as it is."
            )
        for src, dest in moves:
            if src.exists() and dest.exists() and not case_only:
                raise ProfileRenameError(f"{dest.name} is there again; undoing would overwrite it.")
        for src, dest in builds:
            if not src.is_dir() or (dest.exists() and not case_only):
                raise ProfileRenameError(f"{dest.name} is not where the rename left it, so nothing was changed.")
        back = operations.start(new, f"undo of the rename of profile {info.get('name', '')}")
        try:
            for i, (src, dest) in enumerate(moves):
                if not src.is_file():
                    continue
                data = src.read_bytes()
                if i == 0 and _sha(data) == info["new_sha"]:  # not changed since: its exact earlier bytes
                    step = next(s for s in op.steps if s["type"] == "file" and s["live"] == str(dest) and s["before"])
                    data = (op.dir / step["before"]).read_bytes()
                _move(back, src, dest, data, case_only)
            if info.get("settings"):
                _settings_back(op, back, Path(info["settings"]), old.name, new.name)
            for src, dest in builds:
                if case_only:
                    aside = src.with_name(f".{src.name}.rename-{back.id}")
                    back.move_folder(src, aside)
                    back.move_folder(aside, dest)
                else:
                    back.move_folder(src, dest)
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()  # an undo is final
        op.release()
    for n in _apply_state(info, back=True):
        log(f"undo: {n}")
    return f"took back the rename of {info.get('name', 'the profile')}: it is called {old.stem} again"


def _settings_back(op: build.Operation, back: build.Operation, file: Path, old: str, new: str) -> None:
    """The settings file with the profile's entry under its old name: the exact earlier bytes when the file is as the
    rename left it, else the same re-keying of what it holds now."""
    step = next((s for s in op.steps if s["type"] == "file" and s["live"] == str(file) and s["after"]), None)
    now = file.read_bytes()
    if step is not None and step["before"] and now == (op.dir / step["after"]).read_bytes():
        data = (op.dir / step["before"]).read_bytes()
    else:
        data = _dump(_rekeyed(ps._read(file), new, old))
    back.write_file(file, data, expect=_sha(now))


# ----------------------------------------------------------------------------- duplicating
def copy_name(profile: Path) -> str:
    """ "<name> copy", then "<name> copy 2", ... not taken (case aside) in the profile's folder."""
    profile = Path(profile)
    taken = {p.name.lower() for p in profile.parent.iterdir()} if profile.parent.is_dir() else set()
    base = re.sub(r"( copy( \d+)?)$", "", profile.stem) + " copy"
    name, n = base, 2
    while name.lower() + ".me3" in taken:
        name, n = f"{base} {n}", n + 1
    return name


def duplicate(profile: Path, *, loc: Locations, name: str = "", log: Callable[[str], None] = lambda s: None) -> dict:
    """Copy the .me3 as `name` (default: copy_name), one operation. The mod folders are not copied: the copy points at
    the same ones (a library profile's own build folders stay with the original). Returns {operation, profile, name}."""
    profile = Path(profile)
    name = _clean(name) or copy_name(profile)
    if loc.game_running():
        raise ProfileRenameError(GAME_OPEN)
    if not profile.is_file():
        raise ProfileRenameError(f"{profile.name} is not there any more.")
    if profile.name.lower().endswith("-default.me3"):
        raise ProfileRenameError(f"{profile.name} is made by me3 itself, so it can't be duplicated.")
    if (why := name_problem(profile, name)) is not None:
        raise ProfileRenameError(why)
    if _build_folders(profile):  # shortcut: a copy would share them; copying them too comes later
        raise ProfileRenameError(
            f"{profile.stem} has build folders of its own (Combine, an overhaul), so it can't be duplicated yet."
        )
    new = profile.with_name(name + ".me3")
    with operations.lock(profile):
        operations.recover(profile)
        if (why := operations.problem(profile)) is not None:
            raise ProfileRenameError(f"Another change to this profile is not finished: {why}")
        data = profile.read_bytes()
        op = operations.start(profile, f"duplicate of profile {profile.stem} as {name}")
        try:
            op.write_file(new, data, expect="missing")
            op.note(
                kind="profile-duplicate", name=profile.stem, new=name, profile=str(new), made={str(new): _sha(data)}
            )
        except BaseException:
            op.discard()
            raise
        try:
            op.commit(refuse=lambda: GAME_OPEN if loc.game_running() else None)
        except build.BuildError as e:
            raise ProfileRenameError(str(e)) from e
    log(f"duplicated profile {profile.stem} as {name}")
    return {"operation": str(op.dir), "profile": str(new), "name": name}


def undo_duplicate(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Remove the copy, unless it was changed since (then it stays and the reason is given)."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != "profile-duplicate" or op.state != build.ACTIVE:
        raise ProfileRenameError("This copy can no longer be taken back.")
    new = Path(info["profile"])
    with operations.lock(new):
        if new.is_file():
            if _sha(new.read_bytes()) != info["made"][str(new)]:
                raise ProfileRenameError(f"{new.name} was changed after it was copied, so it is left as it is.")
            back = operations.start(new, f"undo of the copy {info.get('new', '')}")
            try:
                back.write_file(new, None, expect=info["made"][str(new)])
            except BaseException:
                back.discard()
                raise
            back.commit()
            back.release()
        op.release()
    return f"took back the copy {info.get('new', '')}"
