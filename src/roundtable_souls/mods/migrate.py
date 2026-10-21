"""The one-time move from the shared library (rs-<game> in me3's profiles folder, 3.21 to 4.0.x) to a folder of its own
for every profile (mods.library):

    rs-<game>/profiles/<name>.me3        ->  profiles/<name>/<name>.me3
    rs-<game>/packages/<id>/             ->  profiles/<name>/mod/<id>/        (moved; copied when another profile uses it)
    rs-<game>/natives/<id>/              ->  profiles/<name>/natives/<id>/    (likewise)
    rs-<game>/builds/<what>/<name>/      ->  profiles/<name>/builds/<what>/
    rs-<game>/sources/<id>, overhauls/<id> -> profiles/<name>/builds/<id>/sources, overhaul (likewise)
    rs-<game>/.roundtable                ->  the profile's own settings entry and .bak, in profiles/<name>/.roundtable

All of it is one journaled operation (merging.build.Operation, journal in the profiles folder): an interruption is
undone as a whole by the next start. A mod folder several profiles use is copied for all but the last, which takes the
original; every copy is checked file by file against its source before anything is committed, so no source is ever
gone without a verified copy. The profile text is rewritten with the paths its entries now need. A clash with an
existing folder takes <name>-2. Profiles outside rs-<game>/profiles are never touched; rs-<game> goes only when
nothing but empty folders and lock files is left in it. Same drive only (it is all inside me3's profiles folder).
Undo (undo_migration) puts everything back; the folders it made go to the Recycle Bin.
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

from roundtable_souls.formats import me3_profile
from roundtable_souls.merging import build
from roundtable_souls.mods import history, library
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.profile_writer import ProfileWriter
from roundtable_souls.platform import files

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "profile-folders"  # the operation's kind in its journal and the Activity undo record's type
PREFIX = "rs-"  # the old library folder: rs-<game key>
OFFLINE = ".offline.me3"


class MigrateError(RuntimeError):
    pass


def _n(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _inside(p: Path | str, folder: Path | str) -> bool:
    a, b = _n(p), _n(folder)
    return a == b or a.startswith(b + os.sep)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def legacy_root(home: Path, game: str) -> Path:
    return Path(home) / f"{PREFIX}{game}"


def old_profiles(home: Path, game: str) -> list[Path]:
    """The profiles still in rs-<game>/profiles (the offline copies are not profiles)."""
    folder = legacy_root(home, game) / "profiles"
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.glob("*.me3") if p.is_file() and not p.name.lower().endswith(OFFLINE)),
        key=lambda p: p.name.lower(),
    )


# ----------------------------------------------------------------------------- the plan
@dataclass
class Unit:
    """One folder of the library and the profiles that use it."""

    src: Path
    dest_rel: str  # inside the profile's folder
    users: list[str] = field(default_factory=list)  # old profile names


@dataclass
class Item:
    old: Path
    name: str  # the folder and profile name now
    folder: Path
    units: list[Unit] = field(default_factory=list)
    old_bytes: bytes = b""
    new_bytes: bytes = b""

    @property
    def new(self) -> Path:
        return self.folder / f"{self.name}.me3"

    def where(self, target: Path) -> Path:
        """target as it is once this profile has its own folder."""
        for u in self.units:
            if _inside(target, u.src):
                return self.folder / u.dest_rel / Path(os.path.abspath(target)).relative_to(os.path.abspath(u.src))
        return target


@dataclass
class Plan:
    home: Path
    game: str
    root: Path
    items: list[Item] = field(default_factory=list)
    units: dict[str, Unit] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def plan(home: Path, game: str) -> Plan:
    """What the migration does, with nothing written."""
    home = Path(home)
    root = legacy_root(home, game)
    out = Plan(home, game, root)
    taken = {p.name.lower() for p in home.iterdir()} if home.is_dir() else set()
    unit_of: dict[str, Unit] = {}

    def unit(src: Path, rel: str, user: str) -> None:
        u = unit_of.setdefault(_n(src), Unit(src, rel))
        if user not in u.users:
            u.users.append(user)

    readable: list[tuple[Path, bytes, list[dict]]] = []
    for p in old_profiles(home, game):
        try:
            raw = p.read_bytes()
            text = raw.decode("utf-8")
            if me3_profile.is_array_form(text):
                text = me3_profile.to_blocks(text)
            readable.append((p, raw, me3_profile.entries(text)))
        except (OSError, ValueError) as e:
            out.notes.append(f"{p.name} could not be read ({e}), so it stays where it is")
    for p, raw, rows in readable:
        name = p.stem
        k = 2
        while name.lower() in taken:
            name, k = f"{p.stem}-{k}", k + 1
        taken.add(name.lower())
        if name != p.stem:
            out.notes.append(f"A folder called {p.stem} was already there, so the profile is now {name}")
        out.items.append(Item(p, name, home / name, old_bytes=raw))
        for e in rows:
            if not e.get("path"):
                continue
            parts = _rel(Path(os.path.abspath(me3_profile.resolve(p, e["path"]))), root)
            if len(parts) >= 2 and parts[0] in ("packages", "natives"):
                unit(
                    root / parts[0] / parts[1],
                    ("mod" if parts[0] == "packages" else "natives") + "/" + parts[1],
                    p.stem,
                )
            elif len(parts) >= 3 and parts[0] == "builds" and parts[2].lower() == p.stem.lower():
                unit(root / "builds" / parts[1] / parts[2], f"builds/{parts[1]}", p.stem)
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
    out.units = unit_of
    by_name = {i.old.stem: i for i in out.items}
    for u in unit_of.values():
        for user in u.users:
            by_name[user].units.append(u)
    for item in out.items:
        item.new_bytes = _rewrite(item)
    return out


def _rel(path: Path, root: Path) -> tuple[str, ...]:
    try:
        return Path(path).relative_to(Path(os.path.abspath(root))).parts
    except ValueError:
        return ()


def _rewrite(item: Item) -> bytes:
    """The profile text with every entry path as the new place needs it: a relative one stays relative, to the new
    folder; one inside a moved folder follows it; others point where they did."""
    w = ProfileWriter(item.old)
    for e in w.entries():
        if not e["path"]:
            continue
        target = Path(os.path.abspath(me3_profile.resolve(item.old, e["path"])))
        now = item.where(target)
        new = str(now).replace("\\", "/") if Path(e["path"]).is_absolute() else _relpath(now, item.folder)
        if new != e["path"]:
            w.set_path(e["index"], new)
    plan_ = w.plan(f"before moving {item.old.name}")
    return plan_.bytes_to_write if w.text != item.old_bytes.decode("utf-8") else item.old_bytes


def _relpath(target: Path, folder: Path) -> str:
    try:
        return os.path.relpath(target, folder).replace("\\", "/")
    except ValueError:  # another drive
        return str(target).replace("\\", "/")


# ----------------------------------------------------------------------------- applying
def _tree(folder: Path) -> dict[str, tuple[int, str]]:
    return {
        p.relative_to(folder).as_posix(): (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _copy_verified(src: Path, dst: Path) -> None:
    """src copied to dst and read back: every file and its bytes must be the same, else nothing is kept."""
    shutil.copytree(src, dst)
    if _tree(src) != _tree(dst):
        raise MigrateError(f"The copy of {src.name} does not match the original, so nothing was moved.")


def migrate(loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict | None:
    """Move rs-<game>'s profiles into folders of their own, as one operation. None when there is nothing to do (also on
    a second run). Raises MigrateError, with nothing changed, when it can't be done now."""
    home = loc.me3_profiles_dir()
    if home is None or not old_profiles(home, loc.game.key):
        return None
    if loc.game_running():
        return None  # tried again at the next start
    with build.ops_lock(home):
        finish_pending(home)
        p = plan(home, loc.game.key)
        if not p.items:
            return None
        op = build.Operation(home, f"moving {len(p.items)} profile(s) of {loc.game.key} into their own folders")
        stage = home / f".rs-profile-folders-{op.id}"
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
    log(f"moved {len(p.items)} profile(s) of {loc.game.key} into folders of their own")
    return {
        "operation": str(op.dir),
        "profile": str(p.items[0].new),
        "profiles": [str(i.new) for i in p.items],
        "notes": [*p.notes, *notes],
        "game": loc.game.key,
    }


def _changed(p: Plan) -> bool:
    return any(not i.old.is_file() or i.old.read_bytes() != i.old_bytes for i in p.items)


def _prepare(p: Plan, op: build.Operation, stage: Path) -> None:
    stage.mkdir(parents=True)
    root, state = p.root, p.root / library.STATE
    old_settings = state / library.SETTINGS
    data = ps._read(old_settings) if old_settings.is_file() else {}
    moves: list[dict] = []
    for item in p.items:
        sd = stage / item.name
        sd.mkdir()
        (sd / f"{item.name}.me3").write_bytes(item.new_bytes)
        offline = item.old.with_name(item.old.stem + OFFLINE)
        if offline.is_file():
            shutil.copy2(offline, sd / f"{item.name}.offline.me3")
        own_state = sd / library.STATE
        own_state.mkdir()
        files.hide(own_state)
        entry = (data.get("profiles") or {}).get(item.old.name)
        if isinstance(entry, dict):
            (own_state / library.SETTINGS).write_text(
                json.dumps(
                    {"version": 1, "schema": 1, "profiles": {f"{item.name}.me3": _restored(entry, item)}},
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        bak = state / library.BACKUPS / (item.old.name + ".bak")
        if bak.is_file():
            (own_state / library.BACKUPS).mkdir()
            shutil.copy2(bak, own_state / library.BACKUPS / f"{item.name}.me3.bak")
        for u in item.units:
            if u.users[-1] != item.old.stem and u.src.is_dir():  # all but the last user get a verified copy
                (sd / u.dest_rel).parent.mkdir(parents=True, exist_ok=True)
                _copy_verified(u.src, sd / u.dest_rel)
        op.replace_folder(item.folder, sd)
    for item in p.items:
        for u in item.units:
            if u.users[-1] == item.old.stem and u.src.is_dir():  # the last user takes the original
                op.move_folder(u.src, item.folder / u.dest_rel)
                moves.append({"src": str(u.src), "dest": str(item.folder / u.dest_rel)})
    for item in p.items:
        op.write_file(item.old, None, expect=_sha(item.old_bytes))
        offline = item.old.with_name(item.old.stem + OFFLINE)
        if offline.is_file():
            op.write_file(offline, None, expect=_sha(offline.read_bytes()))
        bak = state / library.BACKUPS / (item.old.name + ".bak")
        if bak.is_file():
            op.write_file(bak, None, expect=_sha(bak.read_bytes()))
    if old_settings.is_file() and set(data.get("profiles") or {}) <= {i.old.name for i in p.items}:
        op.write_file(old_settings, None, expect=_sha(old_settings.read_bytes()))
    ordered = [(Path(m["src"]), Path(m["dest"])) for m in moves]
    pairs = list(ordered)
    for item in p.items:  # a path of the old library follows to the first profile that has it
        for u in item.units:
            if not any(_n(s) == _n(u.src) for s, _d in pairs):
                pairs.append((u.src, item.folder / u.dest_rel))
    op.note(
        kind=KIND,
        name=p.game,
        game=p.game,
        profile=str(p.items[0].new),
        home=str(p.home),
        root=str(root),
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
def finish_pending(home: Path) -> list[str]:
    """Undo a migration that was interrupted, and finish the launcher's records of one that was done (see
    finish_state). Safe to run again."""
    said = build.recover_operations(home, 30.0, build.OPS)
    for op in build.active(home, build.OPS):
        if op.info.get("kind") == KIND and not op.info.get("state_done"):
            finish_state(op)
            said.append("an interrupted move of the profiles into their folders was finished")
    for stage in Path(home).glob(".rs-profile-folders-*"):  # what an interrupted run staged: emptied by the recovery
        try:
            stage.rmdir()
        except OSError:
            pass
    return said


def finish_state(op: build.Operation) -> list[str]:
    """Re-key the launcher's own records for a migration that is done (the settings it remembers, the version history),
    clear what it left in rs-<game>, then say so in its journal. Safe to run again."""
    notes = _apply_state(op.info)
    _tidy(Path(op.info["root"]))
    op.note(state_done=True)
    return notes


def _tidy(root: Path) -> None:
    """rs-<game> goes when only empty folders and lock files are left in it; anything else keeps it."""
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        try:
            if p.is_file() and p.name.endswith(".lock") and p.stat().st_size == 0:
                p.unlink()
            elif p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass
    try:
        if not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


def _remap(value: str, pairs: list[tuple[Path, Path]]) -> str:
    for src, dst in pairs:
        if _inside(value, src):
            return str(dst / Path(os.path.abspath(value)).relative_to(os.path.abspath(src)))
    return value


def _apply_state(info: dict, *, back: bool = False) -> list[str]:
    from roundtable_souls.config import settings as launcher_settings
    from roundtable_souls.mods.rebuild import _key

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
        launcher_settings.change_settings(change)
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
    """Put rs-<game> back as it was (see the module notes). Raises MigrateError, nothing changed, when a migrated
    profile changed since, or an old place is taken again. The profiles' new folders go to the Recycle Bin after
    their mods are back."""
    from roundtable_souls.platform import trash

    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise MigrateError("This move can no longer be taken back.")
    if not trash.available():
        raise MigrateError("There is no Recycle Bin to put the profiles' new folders in, so nothing was changed.")
    home = Path(info["home"])
    profs, moves = info["profiles"], info["moves"]
    with build.ops_lock(home):
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
            if not Path(m["dest"]).is_dir() or Path(m["src"]).exists():
                raise MigrateError(f"{Path(m['src']).name} is not where the move left it, so it is left as it is.")
        back = build.Operation(home, f"undo of the move of {info.get('game', '')} profiles")
        try:
            for m in moves:
                back.move_folder(Path(m["dest"]), Path(m["src"]))
            for step in op.steps:  # the files removed from rs-<game> come back with their earlier bytes
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
    return "took back the move into profile folders: rs-" + str(info.get("game", "")) + " is as it was"
