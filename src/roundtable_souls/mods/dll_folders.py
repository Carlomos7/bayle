"""Every DLL mod lives in a folder of its own (natives/<DLL name>/<DLL name>.dll). loose() finds the DLL entries that
do not: the DLL sits directly in natives/ or in the profile's folder, or in a folder other entries' DLLs use too.
preview() says what "Put in folders" would do and what stops it; move() does it as one journaled operation
(merging.build) with Undo (undo_move).

For each loose DLL a folder natives/<stem> is built beside the profile: the DLL and the files sharing its stem
(UnlockTheFps.ini, UnlockTheFps.zh-CN.ini, ...) are copied there and read back; a folder named after the stem moves in
whole. A settings file no DLL owns (a config.ini next to several DLLs) is COPIED, never moved: another DLL may read
it. Only after that does the journal remove the originals and point the entry at the new place (a relative path).
Nothing is overwritten: a folder that is already there stops the move. An interruption is undone as a whole.
"""

from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.merging import build
from roundtable_souls.mods import configs, naming, operations
from roundtable_souls.mods.checks import _canon
from roundtable_souls.mods.profile_edit import entries, read_text, rel, resolve, roots
from roundtable_souls.mods.profile_writer import ProfileWriter

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "dll-folders"  # the operation's kind in its journal and the Activity undo record's type
GAME_OPEN = "Close the game first: it has these files open."


class DllFolderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Move:
    name: str  # the DLL's stem: the new folder's name
    dll: Path
    indexes: tuple[int, ...]  # the profile's entries that load this DLL
    target: Path  # natives/<name>
    moves: tuple[Path, ...] = ()  # files (and a folder named after the stem) that move with it
    copies: tuple[Path, ...] = ()  # settings files another DLL may read: copied, the original stays


@dataclass
class Plan:
    profile: Path
    moves: list[Move] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.moves) and not self.refusals

    @property
    def files_moved(self) -> int:
        return sum(1 + len(m.moves) for m in self.moves)

    @property
    def files_copied(self) -> int:
        return sum(len(m.copies) for m in self.moves)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def loose(profile: Path) -> dict[Path, list[int]]:
    """The DLLs of the profile's native entries that are not in a folder of their own, each with its entries' indexes.
    A DLL inside a package's folder belongs to that package. Nothing is read beyond the profile and folder listings."""
    profile = Path(profile)
    text = read_text(profile)
    rows = entries(profile)
    _pk, nt_root = roots(profile, text)
    packages = [_canon(resolve(profile, e["path"])) for e in rows if e["kind"] == "package" and e.get("path")]
    dlls: dict[Path, list[int]] = defaultdict(list)
    for e in rows:
        if e["kind"] != "native" or not e.get("path"):
            continue
        d = resolve(profile, e["path"])
        if d.suffix.lower() == ".dll" and d.is_file():
            dlls[d].append(e["index"])
    sharing: dict[Path, set[Path]] = defaultdict(set)
    for d in dlls:
        sharing[_canon(d.parent)].add(_canon(d))
    shared_roots = {_canon(profile.parent), _canon(nt_root)}
    out = {}
    for d, idx in dlls.items():
        parent = _canon(d.parent)
        if any(parent == p or p in parent.parents for p in packages):
            continue
        if parent in shared_roots or len(sharing[parent]) > 1:
            out[d] = idx
    return out


def _sidecars(dll: Path) -> tuple[list[Path], list[Path]]:
    """(moves, copies) for a DLL: what shares its stem or is a folder of that name moves; settings files of the folder
    no other DLL owns are copied when the folder holds other DLLs too."""
    try:
        kids = sorted(dll.parent.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return [], []
    stem = dll.stem.lower()
    others = [k.stem.lower() for k in kids if k.is_file() and k.suffix.lower() == ".dll" and k != dll]
    moves, copies = [], []
    for k in kids:
        low = k.name.lower()
        if k == dll or k.suffix.lower() == ".dll" and k.is_file():
            continue
        if k.is_dir():
            if low == stem:
                moves.append(k)
        elif low.startswith(stem + ".") and not any(o.startswith(stem) and low.startswith(o + ".") for o in others):
            moves.append(k)
        elif others and configs.settings_name(k.name) and not any(low.startswith(o + ".") for o in others):
            copies.append(k)
    return moves, copies


def preview(profile: Path, loc: Locations) -> Plan:
    """What putting the loose DLLs in folders would do, or why it can't be done now (refusals; nothing is changed)."""
    from roundtable_souls.mods.install import folder_problem

    profile = Path(profile)
    out = Plan(profile)
    try:
        found = loose(profile)
        nt_root = roots(profile, read_text(profile))[1]
    except (OSError, ValueError) as e:
        out.refusals.append(f"{profile.name} could not be read ({e}), so nothing was moved.")
        return out
    taken = {c.name.lower() for c in nt_root.iterdir()} if nt_root.is_dir() else set()
    for dll, idx in sorted(found.items(), key=lambda kv: kv[0].name.lower()):
        name = dll.stem
        target = nt_root / name
        why = naming.unsafe(name) or (
            f"{name} is a name the launcher keeps" if name.lower() in naming.RESERVED else None
        )
        if why is None and name.lower() in taken:
            why = f"A folder called {name} is already there"
        if why is None:
            why = folder_problem(target, len(dll.name))
        if why is not None:
            out.refusals.append(f"{dll.name}: {why}, so nothing was moved.")
            continue
        taken.add(name.lower())
        moves, copies = _sidecars(dll)
        out.moves.append(Move(name, dll, tuple(sorted(idx)), target, tuple(moves), tuple(copies)))
    if out.moves and loc.game_running():
        out.refusals.append(GAME_OPEN)
    if out.moves and (why := operations.problem(profile)) is not None:
        out.refusals.append(f"Another change to this profile is not finished: {why}")
    return out


def _copy_checked(src: Path, dst: Path) -> None:
    shutil.copy2(src, dst)
    if src.stat().st_size != dst.stat().st_size or _sha(src.read_bytes()) != _sha(dst.read_bytes()):
        raise DllFolderError(f"The copy of {src.name} does not match the original, so nothing was moved.")


def _signature(p: Plan) -> list:
    return [(m.dll, m.target, m.indexes, m.moves, m.copies) for m in p.moves]


def move(profile: Path, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Put every loose DLL in its own folder, as one operation. Returns {operation, profile, name, folders, moved,
    copied}. Raises DllFolderError with nothing changed."""
    profile = Path(profile)
    first = preview(profile, loc)
    if not first.ok:
        raise DllFolderError(" ".join(first.refusals) or "Every DLL is in a folder of its own already.")
    operations.recover(profile)
    with operations.lock(profile):
        plan = preview(profile, loc)
        if not plan.ok or _signature(plan) != _signature(first):
            raise DllFolderError(" ".join(plan.refusals) or "The profile changed since the preview; try again.")
        raw = profile.read_bytes()
        op = operations.start(profile, f"DLL mods put in folders of their own in {profile.name}")
        try:
            _prepare(plan, op, raw)
        except BaseException:
            op.discard()
            raise
        try:
            op.commit(refuse=lambda: _refuse(plan, loc, raw))
        except build.BuildError as e:
            raise DllFolderError(str(e)) from e
    log(f"put {len(plan.moves)} DLL mod(s) in folders of their own")
    return {
        "operation": str(op.dir),
        "profile": str(profile),
        "name": profile.stem,
        "folders": len(plan.moves),
        "moved": plan.files_moved,
        "copied": plan.files_copied,
    }


def _refuse(plan: Plan, loc: Locations, raw: bytes) -> str | None:
    if loc.game_running():
        return GAME_OPEN
    if plan.profile.read_bytes() != raw:
        return "The profile changed while the DLLs were being moved."
    if any(m.target.exists() for m in plan.moves):
        return "A folder for a DLL appeared meanwhile, so nothing was moved."
    return None


def _prepare(plan: Plan, op: build.Operation, raw: bytes) -> None:
    stage = op.dir / "stage"  # beside the journal; on the same drive as the new folders or nothing is done
    anchor = next(p for p in plan.moves[0].target.parents if p.exists())
    if not build._same_drive(stage.parent, anchor):
        raise DllFolderError("The mods folder is on another drive than the launcher's files, so nothing was moved.")
    w = ProfileWriter(plan.profile)
    made: list[dict] = []
    for m in plan.moves:
        folder = stage / m.name
        folder.mkdir(parents=True)
        files = [m.dll, *(f for f in (*m.moves, *m.copies) if f.is_file())]
        for f in files:
            _copy_checked(f, folder / f.name)
        op.move_folder(folder, m.target)
        for d in (f for f in m.moves if f.is_dir()):
            op.move_folder(d, m.target / d.name)
        for f in (m.dll, *(f for f in m.moves if f.is_file())):
            op.write_file(f, None, expect=_sha(f.read_bytes()))
        for i in m.indexes:
            w.set_path(i, rel(plan.profile, m.target / m.dll.name))
        made.append(
            {
                "target": str(m.target),
                "files": {f.name: _sha(f.read_bytes()) for f in files},
                "dirs": [[str(d), str(m.target / d.name)] for d in m.moves if d.is_dir()],
            }
        )
    new = w.plan("before putting DLL mods in folders").bytes_to_write
    op.write_file(plan.profile, new, expect=_sha(raw))
    op.note(kind=KIND, name=plan.profile.stem, profile=str(plan.profile), new_sha=_sha(new), folders=made)


def undo_move(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Put every DLL, its files and the profile back as they were; the new folders go to the Recycle Bin. Raises
    DllFolderError, nothing changed, when a new file or the profile was edited since or an old place is taken."""
    from roundtable_souls.platform import trash

    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise DllFolderError("This change can no longer be taken back.")
    if not trash.available():
        raise DllFolderError("There is no Recycle Bin to put the new folders in, so nothing was changed.")
    profile = Path(info["profile"])
    with operations.lock(profile):
        if not profile.is_file() or _sha(profile.read_bytes()) != info["new_sha"]:
            raise DllFolderError(
                f"{profile.name} changed after the move. Undoing would lose that, so nothing was changed."
            )
        for f in info["folders"]:
            target = Path(f["target"])
            for name, sha in f["files"].items():
                p = target / name
                if not p.is_file() or _sha(p.read_bytes()) != sha:
                    raise DllFolderError(f"{name} changed after the move, so nothing was changed.")
            for src, _dst in f["dirs"]:
                if Path(src).exists():
                    raise DllFolderError(f"{Path(src).name} is there again; undoing would overwrite it.")
        for step in op.steps:
            if step["type"] == "file" and step["after"] == "" and Path(step["live"]).exists():
                raise DllFolderError(f"{Path(step['live']).name} is there again; undoing would overwrite it.")
        back = build.Operation(
            op.dir.parent.parent, f"undo of the DLL folders in {profile.name}", ops=op.dir.parent.name
        )
        try:
            for f in reversed(info["folders"]):
                for src, dst in reversed(f["dirs"]):
                    back.move_folder(Path(dst), Path(src))
            for step in op.steps:
                if step["type"] != "file" or not step["before"]:
                    continue
                live, before = Path(step["live"]), (op.dir / step["before"]).read_bytes()
                back.write_file(live, before, expect=info["new_sha"] if step["after"] else "missing")
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()
        op.release()
    for f in info["folders"]:
        try:
            trash.send(Path(f["target"]))
        except OSError as e:
            log(f"undo: {f['target']} could not be moved to the Recycle Bin ({e})")
    return f"took back the DLL folders in {profile.name}"
