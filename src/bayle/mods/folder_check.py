"""A profile's folder inside the launcher's own profiles folder (library.game_root(...)/profiles) must be named after it
and hold only it. check() says which of that is wrong; rename_folder() fixes a folder with the wrong name as one
journaled operation (merging.build.Operation, journal beside the folder) with Undo; mods.folder_split does the other.
Profiles anywhere else (a plain me3 setup) are never judged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.merging import build
from bayle.mods import library, migrate, operations

if TYPE_CHECKING:
    from bayle.game.locate import Locations

KIND = "folder-rename"  # the operation's kind in its journal and the Activity undo record's type
OK, MISNAMED, CROWDED, OUTSIDE = "ok", "misnamed", "crowded", "outside"
GAME_OPEN = "Close the game first: it has these files open."


class FolderError(RuntimeError):
    pass


@dataclass(frozen=True)
class FolderCheck:
    kind: str = OUTSIDE
    folder: str = ""  # the folder's name
    profiles: tuple[Path, ...] = ()  # the profiles (.me3) in the folder

    @property
    def count(self) -> int:
        return len(self.profiles)


def profiles_root(loc: Locations) -> Path | None:
    home = loc.me3_profiles_dir()
    return None if home is None else library.profiles_root(home, loc.game.key)


def profiles_in(folder: Path) -> list[Path]:
    """The profiles in a folder (the offline copies and me3's -default ones are not)."""
    try:
        return sorted(
            (
                p
                for p in Path(folder).iterdir()
                if p.is_file()
                and p.suffix.lower() == ".me3"
                and not p.name.lower().endswith((".offline.me3", "-default.me3"))
            ),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []


def check(profile: Path, loc: Locations) -> FolderCheck:
    profile = Path(profile)
    root = profiles_root(loc)
    if root is None or migrate._n(profile.parent.parent) != migrate._n(root):
        return FolderCheck()
    found = tuple(profiles_in(profile.parent))
    if len(found) > 1:
        return FolderCheck(CROWDED, profile.parent.name, found)
    if profile.parent.name.lower() != profile.stem.lower():
        return FolderCheck(MISNAMED, profile.parent.name, found)
    return FolderCheck(OK, profile.parent.name, found)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def finish_state(op: build.Operation) -> list[str]:
    """Re-key the launcher's records (remembered profile, attached configs, history) for a done operation, then say so
    in its journal. Safe to run again. Used by the rename and the split."""
    notes = migrate._apply_state(op.info)
    op.note(state_done=True)
    return notes


def rename_refusal(profile: Path, loc: Locations) -> str | None:
    """Why the folder can't be renamed to the profile's name now, in plain words, or None."""
    profile = Path(profile)
    if check(profile, loc).kind != MISNAMED:
        return "This folder does not need renaming."
    if loc.game_running():
        return GAME_OPEN
    target = profile.parent.with_name(profile.stem)
    same = migrate._n(target) == migrate._n(profile.parent)
    if not same and target.exists():
        return f"A folder called {profile.stem} is already there, so nothing was renamed."
    if (why := operations.problem(profile)) is not None:
        return f"Another change to this profile is not finished: {why}"
    return None


def rename_folder(profile: Path, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Rename the profile's folder to the profile's name. Returns {operation, profile (new path), name, folder}.
    Raises FolderError with nothing changed."""
    profile = Path(profile)
    if why := rename_refusal(profile, loc):
        raise FolderError(why)
    operations.recover(profile)
    src = profile.parent
    dst = src.with_name(profile.stem)
    new = dst / profile.name
    case_only = migrate._n(src) == migrate._n(dst)
    with build.ops_lock(src.parent):
        if why := rename_refusal(profile, loc):
            raise FolderError(why)
        raw = profile.read_bytes()
        item = migrate.Item(
            profile,
            profile.stem,
            dst,
            library.state_of(profile).root,
            units=[migrate.Unit(src, ".", [profile.stem])],
            old_bytes=raw,
        )
        item.new_bytes = migrate._rewrite(item)  # an absolute entry path into the folder follows it
        op = build.Operation(src.parent, f"rename of the folder {src.name} to {dst.name}")
        try:
            if item.new_bytes != raw:
                op.write_file(profile, item.new_bytes, expect=_sha(raw))
            if case_only:
                aside = src.with_name(f".{src.name}.rename-{op.id}")
                op.move_folder(src, aside)
                op.move_folder(aside, dst)
            else:
                op.move_folder(src, dst)
            op.note(
                kind=KIND,
                name=profile.stem,
                profile=str(new),
                game=loc.game.key,
                folder=[str(src), str(dst)],
                pairs=[[str(src), str(dst)]],
                profiles=[{"old": str(profile), "new": str(new), "folder": str(dst)}],
                new_sha=_sha(item.new_bytes),
                state_done=False,
            )
        except BaseException:
            op.discard()
            raise
        try:
            op.commit(refuse=lambda: GAME_OPEN if loc.game_running() else None)
        except build.BuildError as e:
            raise FolderError(str(e)) from e
        notes = finish_state(op)
    log(f"renamed the folder {src.name} to {dst.name}")
    return {"operation": str(op.dir), "profile": str(new), "name": profile.stem, "folder": dst.name, "notes": notes}


def undo_rename(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Put the folder back under its old name (and the profile's text as it was). Raises FolderError, nothing changed,
    when the old name is taken again or the profile changed since."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise FolderError("This rename can no longer be taken back.")
    src, dst = (Path(x) for x in info["folder"])  # it went src -> dst
    new = dst / Path(info["profile"]).name
    case_only = migrate._n(src) == migrate._n(dst)
    with build.ops_lock(dst.parent):
        if not new.is_file():
            raise FolderError(f"{new.name} is not there any more, so the rename can't be taken back.")
        if src.exists() and not case_only:
            raise FolderError(f"A folder called {src.name} is there again; undoing would overwrite it.")
        back = build.Operation(dst.parent, f"undo of the rename of the folder {src.name}")
        try:
            step = next((s for s in op.steps if s["type"] == "file" and s["after"]), None)
            if step is not None and _sha(new.read_bytes()) == info["new_sha"]:
                back.write_file(new, (op.dir / step["before"]).read_bytes(), expect=info["new_sha"])
            if case_only:
                aside = dst.with_name(f".{dst.name}.rename-{back.id}")
                back.move_folder(dst, aside)
                back.move_folder(aside, src)
            else:
                back.move_folder(dst, src)
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()
        op.release()
    for n in migrate._apply_state(info, back=True):
        log(f"undo: {n}")
    return f"took back the rename: the folder is called {src.name} again"
