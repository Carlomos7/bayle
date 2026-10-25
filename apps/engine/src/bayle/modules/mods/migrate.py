"""Giving profiles folders of their own inside the launcher's root for a game, rs-<game> in me3's profiles folder
(mods.library): roundtable/<game>/profiles/<name>/, by three actions that share one engine:

    migrate        what older versions made (3.21 to 4.0.x), in one operation:
                       rs-<game>/profiles/<name>.me3          ->  roundtable/<game>/profiles/<name>/<name>.me3
                       rs-<game>/packages|natives/<id>/       ->  .../<name>/packages|natives/<id>/
                       rs-<game>/builds/<what>/<name>/        ->  .../<name>/builds/<what>/
                       rs-<game>/sources/<id>, overhauls/<id> ->  .../<name>/builds/<id>/sources, overhaul
                       rs-<game>/<name>/ (its mod/ becomes packages/)  ->  .../<name>/
                   and rs-<game> goes when nothing is left in it.
    move into      a profile that lives elsewhere in me3's profiles folder (a plain me3 setup): its .me3 and the mod
                   folders its entries point at inside its own folder go to .../<name>/packages|natives. A mod folder
                   another profile in the source folder also lists is copied, not moved.
    split          a folder inside roundtable/<game>/profiles that holds several .me3 files: one folder per profile.

Each is one journaled operation (merging.build.Operation, journal in roundtable/<game>/profiles/.roundtable-ops): an interruption is
undone as a whole by the next start. A mod folder several profiles use is copied for all but the last, which takes the
original; every copy is checked file by file against its source before anything is committed, so no source is ever
gone without a verified copy. The profile text is rewritten with the paths its entries now need. A clash with an
existing folder takes <name>-2. Profiles elsewhere are never touched. Same drive only (it is all inside me3's
profiles folder). Undo (undo_migration) puts everything back; the folders it made go to the Recycle Bin.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.adapters.filesystem import build, files
from bayle.adapters.formats import me3_profile
from bayle.modules.mods import history, kinds, library, profile_edit
from bayle.modules.mods import profile_settings as ps
from bayle.modules.mods.models import UndoError
from bayle.modules.mods.profile_writer import ProfileWriter

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

KIND = "profile-folders"  # the operation's kind in its journal and the Activity undo record's type
PREFIX = library.PREFIX
OFFLINE = ".offline.me3"
OLD_FOLDERS = ("profiles", "library", "packages", "natives", "overhauls", "sources", "builds", library.LEGACY_STATE)
OTHER = "\0other"  # a user of a mod folder that is not moving: the folder is copied, never taken


class MigrateError(RuntimeError):
    pass


def _n(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _inside(p: Path | str, folder: Path | str) -> bool:
    a, b = _n(p), _n(folder)
    return a == b or a.startswith(b + os.sep)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _same_drive(a: Path, b: Path) -> bool:
    while not b.exists() and b != b.parent:
        b = b.parent
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def legacy_root(home: Path, game: str) -> Path:
    return library.legacy_root(home, game)


def own_profiles(folder: Path) -> list[Path]:
    """The profiles directly in a folder (offline copies and me3's generated defaults are not)."""
    try:
        return sorted(
            (p for p in Path(folder).glob("*.me3") if p.is_file() and library.is_user_profile(p)),
            key=lambda p: p.name.lower(),
        )
    except OSError:
        return []


def old_profiles(home: Path, game: str) -> list[Path]:
    """The profiles older versions made: the shared layout of rs-<game>/profiles, rs-<game>/<name>/, and 4.2.0's
    roundtable/<game>/profiles/<name>/."""
    root = legacy_root(home, game)
    out = own_profiles(root / "profiles")
    for top, skip in ((root, OLD_FOLDERS), (library.old_game_root(home, game) / "profiles", ())):
        try:
            folders = sorted(
                d for d in top.iterdir() if d.is_dir() and not d.name.startswith(".") and d.name.lower() not in skip
            )
        except OSError:
            continue
        for d in folders:
            out += [p for p in own_profiles(d) if p.stem.lower() == d.name.lower()]
    return out


def shared_library(home: Path, game: str) -> Path | None:
    """4.2.0's Shared mods folder, when it is there: roundtable/<game>/library."""
    folder = library.old_game_root(home, game) / "library"
    return folder if folder.is_dir() else None


# ----------------------------------------------------------------------------- the plan
@dataclass
class Unit:
    """One folder (or file) of a mod and the profiles that use it."""

    src: Path
    dest_rel: str  # inside the profile's folder
    users: list[str] = field(default_factory=list)  # old profile names; OTHER last when one that stays uses it


@dataclass
class Item:
    old: Path
    name: str  # the folder and profile name now
    folder: Path
    state: Path  # the launcher's folder the profile's records are in now
    entry: dict | None = None  # its settings entry
    units: list[Unit] = field(default_factory=list)
    old_bytes: bytes = b""
    new_bytes: bytes = b""
    maps: list[tuple[Path, Path]] = field(default_factory=list)  # folders that moved whole (the Shared mods folder)
    keep_state: bool = False  # its state folder is a unit and moves whole (renamed .bayle)

    @property
    def new(self) -> Path:
        return self.folder / f"{self.name}.me3"

    def where(self, target: Path) -> Path:
        """target as it is once this profile has its own folder."""
        for u in self.units:
            if _inside(target, u.src):
                return self.folder / u.dest_rel / Path(os.path.abspath(target)).relative_to(os.path.abspath(u.src))
        for src, dst in self.maps:
            if _inside(target, src):
                return dst / Path(os.path.abspath(target)).relative_to(os.path.abspath(src))
        return target


@dataclass
class Plan:
    root: Path  # roundtable/<game>/profiles
    game: str
    legacy: bool  # the old shared layout, not a move into the root
    items: list[Item] = field(default_factory=list)
    units: dict[str, Unit] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    old_roots: list[Path] = field(default_factory=list)  # rs-<game>, roundtable/<game> (legacy only)
    shared: tuple[Path, Path] | None = None  # 4.2.0's Shared mods folder and where it goes

    @property
    def summary(self) -> dict:
        """Counts for the confirm: profiles moved, mod folders moved, mod folders copied."""
        copied = sum(1 for u in self.units.values() for user in u.users[:-1] if user != OTHER)
        taken = sum(1 for u in self.units.values() if u.users and u.users[-1] != OTHER)
        return {
            "profiles": len(self.items),
            "moved": taken,
            "copied": copied + sum(OTHER in u.users for u in self.units.values()),
        }


def _read_profile(p: Path) -> tuple[bytes, list[dict]]:
    raw = p.read_bytes()
    text = raw.decode("utf-8")
    if me3_profile.is_array_form(text):
        text = me3_profile.to_blocks(text)
    return raw, me3_profile.entries(text)


def _build(
    root: Path,
    game: str,
    legacy: bool,
    movers: list[Path],
    stay: list[Path],
    find: Callable[[Path, list[dict], Callable[[Path, str, str], None]], None],
    entry_of: Callable[[Path], dict | None],
    state_of: Callable[[Path], Path],
) -> Plan:
    out = Plan(root, game, legacy)
    taken = {p.name.lower() for p in root.iterdir()} if root.is_dir() else set()
    unit_of: dict[str, Unit] = {}

    def unit(src: Path, rel: str, user: str) -> None:
        u = unit_of.setdefault(_n(src), Unit(src, rel))
        if user not in u.users:
            u.users.append(user)

    def sentinel(src: Path, rel: str, user: str) -> None:
        u = unit_of.get(_n(src))
        if u is not None and OTHER not in u.users:
            u.users.append(OTHER)

    readable: list[tuple[Path, bytes, list[dict]]] = []
    for p in movers:
        try:
            readable.append((p, *_read_profile(p)))
        except (OSError, ValueError) as e:
            out.notes.append(f"{p.name} could not be read ({e}), so it stays where it is")
    for p, raw, rows in readable:
        name, k = p.stem, 2
        while name.lower() in taken:
            name, k = f"{p.stem}-{k}", k + 1
        taken.add(name.lower())
        if name != p.stem:
            out.notes.append(f"A folder called {p.stem} was already there, so the profile is now {name}")
        out.items.append(Item(p, name, root / name, state_of(p), entry_of(p), old_bytes=raw))
        find(p, rows, unit)
    for p in stay:  # profiles that stay: what they list is copied, not taken
        try:
            find(p, _read_profile(p)[1], sentinel)
        except OSError, ValueError:
            pass
    out.units = unit_of
    by_name = {i.old.stem: i for i in out.items}
    for u in unit_of.values():
        for user in u.users:
            if user in by_name:
                by_name[user].units.append(u)
    for item in out.items:
        item.new_bytes = _rewrite(item)
    return out


def plan(home: Path, game: str) -> Plan:
    """What migrating the older layouts does, with nothing written."""
    root = legacy_root(home, game)
    lay = library.layout()
    old42 = library.old_game_root(home, game)

    def shared_layout(p: Path) -> bool:
        return p.parent.name.lower() == "profiles" and library.legacy_root(home, game) in p.parents

    def find(p: Path, rows: list[dict], unit: Callable[[Path, str, str], None]) -> None:
        if not shared_layout(p):  # <old folder>/<name>/: its folders come along, mod/ as packages/
            for sub, rel in (
                ("mod", lay.packages),
                ("packages", lay.packages),
                ("natives", lay.natives),
                ("builds", "builds"),
            ):
                if (p.parent / sub).exists():
                    unit(p.parent / sub, rel, p.stem)
            for sub in (library.STATE, library.LEGACY_STATE):  # its state folder moves whole, renamed
                if (p.parent / sub).is_dir():
                    unit(p.parent / sub, library.STATE, p.stem)
                    break
            targets = [me3_profile.resolve(p, e["path"]) for e in rows if e.get("path")]
            for own in library.root_folders(p, targets):  # an overhaul's own folder is part of the layout
                unit(own, own.name, p.stem)
            return
        for e in rows:
            if not e.get("path"):
                continue
            parts = _rel(Path(os.path.abspath(me3_profile.resolve(p, e["path"]))), root)
            if len(parts) >= 2 and parts[0] in ("packages", "natives"):
                unit(
                    root / parts[0] / parts[1],
                    (lay.packages if parts[0] == "packages" else lay.natives) + "/" + parts[1],
                    p.stem,
                )
            elif len(parts) >= 3 and parts[0] == "builds" and parts[2].lower() == p.stem.lower():
                unit(root / "builds" / parts[1] / parts[2], f"builds/{parts[1]}", p.stem)
            elif len(parts) >= 3 and parts[0] == "profiles" and parts[1].lower() not in OLD_FOLDERS:
                unit(root / "profiles" / parts[1], parts[1], p.stem)  # an overhaul's folder beside the profiles
            elif len(parts) >= 2 and parts[0] in ("sources", "overhauls"):
                unit(
                    root / parts[0] / parts[1],
                    f"builds/{parts[1]}/" + ("sources" if parts[0] == "sources" else "overhaul"),
                    p.stem,
                )
        builds = root / "builds"
        for what in sorted(x for x in builds.iterdir() if x.is_dir()) if builds.is_dir() else []:
            mine = next((x for x in what.iterdir() if x.is_dir() and x.name.lower() == p.stem.lower()), None)
            if mine is None:
                continue
            unit(mine, f"builds/{what.name}", p.stem)
            for coll, leaf in (("sources", "sources"), ("overhauls", "overhaul")):
                if (root / coll / what.name).is_dir():
                    unit(root / coll / what.name, f"builds/{what.name}/{leaf}", p.stem)

    settings = root / library.LEGACY_STATE / library.SETTINGS
    try:
        data = ps._read(settings) if settings.is_file() else {}
    except ps.Unreadable:
        data = {}

    def entry(p: Path) -> dict | None:
        return (data.get("profiles") or {}).get(p.name) if shared_layout(p) else None

    out = _build(
        library.profiles_root(home, game),
        game,
        True,
        old_profiles(home, game),
        [],
        find,
        entry,
        lambda p: root / library.LEGACY_STATE if shared_layout(p) else library.state_of(p).root,
    )
    out.old_roots = [root, old42]
    shared = shared_library(home, game)
    target = library.shared_root(home, game)
    if shared is not None and not target.exists():
        out.shared = (shared, target)
    elif shared is not None:
        out.notes.append(f"{target.name} is already there, so the Shared mods stay in {shared.parent.name}/library")
    for item in out.items:
        item.keep_state = not shared_layout(item.old)
        if out.shared is not None and item.keep_state:
            item.maps.append(out.shared)
    for item in out.items:
        item.new_bytes = _rewrite(item)
    return out


def plan_move(profiles: list[Path], root: Path, game: str) -> Plan:
    """What moving these profiles (all from one folder) into root does: each into root/<name>/, with the mod folders
    their entries point at inside that folder. The .me3 files left in the folder are checked for what they share."""

    source = Path(profiles[0]).parent
    movers = [Path(p) for p in profiles]
    stay = [p for p in own_profiles(source) if _n(p) not in {_n(m) for m in movers}]

    def find(p: Path, rows: list[dict], unit: Callable[[Path, str, str], None]) -> None:
        text = me3_profile.read_text(p)
        pk, nt = profile_edit.roots(p, text)
        for e in rows:
            if not e.get("path"):
                continue
            target = Path(os.path.abspath(me3_profile.resolve(p, e["path"])))
            if not _inside(target, source) or _n(target) == _n(source):
                continue
            first, src = None, Path(os.path.abspath(source))
            for cont in (pk, nt):
                if _inside(target, cont) and _n(target) != _n(cont):
                    first = Path(target).relative_to(os.path.abspath(cont)).parts[0]
                    src = Path(os.path.abspath(cont)) / first
                    break
            if first is None:
                first = Path(target).relative_to(os.path.abspath(source)).parts[0]
                src = src / first
            if first.startswith(".") or _n(src) in (_n(pk), _n(nt)) or src.suffix.lower() == ".me3":
                continue
            unit(src, ("packages" if e["kind"] == "package" else "natives") + "/" + first, p.stem)

    return _build(
        root,
        game,
        False,
        movers,
        stay,
        find,
        lambda p: ps.load(p) or None,
        lambda p: library.state_of(p).root,
    )


def _rel(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return Path(path).relative_to(Path(os.path.abspath(root))).parts
    except ValueError:
        return ()


def _rewrite(item: Item, src: Path | None = None, raw: bytes | None = None) -> bytes:
    """The profile text with every entry path as the new place needs it: a relative one stays relative, to the new
    folder; one inside a moved folder follows it (an absolute one into the new folder turns relative); others point
    where they did. src, raw: another file beside the profile (its offline copy) instead of the profile."""
    src = item.old if src is None else src
    raw = item.old_bytes if raw is None else raw
    w = ProfileWriter(src)
    for e in w.entries():
        if not e["path"]:
            continue
        target = Path(os.path.abspath(me3_profile.resolve(src, e["path"])))
        now = item.where(target)
        inside = _inside(now, item.folder)  # an absolute path into the profile's own folder becomes relative
        new = (
            str(now).replace("\\", "/") if Path(e["path"]).is_absolute() and not inside else _relpath(now, item.folder)
        )
        if new != e["path"]:
            w.set_path(e["index"], new)
    plan_ = w.plan(f"before moving {src.name}")
    return plan_.bytes_to_write if w.text != raw.decode("utf-8") else raw


def _relpath(target: Path, folder: Path) -> str:
    try:
        return os.path.relpath(target, folder).replace("\\", "/")
    except ValueError:  # another drive
        return str(target).replace("\\", "/")


# ----------------------------------------------------------------------------- applying
def _tree(folder: Path) -> dict[str, tuple[int, str]]:
    if folder.is_file():
        return {"": (folder.stat().st_size, hashlib.sha256(folder.read_bytes()).hexdigest())}
    return {
        p.relative_to(folder).as_posix(): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _copy_verified(src: Path, dst: Path) -> None:
    """src copied to dst and read back: every file and its bytes must be the same, else nothing is kept."""
    if src.is_file():
        shutil.copy2(src, dst)
    else:
        shutil.copytree(src, dst)
    if _tree(src) != _tree(dst):
        raise MigrateError(f"The copy of {src.name} does not match the original, so nothing was moved.")


def migrate(loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict | None:
    """Turn the old shared layout of rs-<game> into a folder per profile, in place, as one operation. None when there
    is nothing to do (also on a second run). Raises MigrateError, with nothing changed, when it can't be done now."""
    home = loc.me3_profiles_dir()
    if home is None or not old_profiles(home, loc.game.key):
        return None
    root = library.profiles_root(home, loc.game.key)
    if loc.game_running():
        return None  # tried again at the next start
    if not _same_drive(old_profiles(home, loc.game.key)[0], root):
        return None  # Settings put the Profiles folder on another drive: its own relocate copies, a rename cannot
    root.mkdir(parents=True, exist_ok=True)
    with build.ops_lock(root):
        finish_pending(root)
        p = plan(home, loc.game.key)
        if not p.items:
            return None
        return _run(p, f"moving {len(p.items)} profile(s) of {loc.game.key} into their own folders", log)


def move(p: Plan, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Do a plan_move: raises MigrateError, with nothing changed, when it can't be done now."""
    if not p.items:
        raise MigrateError("; ".join(p.notes) or "Nothing to move.")
    if loc.game_running():
        raise MigrateError("Close the game first: it has these files open.")
    p.root.mkdir(parents=True, exist_ok=True)
    with build.ops_lock(p.root):
        finish_pending(p.root)
        names = ", ".join(i.old.name for i in p.items)
        return _run(p, f"moving {names} into {p.root.name}", log)


def _run(p: Plan, what: str, log: Callable[[str], None]) -> dict:
    op = build.Operation(p.root, what)
    stage = p.root / f".rs-profile-folders-{op.id}"
    try:
        _prepare(p, op, stage)
    except BaseException:
        op.discard()
        shutil.rmtree(stage, ignore_errors=True)
        raise
    try:
        op.commit(refuse=lambda: "A file changed while the profiles were being moved." if _changed(p) else None)
    except build.BuildError as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise MigrateError(str(e)) from e
    shutil.rmtree(stage, ignore_errors=True)
    notes = finish_state(op)
    log(f"moved {len(p.items)} profile(s) of {p.game} into folders of their own")
    return {
        "operation": str(op.dir),
        "profile": str(p.items[0].new),
        "profiles": [str(i.new) for i in p.items],
        "notes": [*p.notes, *notes],
        "game": p.game,
        "summary": p.summary,
    }


def _changed(p: Plan) -> bool:
    return any(not i.old.is_file() or i.old.read_bytes() != i.old_bytes for i in p.items)


def _prepare(p: Plan, op: build.Operation, stage: Path) -> None:
    stage.mkdir(parents=True)
    moves: list[dict] = []
    for item in p.items:
        sd = stage / item.name
        sd.mkdir()
        (sd / f"{item.name}.me3").write_bytes(item.new_bytes)
        offline = item.old.with_name(item.old.stem + OFFLINE)
        if offline.is_file():
            shutil.copy2(offline, sd / f"{item.name}.offline.me3")
        own_state = sd / library.STATE
        if not item.keep_state:
            own_state.mkdir()
            files.hide(own_state)
        if isinstance(item.entry, dict) and not item.keep_state:
            (own_state / library.SETTINGS).write_text(
                json.dumps(
                    {"version": 1, "schema": 1, "profiles": {f"{item.name}.me3": _restored(item.entry, item)}},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        bak = item.state / library.BACKUPS / (item.old.name + ".bak")
        if bak.is_file() and not item.keep_state:
            (own_state / library.BACKUPS).mkdir()
            shutil.copy2(bak, own_state / library.BACKUPS / f"{item.name}.me3.bak")
        for u in item.units:
            if u.users[-1] != item.old.stem and u.src.exists():  # all but the last user get a verified copy
                (sd / u.dest_rel).parent.mkdir(parents=True, exist_ok=True)
                _copy_verified(u.src, sd / u.dest_rel)
        op.replace_folder(item.folder, sd)
    for item in p.items:
        for u in item.units:
            if u.users[-1] == item.old.stem and u.src.exists():  # the last user takes the original
                op.move_folder(u.src, item.folder / u.dest_rel)
                moves.append({"src": str(u.src), "dest": str(item.folder / u.dest_rel)})
    for item in p.items:
        op.write_file(item.old, None, expect=_sha(item.old_bytes))
        offline = item.old.with_name(item.old.stem + OFFLINE)
        if offline.is_file():
            op.write_file(offline, None, expect=_sha(offline.read_bytes()))
        bak = item.state / library.BACKUPS / (item.old.name + ".bak")
        if bak.is_file() and not item.keep_state:
            op.write_file(bak, None, expect=_sha(bak.read_bytes()))
    if p.shared is not None:  # 4.2.0's Shared mods: one rename; the profiles' links were rewritten to follow
        op.move_folder(*p.shared)
        moves.append({"src": str(p.shared[0]), "dest": str(p.shared[1])})
    for state in {
        i.state for i in p.items if not i.keep_state
    }:  # a settings file left with no other profile's entries goes (kept in the journal)
        settings = state / library.SETTINGS
        mine = {i.old.name for i in p.items if i.state == state and not i.keep_state}
        try:
            keys = set(ps._read(settings).get("profiles") or {}) if settings.is_file() else None
        except ps.Unreadable:
            keys = None
        if keys is not None and keys <= mine:
            op.write_file(settings, None, expect=_sha(settings.read_bytes()))
    pairs = [(Path(m["src"]), Path(m["dest"])) for m in moves]
    for item in p.items:  # a path of the old place follows to the first profile that has it
        for u in item.units:
            if not any(_n(s) == _n(u.src) for s, _d in pairs):
                pairs.append((u.src, item.folder / u.dest_rel))
    op.note(
        kind=KIND,
        name=p.game,
        game=p.game,
        profile=str(p.items[0].new),
        home=str(p.root),
        root=str(p.root),
        legacy=p.legacy,
        old_roots=[str(r) for r in p.old_roots],
        old_folders=sorted({str(i.old.parent) for i in p.items}),
        moves=moves,
        pairs=[[str(s), str(d)] for s, d in pairs],
        profiles=[
            {
                "old": str(i.old),
                "new": str(i.new),
                "folder": str(i.folder),
                "old_sha": _sha(i.old_bytes),
                "new_sha": _sha(i.new_bytes),
            }
            for i in p.items
        ],
        state_done=False,
    )


def _restored(entry: dict, item: Item) -> dict:
    """A profile's settings entry with the stored paths it holds (the parameter overlay) as the new place needs."""
    out = dict(entry)
    overlay = out.get("overlay")
    if isinstance(overlay, dict):
        fixed = dict(overlay)
        for k in ("package", "rebuild"):
            if overlay.get(k):
                was = ps.from_stored(item.old, overlay[k])
                fixed[k] = ps.to_stored(item.new, item.where(was) if was else None)
        out["overlay"] = fixed
    return out


# ----------------------------------------------------------------------------- after the commit
def finish_pending(root: Path) -> list[str]:
    """Undo a migration that was interrupted, and finish the launcher's records of one that was done (see
    finish_state). Safe to run again."""
    said = build.adopt_legacy_ops(Path(root)) + build.recover_operations(root, 30.0, build.OPS)
    for op in build.active(root, build.OPS):
        if op.info.get("kind") == KIND and not op.info.get("state_done"):
            finish_state(op)
            said.append("an interrupted move of the profiles into their folders was finished")
    for stage in Path(root).glob(".rs-profile-folders-*"):  # what an interrupted run staged: emptied by the recovery
        try:
            stage.rmdir()
        except OSError:
            pass
    return said


def finish_state(op: build.Operation) -> list[str]:
    """Re-key the launcher's own records for a move that is done (the settings it remembers, the version history),
    clear what the old layout left, then say so in its journal. Safe to run again."""
    notes = _apply_state(op.info)
    if op.info.get("legacy"):
        _tidy([Path(r) for r in op.info.get("old_roots") or []], [Path(f) for f in op.info.get("old_folders") or []])
    op.note(state_done=True)
    return notes


def _sweep(top: Path) -> None:
    """top goes when only empty folders and empty lock files are left in it."""
    if not top.is_dir():
        return
    for p in sorted(top.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        try:
            if p.is_file() and p.name.endswith(".lock") and p.stat().st_size == 0:
                p.unlink()
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass
    try:
        if not any(top.iterdir()):
            top.rmdir()
    except OSError:
        pass


def _tidy(old_roots: list[Path], folders: list[Path]) -> None:
    """What the old layouts left goes when it is empty (their shared folders, the folders profiles had), then the old
    game folders themselves and roundtable/ when nothing is left. Anything with a file in it stays."""
    for old_root in old_roots:
        for name in OLD_FOLDERS:
            _sweep(old_root / name)
    for folder in folders:
        if folder.name.lower() != "profiles":
            _sweep(folder)
    for old_root in old_roots:
        _sweep(old_root)
    for old_root in old_roots:
        if old_root.parent.name == library.ROOT:
            _sweep(old_root.parent)


def _remap(value: str, pairs: list[tuple[Path, Path]]) -> str:
    for src, dst in pairs:
        if _inside(value, src):
            return str(dst / Path(os.path.abspath(value)).relative_to(os.path.abspath(src)))
    return value


def _apply_state(info: dict, *, back: bool = False) -> list[str]:
    from bayle.modules import ports
    from bayle.modules.mods.rebuild import _key
    from bayle.modules.settings import models as launcher_settings

    pairs = [(Path(s), Path(d)) for s, d in info["pairs"]]
    profs = [(Path(x["old"]), Path(x["new"])) for x in info["profiles"]]
    if back:
        pairs, profs = [(d, s) for s, d in pairs], [(n, o) for o, n in profs]
    notes: list[str] = []
    marks = {_key(o): _key(n) for o, n in profs}
    setups = {_n(o): str(n) for o, n in profs}
    game = info["game"]

    def change(cur):
        out: dict = {}
        ties = {_remap(k, pairs): [_remap(v, pairs) for v in vs] for k, vs in cur.native_configs.items()}
        if ties != cur.native_configs:
            out["native_configs"] = ties
        overlays = {marks.get(k, k): v for k, v in cur.parameter_overlays.items()}
        if overlays != cur.parameter_overlays:
            out["parameter_overlays"] = overlays
        now = launcher_settings.game_setting(cur, game, "setup")
        if now and _n(now) in setups:
            if game == "eldenring":
                out["setup"] = setups[_n(now)]
            else:
                out["games"] = {**cur.games, game: {**(cur.games.get(game) or {}), "setup": setups[_n(now)]}}
        return out

    try:
        ports.change_settings(change)
    except OSError as e:
        notes.append(f"The launcher's settings could not be updated ({e})")
    if not back:
        for old, new in profs:
            try:
                seen = history.folder(old)
                if seen.is_dir():
                    shutil.copytree(seen, history.folder(new), dirs_exist_ok=True)
            except OSError as e:
                notes.append(f"The version history of {new.name} could not be copied ({e})")
    return notes


# ----------------------------------------------------------------------------- taking it back
def undo_migration(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Put everything back as it was (see the module notes). Raises MigrateError, nothing changed, when a moved
    profile changed since, or an old place is taken again. The profiles' new folders go to the Recycle Bin after
    their mods are back."""
    from bayle.adapters.filesystem import trash

    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise MigrateError("This move can no longer be taken back.")
    if not trash.available():
        raise MigrateError("There is no Recycle Bin to put the profiles' new folders in, so nothing was changed.")
    root = Path(info["root"])
    profs, moves = info["profiles"], info["moves"]
    with build.ops_lock(root):
        for x in profs:
            new, old = Path(x["new"]), Path(x["old"])
            if not new.is_file():
                raise MigrateError(f"{new.name} is no longer in its folder, so the move can't be taken back.")
            if _sha(new.read_bytes()) != x["new_sha"]:
                raise MigrateError(
                    f"{new.name} changed after it was moved. Undoing would lose those changes, so everything is "
                    "left as it is."
                )
            if old.exists():
                raise MigrateError(f"{old.name} is back at its old place; undoing would overwrite it.")
        for m in moves:
            if not Path(m["dest"]).exists() or Path(m["src"]).exists():
                raise MigrateError(f"{Path(m['src']).name} is not where the move left it, so it is left as it is.")
        back = build.Operation(root, f"undo of the move of {info.get('game', '')} profiles")
        try:
            for m in moves:
                back.move_folder(Path(m["dest"]), Path(m["src"]))
            for step in op.steps:  # the files removed from the old place come back with their earlier bytes
                if step["type"] == "file" and step["before"] and not step["after"]:
                    live = Path(step["live"])
                    live.parent.mkdir(parents=True, exist_ok=True)
                    back.write_file(live, (op.dir / step["before"]).read_bytes(), expect="missing")
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()
        op.release()
    for x in profs:
        try:
            trash.send(Path(x["folder"]))
        except OSError as e:
            log(f"undo: {x['folder']} could not be moved to the Recycle Bin ({e})")
    for n in _apply_state(info, back=True):
        log(f"undo: {n}")
    return "took back the move into profile folders: everything is where it was"


def _undo_kind(undo: dict, log, loc) -> str:
    try:
        return undo_migration(Path(undo["operation"]), log)
    except MigrateError as e:
        raise UndoError(str(e)) from e


kinds.register_finisher(
    ("profile-folders",), finish_state, "an interrupted move of the profiles into their folders was finished"
)  # the launcher's records still name the old profiles
kinds.register_undo(
    ("profile-folders",),
    kinds.operation_active,
    _undo_kind,
    kinds.fixed("The move into profile folders can no longer be taken back."),
)
