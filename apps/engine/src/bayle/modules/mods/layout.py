"""Changing where the launcher's profiles live, and what its folders are called, as journaled operations.

    <profiles root>/<game folder>/<name>/<name>.me3 with packages/, natives/, builds/, .bayle/
    <profiles root>/<game folder>/<shared folder>/    Shared mods

relocate         moves every game folder to another Profiles folder. Same drive: a rename. Another drive: each file is
                 copied beside the target, read back (size and sha256), the copies renamed into place as one
                 operation, and only then are the originals deleted. Cancelling or crashing before the commit leaves
                 the originals untouched and the staged copy is cleaned up.
rename_layout    renames the game folders, each profile's packages and natives folders and the shared folder.
undo_layout      puts either back (a relocation is moved back the same way it went).

Both rewrite the paths the .me3 files hold (a relative path is kept relative, so most need nothing) and, once the
move is committed, the launcher's settings (config.settings: profiles_root and the folder names). The journal lives
in the launcher's data folder (ops_root), so it is found again whatever happened to the Profiles folder. Built on
mods.migrate's helpers and merging.build.Operation. preview_relocate / preview_rename give the confirm its numbers.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bayle.adapters.filesystem import build
from bayle.adapters.formats import me3_profile
from bayle.modules import ports
from bayle.modules.mods import kinds, library, migrate
from bayle.modules.mods.models import UndoError
from bayle.modules.mods.profile_writer import ProfileWriter
from bayle.modules.settings import models as settings

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

RELOCATE, RENAME = "layout-relocate", "layout-rename"  # the operations' kinds in their journals
GAME_OPEN = "Close the game first: it has these files open."
GIB = 1 << 30
CLOUD = ("onedrive", "dropbox", "google drive", "googledrive", "icloud", "mobile documents", "my drive")
LONG_PATH = 240  # Windows stops at 260 (MAX_PATH) for many programs


class LayoutError(RuntimeError):
    pass


class Cancelled(LayoutError):
    pass


_AUTO: Any = object()  # setting_to not given: the new root
Progress = Callable[[int, int], None]  # bytes done, bytes in all


def ops_root() -> Path:
    root = ports.data_dir() / "layout-ops"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _same_drive(a: Path, b: Path) -> bool:  # a seam the tests use to force the copy path
    return build._same_drive(a, b)


def _free(path: Path) -> int:  # likewise for the free space
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


# ----------------------------------------------------------------------------- what is there
def current_root(loc: Locations) -> Path | None:
    s = ports.load_settings()
    return Path(s.profiles_root) if s.profiles_root else loc.me3_profiles_dir()


def game_folders(root: Path, pattern: str) -> list[tuple[str, Path]]:
    """(game key, folder) for each folder of root named by the pattern ("b-{game}"), case aside."""
    head, tail = pattern.split("{game}")
    rx = re.compile(f"^{re.escape(head)}(.+){re.escape(tail)}$", re.IGNORECASE)
    try:
        found = [(m.group(1), d) for d in Path(root).iterdir() if d.is_dir() and (m := rx.match(d.name))]
    except OSError:
        return []
    return sorted(found, key=lambda x: x[1].name.lower())


def profile_dirs(game_dir: Path) -> list[Path]:
    """The profile folders of a game folder: <name>/ holding <name>.me3."""
    try:
        return sorted(
            (d for d in Path(game_dir).iterdir() if d.is_dir() and not d.name.startswith(".") and _me3_in(d)),
            key=lambda d: d.name.lower(),
        )
    except OSError:
        return []


def _me3_in(d: Path) -> list[Path]:
    try:
        return sorted(p for p in d.glob("*.me3") if p.is_file())
    except OSError:
        return []


def _n(p: Path | str) -> str:
    return migrate._n(p)


def _sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _inventory(folders: list[Path]) -> dict[str, int]:
    files = size = profiles = longest = 0
    for g in folders:
        profiles += len(profile_dirs(g))
        for dirpath, _dirs, names in os.walk(g):
            for n in names:
                files += 1
                p = Path(dirpath) / n
                longest = max(longest, len(os.path.relpath(p, g.parent)))
                try:
                    size += p.stat().st_size
                except OSError:
                    pass
    return {"games": len(folders), "profiles": profiles, "files": files, "bytes": size, "longest": longest}


def _unfinished(root: Path, folders: list[Path]) -> str | None:
    build.adopt_legacy_ops(ops_root())
    if build.pending(ops_root()):
        return "a move of the profiles folders is not finished"

    for g in folders:
        build.adopt_legacy_ops(g)
        if build.pending(g, build.OPS):  # a move, rename, split or Shared change journaled in the game folder
            return f"a change to the profiles in {g.name} is not finished"
        for p in profile_dirs(g):
            for state in (library.STATE, library.LEGACY_STATE):
                if build.pending(p, f"{state}/{library.OPS}"):
                    return f"a change to the profile {p.name} is not finished"
    return None


# ----------------------------------------------------------------------------- the .me3 text
def _retarget(me3: Path, pairs: list[tuple[Path, Path]]) -> bytes | None:
    """The bytes of the profile at me3 once the folders in pairs (old -> new) have moved: an absolute path follows
    the folder it was in, a relative one is kept relative to where the profile will be. None when nothing changes."""
    raw = me3.read_bytes()
    try:
        w = ProfileWriter(me3)
        here = Path(migrate._remap(str(me3.parent), pairs))
        for e in w.entries():
            path = e["path"]
            if not path:
                continue
            was = Path(os.path.abspath(me3_profile.resolve(me3, path)))
            now = Path(migrate._remap(str(was), pairs))
            if Path(path).is_absolute():
                new = str(now)
                new = new.replace("/", "\\") if "\\" in path and "/" not in path else new.replace("\\", "/")
            else:
                new = migrate._relpath(now, here)
            if new != path:
                w.set_path(e["index"], new)
        if w.text == raw.decode("utf-8"):
            return None
        return w.plan(f"before moving {me3.name}").bytes_to_write
    except Exception:  # shortcut: an unreadable profile is left as it is, the move does not depend on its text
        return None


# ----------------------------------------------------------------------------- previews and refusals
def _cloud(p: Path) -> bool:
    return any(c in str(p).lower().replace("\\", "/") for c in CLOUD)


def relocate_refusal(loc: Locations, new_root: Path, folders: list[tuple[str, Path]] | None = None) -> str | None:
    """Why the Profiles folder can't be moved to new_root now, in plain words, or None."""
    old = current_root(loc)
    pattern = ports.load_settings().game_folder_pattern
    if old is None:
        return "There is no Profiles folder to move."
    folders = game_folders(old, pattern) if folders is None else folders
    if not folders:
        return "There are no profile folders to move."
    new_root = Path(os.path.abspath(new_root))
    if new_root.is_file():
        return f"{new_root} is a file, not a folder."
    if _n(new_root) == _n(old):
        return "That is the Profiles folder already."
    for _g, f in folders:
        if migrate._inside(new_root, f):
            return f"{new_root} is inside {f.name}, which is being moved."
    taken = [f.name for _g, f in folders if (new_root / f.name).exists()]
    taken += [d.name for _g, d in game_folders(new_root, pattern) if d.name not in taken]
    if taken:
        return f"{new_root} already has {', '.join(sorted(taken))}, so nothing was moved."
    if loc.game_running():
        return GAME_OPEN
    if why := _unfinished(old, [f for _g, f in folders]):
        return f"Not yet: {why}."
    inv = _inventory([f for _g, f in folders])
    if not _same_drive(new_root if new_root.exists() else _existing(new_root), old) and (
        _free(new_root) < inv["bytes"] + inv["bytes"] // 20 + (64 << 20)
    ):
        return "There is not enough free space for the copy."
    return None


def _existing(p: Path) -> Path:
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def preview_relocate(loc: Locations, new_root: Path) -> dict[str, Any]:
    """For the confirm: counts, size, whether the files are copied, warnings, and the refusal (None when it can go)."""
    old = current_root(loc)
    pattern = ports.load_settings().game_folder_pattern
    folders = game_folders(old, pattern) if old else []
    new_root = Path(os.path.abspath(new_root))
    inv = _inventory([f for _g, f in folders])
    copy = not _same_drive(_existing(new_root), old) if old else False
    free = _free(new_root)
    warnings: list[str] = []
    if _cloud(new_root):
        warnings.append(
            "This folder looks cloud-synced (OneDrive, Dropbox, Google Drive or iCloud); syncing can slow or break the game's files."
        )
    if copy and free - inv["bytes"] < max(GIB, inv["bytes"] // 10):
        warnings.append("The drive will be nearly full after the copy.")
    if len(str(new_root)) + 1 + inv["longest"] > LONG_PATH:
        warnings.append("Some paths will be very long; programs that stop at 260 characters may not open them.")
    return {
        **inv,
        "from": str(old or ""),
        "to": str(new_root),
        "copy": copy,
        "free": free,
        "warnings": warnings,
        "refusal": relocate_refusal(loc, new_root, folders),
    }


# ----------------------------------------------------------------------------- relocating
def relocate(
    loc: Locations, new_root: Path, progress: Progress | None = None, cancel: Callable[[], bool] | None = None
) -> dict:
    """Move every game folder to new_root. Raises LayoutError (Cancelled when cancel() said so) with nothing changed."""
    old = current_root(loc)
    if why := relocate_refusal(loc, new_root):
        raise LayoutError(why)
    assert old is not None
    s = ports.load_settings()
    return _move_root(
        loc, old, Path(os.path.abspath(new_root)), s.game_folder_pattern, s.profiles_root, _AUTO, progress, cancel
    )


def _move_root(
    loc: Locations,
    old: Path,
    new: Path,
    pattern: str,
    setting_from: str | None,
    setting_to: str | None,
    progress: Progress | None = None,
    cancel: Callable[[], bool] | None = None,
) -> dict:
    setting_to = str(new) if setting_to is _AUTO else setting_to
    folders = game_folders(old, pattern)
    pairs = [(f, new / f.name) for _g, f in folders]
    copy = not _same_drive(_existing(new), old)
    total = _inventory([f for _g, f in folders])["bytes"]
    made = not new.exists()
    root = ops_root()
    with build.ops_lock(root):
        finish_pending()
        op = build.Operation(root, f"move of the profiles folders to {new}")
        stage = new / f".rs-relocate-{op.id}" if copy else None
        op.note(kind=RELOCATE, stage=str(stage or ""), made_root=str(new) if made else "")
        try:
            new.mkdir(parents=True, exist_ok=True)
            done = [0]

            def tick(n: int) -> None:
                done[0] += n
                if progress:
                    progress(done[0], total)

            profiles: dict[str, list[dict]] = {}
            for game, f in folders:
                dest = new / f.name
                mine = [(m, dest / m.relative_to(f)) for p in profile_dirs(f) for m in _me3_in(p)]
                profiles[game] = [{"old": str(m), "new": str(n)} for m, n in mine]
                if copy:
                    assert stage is not None
                    _copy_tree(f, stage / f.name, tick, cancel)
                    for m, _n2 in mine:
                        data = _retarget(m, pairs)
                        if data is not None:
                            (stage / f.name / m.relative_to(f)).write_bytes(data)
                    op.move_folder(stage / f.name, dest)
                else:
                    for m, _n2 in mine:
                        if (data := _retarget(m, pairs)) is not None:
                            op.write_file(m, data, expect=migrate._sha(m.read_bytes()))
                    op.move_folder(f, dest)
            op.note(
                games=[{"game": g, "profiles": profiles[g]} for g, _f in folders],
                pairs=[[str(a), str(b)] for a, b in pairs],
                old_root=str(old),
                new_root=str(new),
                pattern=pattern,
                setting_from=setting_from,
                setting_to=setting_to,
                cleanup=[str(f) for _g, f in folders] if copy else [],
                state_done=False,
            )
        except BaseException:
            op.discard()
            _drop(stage, new if made else None)
            raise
        try:
            op.commit(refuse=lambda: GAME_OPEN if loc.game_running() else None)
        except build.BuildError as e:
            _drop(stage, new if made else None)
            raise LayoutError(str(e)) from e
        notes = _finish(op)
    return {
        "operation": str(op.dir),
        "from": str(old),
        "to": str(new),
        "copied": copy,
        "notes": notes,
        "undo": {"type": "layout-relocate", "name": Path(new).name, "operation": str(op.dir)},
    }


def _drop(stage: Path | None, made_root: Path | None) -> None:
    if stage:
        shutil.rmtree(stage, ignore_errors=True)
    if made_root is not None:
        try:
            made_root.rmdir()  # only when empty
        except OSError:
            pass


def _copy_tree(src: Path, dst: Path, tick: Callable[[int], None], cancel: Callable[[], bool] | None) -> None:
    """src copied to dst, every file read back (size and sha256). Raises Cancelled, or LayoutError on a mismatch."""
    for dirpath, dirnames, names in os.walk(src):
        here = dst / Path(dirpath).relative_to(src)
        here.mkdir(parents=True, exist_ok=True)
        for d in dirnames:
            if (Path(dirpath) / d).is_symlink():  # a folder link is recreated, not followed
                os.symlink(os.readlink(Path(dirpath) / d), here / d, target_is_directory=True)
        for n in names:
            if cancel and cancel():
                raise Cancelled("Cancelled: nothing was moved.")
            a, b = Path(dirpath) / n, here / n
            shutil.copy2(a, b)
            if a.stat().st_size != b.stat().st_size or _sha_file(a) != _sha_file(b):
                raise LayoutError(f"The copy of {n} does not match the original, so nothing was moved.")
            tick(b.stat().st_size)


def _finish(op: build.Operation) -> list[str]:
    """What follows a committed operation: the launcher's settings and records, the originals of a copy. Safe to
    run again (a crash after the commit finishes it at the next start)."""
    info, notes = op.info, []
    if info["kind"] == RELOCATE:
        changes: dict[str, Any] = {"profiles_root": info["setting_to"]}
    else:
        changes = dict(info["set_to"])
    try:
        ports.save_settings(**changes)
    except OSError as e:
        notes.append(f"The launcher's settings could not be updated ({e})")
    for g in info["games"]:
        notes += migrate._apply_state({"pairs": info["pairs"], "profiles": g["profiles"], "game": g["game"]})
    if info["kind"] == RELOCATE:
        for f in info.get("cleanup") or []:
            shutil.rmtree(f, ignore_errors=True)
            if Path(f).exists():
                notes.append(f"{f} could not be deleted; the files are copied, you can delete it yourself")
        if info.get("stage"):
            shutil.rmtree(info["stage"], ignore_errors=True)
    op.note(state_done=True)
    return notes


def finish_pending() -> list[str]:
    """Undo an operation that was interrupted before its commit (and clean up what it staged), finish one that was
    committed but not finished. Safe to run again."""
    root = ops_root()
    adopted = build.adopt_legacy_ops(root)
    base = root / build.OPS
    staged = []
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and build._state(d) in (build.PREPARED, build.ACTIVATING):
                staged.append(build.Operation.load(d).info)
    said = adopted + build.recover_operations(root)
    for info in staged:
        _drop(
            Path(info["stage"]) if info.get("stage") else None,
            Path(info["made_root"]) if info.get("made_root") else None,
        )
    for op in build.active(root):
        if op.info.get("kind") in (RELOCATE, RENAME) and not op.info.get("state_done"):
            _finish(op)
            said.append("an interrupted change of the profiles folders was finished")
    return said


# ----------------------------------------------------------------------------- renaming
@dataclass
class Names:
    pattern: str
    packages: str
    natives: str
    shared: str

    @classmethod
    def now(cls) -> Names:
        s = ports.load_settings()
        return cls(s.game_folder_pattern, s.packages_folder, s.natives_folder, s.shared_folder)

    def fields(self) -> dict[str, str]:
        return {
            "game_folder_pattern": self.pattern,
            "packages_folder": self.packages,
            "natives_folder": self.natives,
            "shared_folder": self.shared,
        }


def _rename_plan(root: Path, a: Names, b: Names) -> tuple[list[dict], str | None]:
    """The renames that take layout a to layout b under root, and why they can't be done (None: they can)."""
    games: list[dict] = []
    taken_roots = {x.name.lower() for x in root.iterdir()} if root.is_dir() else set()
    vacated = set()
    for game, g in game_folders(root, a.pattern):
        to = root / b.pattern.replace("{game}", game)
        inner: list[dict] = []
        parents = [("", g, [(a.shared, b.shared)])] + [
            (p.name, p, [(a.packages, b.packages), (a.natives, b.natives)]) for p in profile_dirs(g)
        ]
        for rel, parent, names in parents:
            have = {x.name.lower() for x in parent.iterdir()}
            moving = {f.lower() for f, t in names if f != t and (parent / f).exists()}
            for f, t in names:
                if f == t or not (parent / f).exists():
                    continue
                if t.lower() in have - moving:
                    return [], f"{t} is already in {parent.name}, so nothing was renamed."
                inner.append({"parent_rel": rel, "from": f, "to": t})
        profiles = [{"old": str(m), "new": str(to / m.relative_to(g))} for p in profile_dirs(g) for m in _me3_in(p)]
        if g.name != to.name:
            vacated.add(g.name.lower())
        games.append({"game": game, "from_dir": str(g), "to_dir": str(to), "inner": inner, "profiles": profiles})
    for gm in games:
        t = Path(gm["to_dir"]).name.lower()
        if gm["from_dir"] != gm["to_dir"] and t in taken_roots - vacated:
            return [], f"{Path(gm['to_dir']).name} is already in the Profiles folder, so nothing was renamed."
    return games, None


def _problems(a: Names, **new: str | None) -> Names:
    b = Names(
        new.get("pattern") or a.pattern,
        new.get("packages") or a.packages,
        new.get("natives") or a.natives,
        new.get("shared") or a.shared,
    )
    if b == a:
        raise LayoutError("Those are the names already.")
    bad = settings.layout_problems(pattern=b.pattern, packages=b.packages, natives=b.natives, shared=b.shared)
    if bad:
        raise LayoutError(" ".join(bad.values()))
    return b


def rename_refusal(loc: Locations, games: list[dict]) -> str | None:
    if loc.game_running():
        return GAME_OPEN
    return _unfinished(Path(), [Path(g["from_dir"]) for g in games])


def preview_rename(loc: Locations, *, pattern=None, packages=None, natives=None, shared=None) -> dict[str, Any]:
    a = Names.now()
    root = current_root(loc)
    out: dict[str, Any] = {"games": 0, "profiles": 0, "folders": 0, "profile_files": 0, "warnings": [], "refusal": None}
    try:
        b = _problems(a, pattern=pattern, packages=packages, natives=natives, shared=shared)
        games, why = _rename_plan(root, a, b) if root else ([], "There is no Profiles folder.")
    except LayoutError as e:
        out["refusal"] = str(e)
        return out
    out["refusal"] = why or rename_refusal(loc, games)
    out["games"] = sum(g["from_dir"] != g["to_dir"] for g in games)
    out["profiles"] = sum(len(g["profiles"]) for g in games)
    out["folders"] = out["games"] + sum(len(g["inner"]) for g in games)
    longest = max((len(g["to_dir"]) for g in games), default=0)
    if root and longest + 40 > LONG_PATH:
        out["warnings"].append("Some paths will be very long.")
    return out


def rename_layout(loc: Locations, *, pattern=None, packages=None, natives=None, shared=None) -> dict:
    """Rename the folders to the new names (None keeps one), as one operation. Raises LayoutError, nothing changed."""
    a = Names.now()
    b = _problems(a, pattern=pattern, packages=packages, natives=natives, shared=shared)
    root = current_root(loc)
    if root is None:
        raise LayoutError("There is no Profiles folder.")
    games, why = _rename_plan(root, a, b)
    if why or (why := rename_refusal(loc, games)):
        raise LayoutError(why)
    return _rename_run(loc, games, a.fields(), b.fields())


def _rename_run(loc: Locations, games: list[dict], set_from: dict, set_to: dict) -> dict:
    pairs: list[tuple[Path, Path]] = []
    for g in games:
        f, t = Path(g["from_dir"]), Path(g["to_dir"])
        pairs += [(f / i["parent_rel"] / i["from"], t / i["parent_rel"] / i["to"]) for i in g["inner"]]
        if f != t:
            pairs.append((f, t))
    pairs.sort(key=lambda p: len(str(p[0])), reverse=True)  # the most specific folder first
    root = ops_root()
    with build.ops_lock(root):
        finish_pending()
        op = build.Operation(root, "rename of the profiles folders")
        try:
            op.note(kind=RENAME)
            for g in games:
                for x in g["profiles"]:
                    m = Path(x["old"])
                    if (data := _retarget(m, pairs)) is not None:
                        op.write_file(m, data, expect=migrate._sha(m.read_bytes()))
            # every folder goes to a name of its own first, so swapped or case-only names never meet
            inner = [
                (Path(g["from_dir"]) / i["parent_rel"] / i["from"], Path(g["from_dir"]) / i["parent_rel"] / i["to"])
                for g in games
                for i in g["inner"]
            ]
            outer = [(Path(g["from_dir"]), Path(g["to_dir"])) for g in games if g["from_dir"] != g["to_dir"]]
            for group in (inner, outer):
                asides = [(a, a.with_name(f".{a.name}.rename-{op.id}"), b) for a, b in group]
                for a, aside, _b in asides:
                    op.move_folder(a, aside)
                for _a, aside, b in asides:
                    op.move_folder(aside, b)
            op.note(
                games=games,
                pairs=[[str(a), str(b)] for a, b in pairs],
                set_from=set_from,
                set_to=set_to,
                state_done=False,
            )
        except BaseException:
            op.discard()
            raise
        try:
            op.commit(refuse=lambda: GAME_OPEN if loc.game_running() else None)
        except build.BuildError as e:
            raise LayoutError(str(e)) from e
        notes = _finish(op)
    return {
        "operation": str(op.dir),
        "notes": notes,
        "folders": len(inner) + len(outer),
        "undo": {"type": "layout-rename", "name": "the folders", "operation": str(op.dir)},
    }


# ----------------------------------------------------------------------------- taking it back
def undo_layout(op_dir: Path, loc: Locations) -> str:
    """Put a relocation or a rename back as it was. Raises LayoutError, nothing changed, when it can't be."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") not in (RELOCATE, RENAME) or op.state != build.ACTIVE or not info.get("state_done"):
        raise LayoutError("This change can no longer be taken back.")
    if loc.game_running():
        raise LayoutError(GAME_OPEN)
    if info["kind"] == RELOCATE:
        back = Path(info["old_root"])
        for x in info["pairs"]:
            if not Path(x[1]).is_dir():
                raise LayoutError(f"{Path(x[1]).name} is not where the move left it, so it is left as it is.")
        _move_root(loc, Path(info["new_root"]), back, info["pattern"], info["setting_to"], info["setting_from"])
        what = f"moved the profiles folders back to {back}"
    else:
        games = [
            {
                **g,
                "from_dir": g["to_dir"],
                "to_dir": g["from_dir"],
                "inner": [{**i, "from": i["to"], "to": i["from"]} for i in g["inner"]],
                "profiles": [{"old": x["new"], "new": x["old"]} for x in g["profiles"]],
            }
            for g in info["games"]
        ]
        for g in games:
            if not Path(g["from_dir"]).is_dir():
                raise LayoutError(f"{Path(g['from_dir']).name} is not where the rename left it.")
        _rename_run(loc, games, info["set_to"], info["set_from"])
        what = "took back the rename of the profiles folders"
    # the undo is itself an operation in the journal; both are let go, nothing is left to undo twice
    for done in build.active(ops_root()):
        done.release()
    return what


def _undo_kind(undo: dict, log, loc) -> str:
    try:
        return undo_layout(Path(undo["operation"]), loc)
    except LayoutError as e:
        raise UndoError(str(e)) from e


kinds.register_undo(
    ("layout-relocate", "layout-rename"),
    kinds.operation_active,
    _undo_kind,
    kinds.fixed("This change to the profiles folders can no longer be taken back."),
)
