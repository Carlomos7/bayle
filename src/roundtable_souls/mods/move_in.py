"""Moving a profile that lives outside Bayle's folder (roundtable/<game>/profiles in me3's profiles folder) into it,
as one undoable operation. It ends as mods.library lays profiles out: <name>/<name>.me3 with its own packages/,
natives/, builds/ and .roundtable/.

    in its own folder (<name>/<name>.me3)   the whole folder moves (one rename); only absolute paths into it are rewritten.
    loose among others (a plain me3 setup)  the .me3 and what the launcher keeps for it move; each mod entry's folder goes
                                            to packages/ or natives/. A folder another profile of that folder lists too is
                                            COPIED (checked file by file against the original); the others are MOVED.
                                            A profile that can't be read counts as using everything. The other profiles
                                            are never changed. A path outside the folder stays pointing where it did.

One merging.build.Operation, journaled in roundtable/<game>/profiles (so operations.recover finds it): the copies are
staged and verified first, the sources go only as part of the commit (a rename for a moved folder; the .me3 and its
records are removed by a journal step that keeps their bytes), and an interruption is undone as a whole. Undo
(undo_move_in) puts everything back; what it leaves in the new folder (the copies) goes to the Recycle Bin. Same drive
only: moving across drives would need a copy and a delete outside the journal, so it is refused.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.formats import me3_profile
from roundtable_souls.merging import build
from roundtable_souls.mods import library, migrate, naming, operations
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.migrate import Item, Unit
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.platform import files

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "profile-move-in"
GAME_OPEN = "Close the game first: it has these files open."


class MoveInError(ModError):
    pass


@dataclass
class MovePlan:
    profile: Path
    game: str
    root: Path | None = None  # roundtable/<game>
    profiles: Path | None = None  # roundtable/<game>/profiles: the new folder's parent, and where the journal lives
    item: Item | None = None
    whole: bool = False  # the profile's own folder moves as it is
    moved: list[Unit] = field(default_factory=list)
    copied: list[Unit] = field(default_factory=list)
    stays: list[str] = field(default_factory=list)  # entries pointing outside the folder: left where they are
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals and self.item is not None and self.profiles is not None

    @property
    def source_folder(self) -> Path:
        return self.profile.parent


def _n(p: Path | str) -> str:
    return migrate._n(p)


def _inside(p: Path | str, folder: Path | str) -> bool:
    return migrate._inside(p, folder)


def _rows(profile: Path) -> tuple[bytes, list[dict]]:
    raw = Path(profile).read_bytes()
    text = raw.decode("utf-8")
    if me3_profile.is_array_form(text):
        text = me3_profile.to_blocks(text)
    return raw, me3_profile.entries(text)


def outside(profile: Path, loc: Locations) -> bool:
    """Whether the profile is outside Bayle's folder (the Mods page offers the move only then)."""
    home = loc.me3_profiles_dir()
    return home is not None and not _inside(profile, library.game_root(home, loc.game.key))


def _same_drive(a: Path, b: Path) -> bool:
    while not b.exists() and b != b.parent:
        b = b.parent
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


# ----------------------------------------------------------------------------- the plan
def plan(profile: Path, loc: Locations) -> MovePlan:
    """What moving the profile does, with nothing written. Every reason it can't be done is a refusal."""
    profile = Path(profile)
    out = MovePlan(profile, loc.game.key)
    refuse = out.refusals.append
    home = loc.me3_profiles_dir()
    if home is None:
        refuse("The me3 profiles folder is not known, so there is nowhere to move it to.")
        return out
    out.root = library.game_root(home, loc.game.key)
    out.profiles = library.profiles_root(home, loc.game.key)
    name = profile.stem
    if not profile.is_file():
        refuse(f"{profile.name} is not there any more.")
        return out
    if _inside(profile, out.root):
        refuse(f"{name} is already in Bayle's folder.")
        return out
    if profile.name.lower().endswith(("-default.me3", migrate.OFFLINE)):
        refuse(f"{profile.name} is made by me3 itself, so it can't be moved.")
        return out
    if loc.game_running():
        refuse(GAME_OPEN)
    if (why := operations.problem(profile)) is not None:
        refuse(f"Another change to this profile is not finished: {why}")
    folder = out.profiles / name
    if folder.exists():
        refuse(f"{folder.relative_to(home)} already exists. Rename the profile, then try again.")
    elif why := naming.path_problem(folder / f"{name}.me3", 0):
        refuse(why)
    if not _same_drive(profile.parent, out.profiles):
        refuse("Bayle's folder is on another drive than this profile, so it can't be moved there.")
    try:
        raw, rows = _rows(profile)
    except (OSError, ValueError) as e:
        refuse(f"{profile.name} could not be read ({e}).")
        return out
    out.whole = library.own_folder(profile)
    src = out.source_folder
    layout = library.ProfileFolder(folder)
    item = Item(profile, name, folder, library.state_of(profile).root, old_bytes=raw)
    seen: set[str] = set()
    from roundtable_souls import overhauls
    from roundtable_souls.mods import overhaul_install

    # an overhaul's own folder is part of the profile's layout, at its root: it moves whole, not entry by entry
    owns = [Path(os.path.abspath(o)) for o in overhaul_install.own_folders(profile, rows, overhauls.load(loc.game.key))]
    for e in rows:
        if not e.get("path"):
            continue
        target = Path(os.path.abspath(me3_profile.resolve(profile, e["path"])))
        if not target.exists():
            refuse(f"{e.get('name') or e['path']} is not there ({target}). Remove it from the profile or put it back.")
            continue
        if not _inside(target, src) or _n(target) == _n(src) or _inside(target, src / library.STATE):
            out.stays.append(str(target))
            continue
        own = next((o for o in owns if _inside(target, o) and _n(o) != _n(src)), None)
        if own is not None:
            if _n(own) not in seen:
                seen.add(_n(own))
                item.units.append(Unit(own, own.name, [name]))
            continue
        unit_src = target if target.is_dir() or _n(target.parent) == _n(src) else target.parent
        if _n(unit_src) in seen:
            continue
        seen.add(_n(unit_src))
        sub = (layout.packages if e["kind"] == "package" else layout.natives).name
        rel, k = f"{sub}/{unit_src.name}", 2
        while rel.lower() in {u.dest_rel.lower() for u in item.units}:
            rel, k = f"{sub}/{unit_src.name}-{k}", k + 1
        item.units.append(Unit(unit_src, rel, [name]))
    for a in item.units:
        for b in item.units:
            if a is not b and _inside(a.src, b.src):
                refuse(f"{b.src.name} and {a.src.name} overlap, so they can't be moved apart.")
    if out.whole:
        out.moved = list(item.units)
        item.units = [Unit(src, "", [name])]
    else:
        shared = _shared(profile, src, [u.src for u in item.units])
        out.copied = [u for u in item.units if _n(u.src) in shared]
        out.moved = [u for u in item.units if _n(u.src) not in shared]
        mine = library.ProfileFolder.of(profile).builds
        if mine.is_dir():  # its builds (Combine, an overhaul) follow it
            builds = Unit(mine, layout.builds.name, [name])
            item.units.append(builds)
            out.moved.append(builds)
    out.item = item
    if out.ok:
        item.new_bytes = migrate._rewrite(item)
    return out


def _shared(profile: Path, folder: Path, units: list[Path]) -> set[str]:
    """The (normalised) unit folders another profile of `folder` lists too. A profile that can't be read counts as
    using every one."""
    used: set[str] = set()
    try:
        others = [
            p for p in folder.glob("*.me3") if _n(p) != _n(profile) and not p.name.lower().endswith(migrate.OFFLINE)
        ]
    except OSError:
        return {_n(u) for u in units}
    for other in others:
        try:
            _raw, rows = _rows(other)
        except OSError, ValueError:
            return {_n(u) for u in units}
        for e in rows:
            if e.get("path"):
                t = os.path.abspath(me3_profile.resolve(other, e["path"]))
                used.update(_n(u) for u in units if _inside(t, u))
    return used


def counts(p: MovePlan) -> tuple[int, int]:
    """(mods that move, mods that are copied) for the confirm."""
    layout = library.ProfileFolder(Path("x"))
    mods = (layout.packages.name, layout.natives.name)
    return len([u for u in p.moved if u.dest_rel.split("/")[0] in mods]), len(p.copied)


# ----------------------------------------------------------------------------- apply
def recover(loc: Locations) -> list[str]:
    """Undo a move that was interrupted (the previous layout stands) and finish the records of one that was done."""
    home = loc.me3_profiles_dir()
    if home is None:
        return []
    profiles = library.profiles_root(home, loc.game.key)
    if not (profiles / build.OPS).is_dir():
        return []
    said = build.recover_operations(profiles, 30.0, build.OPS)
    for op in build.active(profiles, build.OPS):
        if op.info.get("kind") == KIND and not op.info.get("state_done"):
            finish_state(op)
            said.append("an interrupted move into Bayle's folder was finished")
    for stage in profiles.glob(".move-in-*"):
        try:
            stage.rmdir()
        except OSError:
            pass
    return said


def apply(p: MovePlan, *, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Move as planned. Returns {operation, profile (the new path), name, notes}. Raises MoveInError, with nothing
    changed, when it can't be done now."""
    if not p.ok or p.item is None or p.profiles is None:
        raise MoveInError(" ".join(p.refusals) or "Nothing to move.")
    item, profiles = p.item, p.profiles
    profiles.mkdir(parents=True, exist_ok=True)
    with build.ops_lock(profiles, 30.0):
        recover(loc)
        if why := _changed(p):
            raise MoveInError(why)
        op = build.Operation(profiles, f"move of profile {item.name} into Bayle's folder")
        stage = profiles / f".move-in-{op.id}"
        try:
            _prepare(p, op, stage)
        except BaseException:
            op.discard()
            shutil.rmtree(stage, ignore_errors=True)
            raise
        try:
            op.commit(refuse=lambda: GAME_OPEN if loc.game_running() else _changed(p))
        except build.BuildError as e:
            shutil.rmtree(stage, ignore_errors=True)
            raise MoveInError(str(e)) from e
        shutil.rmtree(stage, ignore_errors=True)
        notes = finish_state(op)
    log(f"moved profile {item.name} into Bayle's folder")
    return {"operation": str(op.dir), "profile": str(item.new), "name": item.name, "notes": notes}


def _changed(p: MovePlan) -> str | None:
    assert p.item is not None
    if not p.profile.is_file() or p.profile.read_bytes() != p.item.old_bytes:
        return f"{p.profile.name} changed since it was checked; try again."
    if p.item.folder.exists():
        return f"{p.item.name} already exists in Bayle's folder. Rename the profile, then try again."
    return None


def _dump(data: dict) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode()


def _prepare(p: MovePlan, op: build.Operation, stage: Path) -> None:
    item, src = p.item, p.source_folder
    assert item is not None
    sha = migrate._sha
    if p.whole:
        if item.new_bytes != item.old_bytes:  # absolute paths into the folder follow it
            op.write_file(p.profile, item.new_bytes, expect=sha(item.old_bytes))
        op.move_folder(src, item.folder)
    else:
        stage.mkdir(parents=True)
        sd = stage / item.name
        sd.mkdir()
        (sd / item.new.name).write_bytes(item.new_bytes)
        offline = p.profile.with_name(item.name + migrate.OFFLINE)
        if offline.is_file():
            shutil.copy2(offline, sd / offline.name)
        own_state = sd / library.STATE
        own_state.mkdir()
        files.hide(own_state)
        settings = ps._current(p.profile)
        data = ps._read(settings)
        entry = (data.get("profiles") or {}).get(p.profile.name)
        if isinstance(entry, dict):
            body = {"version": 1, "schema": 1, "profiles": {item.new.name: migrate._restored(entry, item)}}
            (own_state / library.SETTINGS).write_text(_dump(body).decode(), encoding="utf-8")
        baks = [
            b
            for b in (
                library.state_of(p.profile).backups / (p.profile.name + ".bak"),
                p.profile.with_name(p.profile.name + ".bak"),
            )
            if b.is_file()
        ]
        if baks:
            (own_state / library.BACKUPS).mkdir()
            shutil.copy2(baks[0], own_state / library.BACKUPS / f"{item.new.name}.bak")
        for u in p.copied:
            (sd / u.dest_rel).parent.mkdir(parents=True, exist_ok=True)
            try:
                migrate._copy_verified(u.src, sd / u.dest_rel)
            except migrate.MigrateError as e:
                raise MoveInError(str(e)) from e
        op.replace_folder(item.folder, sd)
        for u in p.moved:
            op.move_folder(u.src, item.folder / u.dest_rel)
        for gone in (p.profile, offline, *baks):
            if gone.is_file():
                op.write_file(gone, None, expect=sha(gone.read_bytes()))
        if isinstance(entry, dict):
            rest = {**data, "profiles": {k: v for k, v in data["profiles"].items() if k != p.profile.name}}
            op.write_file(settings, _dump(rest), expect=sha(settings.read_bytes()))
    moves = item.units if p.whole else p.moved
    op.note(
        kind=KIND,
        name=item.name,
        game=p.game,
        profile=str(item.new),
        old_profile=str(p.profile),
        root=str(p.profiles),
        folder=str(item.folder),
        whole=p.whole,
        source=str(src),
        moves=[{"src": str(u.src), "dest": str(item.folder / u.dest_rel)} for u in moves],
        pairs=[[str(u.src), str(item.folder / u.dest_rel)] for u in moves],
        profiles=[{"old": str(p.profile), "new": str(item.new)}],
        new_sha=sha(item.new_bytes),
        state_done=False,
    )


# ----------------------------------------------------------------------------- after the commit
def finish_state(op: build.Operation) -> list[str]:
    """Re-key the launcher's own records for a move that is done, then say so in its journal. Safe to run again."""
    notes = migrate._apply_state(op.info)
    op.note(state_done=True)
    return notes


# ----------------------------------------------------------------------------- taking it back
def undo_move_in(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Put the profile and its mods back where they were. Raises MoveInError, nothing changed, when the profile
    changed since, or an old place is taken again. What is left of the new folder (the copies) goes to the Recycle Bin."""
    from roundtable_souls.platform import trash

    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise MoveInError("This move can no longer be taken back.")
    if not trash.available():
        raise MoveInError("There is no Recycle Bin to put the new folder in, so nothing was changed.")
    root, folder, new, old = Path(info["root"]), Path(info["folder"]), Path(info["profile"]), Path(info["old_profile"])
    whole, source = info["whole"], Path(info["source"])
    sha = migrate._sha
    if not new.is_file():
        raise MoveInError(f"{new.name} is no longer in its folder, so the move can't be taken back.")
    if sha(new.read_bytes()) != info["new_sha"]:
        raise MoveInError(
            f"{new.name} changed after it was moved. Undoing would lose those changes, so everything is left as it is."
        )
    taken = source if whole else old
    if taken.exists():
        raise MoveInError(f"{taken.name} is back at its old place; undoing would overwrite it.")
    for m in info["moves"]:
        if not Path(m["dest"]).exists() or Path(m["src"]).exists():
            raise MoveInError(f"{Path(m['src']).name} is not where the move left it, so it is left as it is.")
    steps = [s for s in op.steps if s["type"] == "file"]
    with build.ops_lock(root, 30.0):
        back = build.Operation(root, f"undo of the move of profile {info['name']}")
        try:
            if whole:
                first = next((s for s in steps if s["live"] == str(old)), None)
                if first is not None:  # the .me3 as it was, inside the folder where it is now
                    back.write_file(new, (op.dir / first["before"]).read_bytes(), expect=info["new_sha"])
                back.move_folder(folder, source)
            else:
                for m in info["moves"]:
                    back.move_folder(Path(m["dest"]), Path(m["src"]))
                for s in steps:
                    live = Path(s["live"])
                    before = (op.dir / s["before"]).read_bytes()
                    live.parent.mkdir(parents=True, exist_ok=True)
                    if not s["after"]:
                        back.write_file(live, before, expect="missing")
                        continue
                    # the shared settings file: as it was when untouched since, else with this profile's entry back
                    now = live.read_bytes()
                    if now != (op.dir / s["after"]).read_bytes():
                        mine = ps._read(folder / library.STATE / library.SETTINGS).get("profiles") or {}
                        was = ps._read(live)
                        kept = {**(was.get("profiles") or {})}
                        if mine.get(new.name) is not None:
                            kept[old.name] = mine[new.name]
                        before = _dump({**was, "profiles": kept})
                    back.write_file(live, before, expect=sha(now))
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()
        op.release()
    if not whole:
        try:
            trash.send(folder)
        except OSError as e:
            log(f"undo: {folder} could not be moved to the Recycle Bin ({e})")
    for n in migrate._apply_state(info, back=True):
        log(f"undo: {n}")
    return f"took back the move of {info['name']}: it is where it was"
