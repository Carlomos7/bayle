"""Renaming a profile (its .me3) and duplicating it, each as one undoable operation (technical specification §8.10).

me3 knows a profile by its file name only, so nothing inside the file changes, but the launcher keys several things by
the profile's path or name. A rename moves them together:

    in the journal    the .me3, its <name>.offline.me3 and .me3.bak (beside it, or in .roundtable/backups), the
                      profile's entry in .roundtable/settings.json. Files are written under the new name and removed
                      from the old (their bytes are kept in the journal); then the profile's own folder
                      (profiles/<name>/, with its mods, builds and state) is moved to the new name as the last step
                      (merging.build.Operation.move_folder: nothing is ever deleted by an older launcher's rollback).
                      That journal is kept in the profiles folder, outside the folder that moves.
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
from roundtable_souls.merging import build
from roundtable_souls.mods import history, library, migrate, naming, operations
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.profile_edit import ModError

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
    builds: list[tuple[Path, Path]] = field(default_factory=list)  # a loose profile's builds, renamed with it
    folder: tuple[Path, Path] | None = None  # the profile's own folder and where it goes (moved last)
    profile_bytes: bytes = b""  # the .me3 as it is now
    new_bytes: bytes = b""  # and as it is under the new name
    offline_bytes: bytes | None = None  # the offline copy's text under the new name, when its paths needed following
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
    if name.lower() in naming.reserved() or name.lower().endswith(GENERATED):
        return f"{name} is a name the launcher or me3 uses itself."
    target = profile.with_name(name + ".me3")
    if library.own_folder(profile) and name.lower() != profile.stem.lower():
        try:  # case-insensitive on every system: the folder must still work when it reaches Windows
            folder_taken = any(p.name.lower() == name.lower() for p in profile.parent.parent.iterdir())
        except OSError:
            folder_taken = profile.parent.with_name(name).exists()
        if folder_taken:
            return f"There is already a profile called {name}."
    if name.lower() != profile.stem.lower():
        try:
            taken = any(p.name.lower() == target.name.lower() for p in profile.parent.iterdir())
        except OSError:
            taken = target.exists()
        if taken:
            return f"There is already a profile called {name}."
    return naming.path_problem(target, 0)


def folder_move(profile: Path, new_name: str, loc: Locations) -> tuple[Path, Path] | None:
    """(profiles/<name>, profiles/<new name>) for a profile in a folder of its own in me3's profiles folder, else None
    (a profile loose in a folder keeps its folder)."""
    profile = Path(profile)
    home = loc.me3_profiles_dir()
    if (
        home is None
        or not library.own_folder(profile)
        or _canon(profile.parent.parent) != _canon(library.profiles_root(home, loc.game.key))
    ):
        return None
    return profile.parent, profile.parent.with_name(new_name)


def _shift(path: Path, folder: tuple[Path, Path] | None, back: bool = False) -> Path:
    """path as it is once the profile's folder has moved (or, back, before it)."""
    if folder is None:
        return path
    src, dst = (folder[1], folder[0]) if back else folder
    try:
        return dst / Path(path).relative_to(src)
    except ValueError:
        return path


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
    out.new_bytes = out.profile_bytes
    out.folder = folder_move(profile, out.new_name, loc)
    if out.folder is not None:
        try:  # entry paths into the old folder follow it (an absolute one becomes relative)
            out.new_bytes, out.offline_bytes = _followed(profile, out.profile_bytes, out.folder[1])
        except (OSError, ValueError) as e:
            raise ProfileRenameError(f"{profile.name} could not be read ({e}).") from e
        target_folder = out.folder[1]
        if target_folder.exists() and not out.case_only:
            refuse(f"A folder called {target_folder.name} is already there, so the launcher does not overwrite it.")
        if why := naming.path_problem(target_folder / (out.new_name + ".me3"), 0):
            refuse(why)
    elif not library.own_folder(profile):
        mine, theirs = library.ProfileFolder.of(profile).root, library.ProfileFolder.of(new).root
        if mine.is_dir():
            out.builds.append((mine, theirs))
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
        "Its settings, backup copy and version history follow it"
        + (", and its folder is renamed" if out.folder else ""),
    ]
    out.lines.append("Undo puts everything back")
    return out


def _followed(profile: Path, raw: bytes, dst: Path) -> tuple[bytes, bytes | None]:
    """The profile's text (and its offline copy's) once its folder is dst: paths inside the old folder follow it."""
    item = migrate.Item(profile, dst.name, dst, Path(), units=[migrate.Unit(profile.parent, ".", [profile.stem])])
    item.old_bytes = raw
    offline = profile.with_name(profile.stem + OFFLINE)
    extra = None
    if offline.is_file():
        old = offline.read_bytes()
        try:
            got = migrate._rewrite(item, offline, old)
            extra = got if got != old else None
        except OSError, ValueError, ModError:  # a copy that can't be read as a profile moves as it is
            pass
    return migrate._rewrite(item), extra


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


# ----------------------------------------------------------------------------- the journal
def _lock(profile: Path, folder: tuple[Path, Path] | None):
    """The lock for an operation on the profile. One that moves the profile's folder holds the profiles folder's
    instead: Windows does not move a folder that holds an open lock file."""
    return build.ops_lock(folder[0].parent, 30.0) if folder else operations.lock(profile)


def _start(profile: Path, what: str, folder: tuple[Path, Path] | None) -> build.Operation:
    """An operation on the profile; when its folder moves, its journal lives in the profiles folder beside it."""
    if folder is None:
        return operations.start(profile, what)
    op = build.Operation(folder[0].parent, what)
    op.note(profile=str(profile))
    return op


def _move_folder(op: build.Operation, src: Path, dst: Path, case_only: bool) -> None:
    if case_only:
        aside = src.with_name(f".{src.name}.rename-{op.id}")
        op.move_folder(src, aside)
        op.move_folder(aside, dst)
    else:
        op.move_folder(src, dst)


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

    operations.recover(old)
    with _lock(old, p.folder):
        if (why := operations.problem(old)) is not None:
            raise ProfileRenameError(f"Another change to this profile is not finished: {why}")
        if not old.is_file() or old.read_bytes() != p.profile_bytes:
            raise ProfileRenameError(f"{old.name} changed since the preview; try again.")
        op = _start(old, f"rename of profile {p.old_name} to {p.new_name}", p.folder)
        try:
            for src, dest in p.moves:
                data = p.new_bytes if src == old else src.read_bytes()
                if p.offline_bytes is not None and src.name.lower().endswith(OFFLINE):
                    data = p.offline_bytes
                _move(op, src, dest, data, p.case_only)
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
            if p.folder is not None:
                _move_folder(op, *p.folder, p.case_only)
                new = _shift(new, p.folder)
            op.note(
                kind=KIND,
                name=p.old_name,
                new=p.new_name,
                profile=str(new),
                old_profile=str(old),
                folder=[str(p.folder[0]), str(p.folder[1])] if p.folder else None,
                game=loc.game.key,
                moves=[{"old": str(a), "new": str(b)} for a, b in p.moves],
                builds=[{"old": str(a), "new": str(b)} for a, b in p.builds],
                settings=str(p.settings[0]) if p.settings else "",
                new_sha=_sha(p.new_bytes),
                offline_sha=_sha(p.offline_bytes) if p.offline_bytes is not None else "",
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
    folder = (Path(info["folder"][0]), Path(info["folder"][1])) if info.get("folder") else None
    # the files are put back inside the folder where it is now; the folder goes back last
    moves = [(_shift(Path(m["new"]), folder), _shift(Path(m["old"]), folder)) for m in info["moves"]]
    builds = [(Path(m["new"]), Path(m["old"])) for m in info["builds"]]
    with _lock(new, (folder[1], folder[0]) if folder else None):
        if not new.is_file():
            raise ProfileRenameError(f"{new.name} is not there any more, so the rename can't be taken back.")
        for src, dest in moves:
            if src.exists() and dest.exists() and not case_only:
                raise ProfileRenameError(f"{dest.name} is there again; undoing would overwrite it.")
        for src, dest in builds:
            if not src.is_dir() or (dest.exists() and not case_only):
                raise ProfileRenameError(f"{dest.name} is not where the rename left it, so nothing was changed.")
        if folder is not None and folder[0].exists() and not case_only:
            if any(x.is_file() for x in folder[0].rglob("*")):
                raise ProfileRenameError(f"{folder[0].name} is there again; undoing would overwrite it.")
            shutil.rmtree(folder[0])  # only empty folders (a record looked up under the old name made them)
        back = _start(
            new, f"undo of the rename of profile {info.get('name', '')}", (folder[1], folder[0]) if folder else None
        )
        try:
            for i, (src, dest) in enumerate(moves):
                if not src.is_file():
                    continue
                data = src.read_bytes()
                want = (
                    info["new_sha"]
                    if i == 0
                    else info.get("offline_sha")
                    if src.name.lower().endswith(OFFLINE)
                    else None
                )
                if want and _sha(data) == want:  # not changed since: its exact earlier bytes
                    step = next(
                        s
                        for s in op.steps
                        if s["type"] == "file" and s["live"] == str(_shift(dest, folder, back=True)) and s["before"]
                    )
                    data = (op.dir / step["before"]).read_bytes()
                _move(back, src, dest, data, case_only)
            if info.get("settings"):
                _settings_back(op, back, Path(info["settings"]), folder, old.name, new.name)
            for src, dest in builds:
                if case_only:
                    aside = src.with_name(f".{src.name}.rename-{back.id}")
                    back.move_folder(src, aside)
                    back.move_folder(aside, dest)
                else:
                    back.move_folder(src, dest)
            if folder is not None:
                _move_folder(back, folder[1], folder[0], case_only)
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()  # an undo is final
        op.release()
    for n in _apply_state(info, back=True):
        log(f"undo: {n}")
    return f"took back the rename of {info.get('name', 'the profile')}: it is called {old.stem} again"


def _settings_back(
    op: build.Operation, back: build.Operation, was: Path, folder: tuple[Path, Path] | None, old: str, new: str
) -> None:
    """The settings file with the profile's entry under its old name: the exact earlier bytes when the file is as the
    rename left it, else the same re-keying of what it holds now."""
    file = _shift(was, folder)  # where the settings file is now; the journal names it where it was
    step = next((s for s in op.steps if s["type"] == "file" and s["live"] == str(was) and s["after"]), None)
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
    where = profile.parent.parent if library.own_folder(profile) else profile.parent
    taken = (
        {p.name.lower() + ".me3" if p.is_dir() else p.name.lower() for p in where.iterdir()}
        if where.is_dir()
        else set()
    )
    base = re.sub(r"( copy( \d+)?)$", "", profile.stem) + " copy"
    name, n = base, 2
    while name.lower() + ".me3" in taken:
        name, n = f"{base} {n}", n + 1
    return name


def duplicate(profile: Path, *, loc: Locations, name: str = "", log: Callable[[str], None] = lambda s: None) -> dict:
    """Copy the profile as `name`, one operation: a profile with a folder of its own gets a new folder with copies of
    its mod and natives folders (its builds and state are not copied); a loose profile only its .me3. Returns
    {operation, profile, name}."""
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
    own = folder_move(profile, name, loc)
    mine = library.ProfileFolder.of(profile)
    if own is None and mine.builds.is_dir() and any(mine.builds.iterdir()):  # a loose profile's builds stay shared
        raise ProfileRenameError(
            f"{profile.stem} has build folders of its own (Combine, an overhaul), so it can't be duplicated yet."
        )
    new = profile.with_name(name + ".me3") if own is None else own[1] / (name + ".me3")
    with _lock(profile, own):
        operations.recover(profile)
        if (why := operations.problem(profile)) is not None:
            raise ProfileRenameError(f"Another change to this profile is not finished: {why}")
        data = profile.read_bytes()
        op = _start(profile, f"duplicate of profile {profile.stem} as {name}", own)
        try:
            if own is None:
                op.write_file(new, data, expect="missing")
            else:
                staged = own[1].with_name(f".{name}.copy-{op.id}")
                staged.mkdir()
                for sub_name in [*library.copied_folders(profile), "builds"]:  # incl. an overhaul's own folder
                    if (own[0] / sub_name).is_dir():
                        shutil.copytree(own[0] / sub_name, staged / sub_name)
                item = migrate.Item(profile, name, own[1], own[1], units=[migrate.Unit(own[0], ".", [profile.stem])])
                item.old_bytes = data
                data = migrate._rewrite(item)  # an absolute entry path into the folder follows the copy
                (staged / (name + ".me3")).write_bytes(data)
                try:
                    _remap_records(staged, own[0], own[1], profile, own[1] / (name + ".me3"), data)
                except ProfileRenameError:
                    shutil.rmtree(staged, ignore_errors=True)
                    raise
                op.replace_folder(own[1], staged)
            op.note(
                kind="profile-duplicate",
                name=profile.stem,
                new=name,
                profile=str(new),
                folder=str(own[1]) if own else "",
                made={str(new): _sha(data)},
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


def _remap_records(staged: Path, old: Path, new: Path, old_profile: Path, new_profile: Path, data: bytes) -> None:
    """The copied folders' JSON records (an overhaul's manifest, builds/<id>/ records) name the original's files by
    absolute path: those inside the original profile folder now name the copy, and the profile's own hash row follows
    the copy's text. A record that can't be read is refused by name, as nothing says what it holds."""
    base = os.path.normcase(os.path.abspath(old))
    sha = _sha(data)

    def fix(s: str) -> str:
        norm = os.path.normcase(os.path.abspath(s)) if s and os.path.isabs(s) else ""
        if norm != base and not norm.startswith(base + os.sep):
            return s
        out = new / os.path.relpath(os.path.abspath(s), os.path.abspath(old))
        if os.path.normcase(os.path.abspath(s)) == os.path.normcase(os.path.abspath(old_profile)):
            out = new_profile  # the profile file itself is called after the copy now
        return out.as_posix() if "\\" not in s else str(out)

    def walk(v):
        if isinstance(v, str):
            return fix(v)
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            out = {k: walk(x) for k, x in v.items()}
            if isinstance(out.get("path"), str) and os.path.normcase(os.path.abspath(out["path"])) == os.path.normcase(
                os.path.abspath(new_profile)
            ):
                out["sha256"] = sha
            return out
        return v

    for f in sorted(staged.rglob("*.json")):
        try:
            record = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ProfileRenameError(
                f"{f.relative_to(staged).as_posix()} could not be read ({e}), so the profile can't be copied with it."
            ) from e
        fixed = walk(record)
        if fixed != record:
            f.write_text(json.dumps(fixed, indent=2), encoding="utf-8", newline="\n")


def undo_duplicate(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Remove the copy, unless it was changed since (then it stays and the reason is given)."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != "profile-duplicate" or op.state != build.ACTIVE:
        raise ProfileRenameError("This copy can no longer be taken back.")
    new = Path(info["profile"])
    if info.get("folder"):  # the copy's folder goes to the Recycle Bin, unless the copy was changed since
        from roundtable_souls.platform import trash

        if new.is_file():
            if _sha(new.read_bytes()) != info["made"][str(new)]:
                raise ProfileRenameError(f"{new.name} was changed after it was copied, so it is left as it is.")
            if not trash.available():
                raise ProfileRenameError("There is no Recycle Bin to put the copy's folder in, so it is left as it is.")
            trash.send(Path(info["folder"]))
        op.release()
        return f"took back the copy {info.get('new', '')}"
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
