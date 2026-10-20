"""Adopting an existing setup into the library (mods.library): the folder a game's profiles and their mods live in
today becomes rs-<game>, with the mods in packages/ and natives/ and the profiles in profiles/.

    setups      the folders holding user profiles for the game (outside the library), with those profiles
    preview     what adopting one does, worked out with nothing written: each mod folder's new place, each profile's
                new text (its paths rewritten, everything else as written), what stays where it is and why
    adopt       one journaled operation (merging.build.Operation, in the library's .roundtable/ops): the folders are
                renamed into the library, the new profiles written, the old ones removed; then the launcher's own
                records follow (ties, overlay marks, the remembered setup, per-profile settings, .bak, history)
    undo_adopt  the moves back and each profile's exact earlier bytes; refused, with the reason, when an adopted
                profile changed since

Everything is a rename on one drive: no copy of a mod, no extra space, nothing deleted. A mod folder one profile of
the setup uses is moved once however many profiles use it. What the library cannot take stays where it is and is
said: an entry outside the setup's folder, a DLL loose in a shared folder, a mod another game's profile uses. A setup
with an overhaul is not adopted yet (its folder is found beside the profile, mods.overhaul_install.own_folder).

The launcher's records (launcher_settings.json, the per-profile settings) are not in the journal: the window writes
the first one often, so putting its old bytes back would lose those writes. They are re-keyed after the moves, by a
mapping that can be applied twice (a recovery after an interruption does), and mapped back by an undo.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.formats import me3_profile
from roundtable_souls.merging import build
from roundtable_souls.mods import history, library, naming, operations
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.platform import paths

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "library-adopt"  # the operation's kind in its journal, and the Activity undo record's type
PACKAGE_CONTAINERS = ("mod", "mods", "packages")  # folders that hold many mods: never a mod themselves
NATIVE_CONTAINERS = ("natives", "dll", "dlls")
_PATH_LINE = re.compile(r"^(\s*(?:path|source)\s*=\s*)('[^']*'|\"(?:[^\"\\]|\\.)*\")(.*)$", re.S)


class AdoptError(ModError):
    pass


@dataclass(frozen=True)
class Setup:
    folder: Path
    profiles: tuple[Path, ...]


@dataclass
class Move:
    src: Path
    dest: Path
    kind: str  # package, native, build (Combine's package) or unused
    id: str


@dataclass
class Rewrite:
    old: Path
    new: Path
    old_bytes: bytes
    text: str

    @property
    def new_bytes(self) -> bytes:
        return self.text.encode("utf-8")


@dataclass
class AdoptPreview:
    setup: Setup
    library: library.ModLibrary | None
    game: str
    moves: list[Move] = field(default_factory=list)
    rewrites: list[Rewrite] = field(default_factory=list)
    stays: list[str] = field(default_factory=list)
    unused: list[Path] = field(default_factory=list)  # folders in the setup's mod folders no profile uses
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals


def _n(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def _inside(inner: str, outer: str) -> bool:
    """inner is below outer (both _n'd)."""
    return inner.startswith(outer + os.sep)


# ----------------------------------------------------------------------------- finding setups
def setups(loc: Locations) -> list[Setup]:
    """The folders holding the game's user profiles that are not in the library, each with its profiles."""
    root = loc.me3_profiles_dir()
    found: dict[Path, list[Path]] = {}
    for p in loc.me3_profiles():
        if p.name.endswith(".offline.me3") or library.library_of(p) is not None:
            continue
        if root is not None and any(a.parent == root and a.name.startswith(library.PREFIX) for a in p.parents):
            continue
        found.setdefault(p.parent, []).append(p)
    return [Setup(f, tuple(sorted(ps_, key=lambda x: x.name.lower()))) for f, ps_ in sorted(found.items())]


# ----------------------------------------------------------------------------- previewing
def _foreign(loc: Locations, mine: set[str]) -> list[str]:
    """Where the entries of the other profiles in the profiles folder (other games', those not in this setup) point."""
    root = loc.me3_profiles_dir()
    out: list[str] = []
    if root is None:
        return out
    for f in paths._iter_me3_files(root):
        if _n(f) in mine or library.library_of(f) is not None or f.name.endswith(".offline.me3"):
            continue
        try:
            rows = me3_profile.entries(me3_profile.read_text(f))
        except OSError, ValueError:
            continue
        out += [_n(me3_profile.resolve(f, r["path"])) for r in rows if r.get("path")]
    return out


def _deepest(folder: Path) -> int:
    n = 0
    for here, _dirs, names in os.walk(folder):
        base = len(os.path.relpath(here, folder)) + 1 if here != str(folder) else 0
        n = max([n, *(base + len(x) for x in names)])
    return n


def _lit(path: str) -> str:
    path = path.replace("\\", "/")
    return f"'{path}'" if "'" not in path else me3_profile.quote(path)


def _remap(path: str, pairs: list[tuple[Path, Path]], norm: bool = False) -> str:
    """path with the folder it is inside (a pair's first) replaced by that pair's second."""
    here = os.path.abspath(path)
    low = os.path.normcase(here)
    for src, dest in pairs:
        s = _n(src)
        if low == s or _inside(low, s):
            out = os.path.abspath(dest) + here[len(s) :]
            return os.path.normcase(out) if norm else out
    return path if not norm else low


def _rewrite(text: str, rows: list[dict], where, lib: library.ModLibrary, moved: list[Move]) -> str:
    """The profile text with each entry's path pointing at its place from the library's profiles folder (a new id for
    a package without one whose folder gets a new name, so the load_after lines naming it stay true)."""
    nl = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    pairs = [(m.src, m.dest) for m in moved]
    for b, e in reversed(list(zip(me3_profile.blocks(text), rows, strict=True))):
        if not e["path"]:
            continue
        old_abs = Path(os.path.abspath(where(e["path"])))
        new_abs = Path(_remap(str(old_abs), pairs))
        if new_abs == old_abs and Path(e["path"]).is_absolute():
            continue  # outside the setup and written in full: as it was
        try:
            new = Path(os.path.relpath(new_abs, lib.profiles)).as_posix()
        except ValueError:  # another drive: no relative path exists
            new = new_abs.as_posix()
        block = list(b["lines"])
        i = next((k for k, line in enumerate(block) if _PATH_LINE.match(line.rstrip("\r\n"))), None)
        if i is None:
            continue
        keep = block[i][len(block[i].rstrip("\r\n")) :]
        m = _PATH_LINE.match(block[i].rstrip("\r\n"))
        assert m is not None
        block[i] = f"{m.group(1)}{_lit(new)}{m.group(3)}{keep}"
        if e["kind"] == "package" and not e["id"] and new_abs != old_abs and new_abs.name != old_abs.name:
            block.insert(i, f"id = {me3_profile.quote(old_abs.name)}{nl}")
        lines[b["start"] : b["end"]] = block
    return "".join(lines)


def preview(setup: Setup, *, loc: Locations, move_unused: tuple[Path, ...] | list[Path] = ()) -> AdoptPreview:
    """What adopting this setup does (see the module notes). Nothing is written. move_unused: the unused folders
    (preview.unused) to move too; the others stay."""
    from roundtable_souls import overhauls
    from roundtable_souls.mods import overhaul_install
    from roundtable_souls.mods.backends import builtin

    lib = library.ModLibrary.for_game(loc)
    out = AdoptPreview(setup, lib, loc.game.key)
    folder = setup.folder
    if lib is None:
        out.refusals.append("There is no me3 profiles folder on this PC to make the library in.")
        return out
    for p in setup.profiles:
        left = operations.pending(p)
        if left:
            out.refusals.append(f"The {left[0]} in {p.name}'s folder did not finish; open the Mods page to finish it.")
    # an overhaul: its folder is found beside the profile, so the setup cannot move yet
    named = []
    for cfg in overhauls.load(loc.game.key):
        if (folder / cfg.recognise.folder).is_dir() or any(
            overhaul_install.overhaul_in(p, [cfg]) for p in setup.profiles
        ):
            named.append(cfg.short_label)
    if named:
        out.refusals.append(
            f"This setup has {', '.join(named)}. It can be adopted once the launcher builds it itself; until then it "
            "stays where it is (you can still launch and remove it)."
        )
    texts: dict[Path, tuple[bytes, str, list[dict]]] = {}
    for p in setup.profiles:
        try:
            raw = p.read_bytes()
            text = raw.decode("utf-8")
            if me3_profile.is_array_form(text):
                text = me3_profile.to_blocks(text)
            texts[p] = (raw, text, me3_profile.entries(text))
        except (OSError, ValueError) as e:  # UnicodeDecodeError and the TOML error are ValueErrors
            out.refusals.append(f"{p.name} could not be read: {e}")
        if lib.profile(p.stem).exists():
            out.refusals.append(f"The library already has a profile called {p.stem}.")
    if out.refusals:
        return out
    # the entries: where each points, and the folder of its own it would move with
    root_n = _n(folder)
    foreign = _foreign(loc, {_n(p) for p in setup.profiles})
    kinds: dict[str, tuple[Path, str]] = {}
    pointed: list[tuple[Path, str, Path]] = []  # (profile, kind, resolved path)
    for p, (_raw, _text, rows) in texts.items():
        for e in rows:
            if not e["path"]:
                continue
            target = Path(os.path.abspath(me3_profile.resolve(p, e["path"])))
            pointed.append((p, e["kind"], target))
            unit = target if e["kind"] == "package" else target.parent
            low = _n(unit)
            if not _inside(low, root_n) or unit.name.lower() in (*PACKAGE_CONTAINERS, *NATIVE_CONTAINERS):
                continue
            if low not in kinds or e["kind"] == "package":
                kinds[low] = (unit, e["kind"])
    tops = {k: v for k, v in kinds.items() if not any(_inside(k, o) for o in kinds)}
    held: list[str] = []  # units another profile uses: they stay, and so do the entries pointing into them
    for k, (unit, _kind) in list(tops.items()):
        if any(f == k or _inside(f, k) or _inside(k, f) for f in foreign):
            del tops[k]
            held.append(k)
            out.stays.append(f"{unit.name} stays where it is: another profile in the profiles folder uses it")
    # where each goes
    contents = lib.scan()
    taken = {m for names in contents.mods.values() for m in names}
    by_profile = {p: lib.profile(p.stem) for p in texts}
    combined_user: dict[str, Path] = {}
    for p, _kind, target in pointed:
        low = _n(target)
        if low in tops and builtin.is_combined(tops[low][0]):
            combined_user.setdefault(low, p)
    for low, (unit, kind) in sorted(tops.items()):
        if low in combined_user:
            dest = lib.build(builtin.FOLDER, combined_user[low].stem).root
            move = Move(unit, dest, "build", builtin.FOLDER)
        else:
            ident = naming.unique(naming.mod_id(unit.name), taken)
            taken.add(ident)
            move = Move(unit, lib.package(ident) if kind == "package" else lib.native(ident), kind, ident)
        _check_move(out, move, lib)
        out.moves.append(move)
    for p, _kind, target in pointed:
        low = _n(target)
        if any(low == h or _inside(low, h) for h in held):
            continue
        if not any(low == _n(m.src) or _inside(low, _n(m.src)) for m in out.moves):
            out.stays.append(f"{p.name}: {target} stays where it is" + _why_stays(target, folder))
    # folders in the setup's mod folders nobody uses
    used = [_n(t) for _p, _k, t in pointed] + foreign
    for name in (*PACKAGE_CONTAINERS, *NATIVE_CONTAINERS):
        box = folder / name
        if not box.is_dir():
            continue
        for sub in sorted(box.iterdir(), key=lambda x: x.name.lower()):
            low = _n(sub)
            if (
                not sub.is_dir()
                or sub.name.startswith(".")
                or any(u == low or _inside(u, low) or _inside(low, u) for u in used)
            ):
                continue
            out.unused.append(sub)
            if any(_n(c) == low for c in move_unused):
                kind = "package" if name in PACKAGE_CONTAINERS else "native"
                ident = naming.unique(naming.mod_id(sub.name), taken)
                taken.add(ident)
                move = Move(sub, lib.package(ident) if kind == "package" else lib.native(ident), "unused", ident)
                _check_move(out, move, lib)
                out.moves.append(move)
    # the profiles' new text
    for p, (raw, text, rows) in texts.items():
        new = _rewrite(text, rows, lambda s, p=p: me3_profile.resolve(p, s), lib, out.moves)
        out.rewrites.append(Rewrite(p, by_profile[p], raw, new))
    _lines(out, folder)
    return out


def _why_stays(target: Path, folder: Path) -> str:
    low = _n(target)
    if not _inside(low, _n(folder)):
        return " (it is outside this setup's folder)"
    return " (it sits loose in a folder other mods share)"


def _check_move(out: AdoptPreview, move: Move, lib: library.ModLibrary) -> None:
    if move.dest.exists():
        out.refusals.append(f"{move.dest} is already there; {move.src.name} can't move into it.")
    if not build._same_drive(move.src, lib.root.parent):
        out.refusals.append(f"{move.src.name} is on another drive than the library; adopting moves, it does not copy.")
    problem = naming.path_problem(move.dest, _deepest(move.src))
    if problem is not None:
        out.refusals.append(problem)


def _lines(out: AdoptPreview, folder: Path) -> None:
    lib = out.library
    assert lib is not None
    names = ", ".join(p.name for p in out.setup.profiles)
    out.lines.append(
        f"{names} move{'s' if len(out.setup.profiles) == 1 else ''} to {lib.profiles}, with every mod path rewritten."
    )
    for m in out.moves:
        out.lines.append(f"{m.src.name} moves to {m.dest.relative_to(lib.root)}")
    out.lines += out.stays
    if out.unused:
        left = [u.name for u in out.unused if not any(m.src == u for m in out.moves)]
        if left:
            out.lines.append(f"Left where they are, no profile uses them: {', '.join(left)}")
    out.lines.append("Nothing is copied or deleted, and Undo adoption puts every file back.")


# ----------------------------------------------------------------------------- adopting
def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def adopt(p: AdoptPreview, *, loc: Locations, log=lambda s: None) -> dict:
    """Adopt as previewed, as one operation. Returns {operation, profiles, moved, notes}. Raises AdoptError (or
    merging.build.BuildError when a file changed meanwhile) with nothing changed."""
    lib = p.library
    if not p.ok or lib is None:
        raise AdoptError("; ".join(p.refusals) or "Nothing to adopt.")
    if loc.game_running():
        raise AdoptError("The game is running; close it first.")
    olds = [r.old for r in p.rewrites]
    with operations.lock(olds[0]), operations.lock(p.rewrites[0].new):
        for old in olds:
            operations.recover(old)
            if operations.pending(old):
                raise AdoptError(f"An earlier change to {old.name} did not finish; open the Mods page first.")
        for r in p.rewrites:
            if not r.old.is_file() or r.old.read_bytes() != r.old_bytes:
                raise AdoptError(f"{r.old.name} changed since the preview; preview again.")
        lib.ensure(lib.profiles, lib.packages, lib.natives)
        library.ensure_state(lib.state)
        op = build.Operation(lib.state.root, f"adoption of {p.setup.folder.name}", ops=library.OPS)
        try:
            for m in p.moves:
                if m.kind == "build":
                    lib.ensure(m.dest.parent)
                op.replace_folder(m.dest, m.src, keep=True)
            for r in p.rewrites:
                op.write_file(r.new, r.new_bytes, expect="missing")
            for r in p.rewrites:
                op.write_file(r.old, None, expect=_sha(r.old_bytes))
            op.note(
                kind=KIND,
                name=p.setup.folder.name,
                profile=str(p.rewrites[0].new),
                game=p.game,
                setup=str(p.setup.folder),
                moves=[{"src": str(m.src), "dest": str(m.dest), "kind": m.kind} for m in p.moves],
                profiles=[
                    {"old": str(r.old), "new": str(r.new), "old_sha": _sha(r.old_bytes), "new_sha": _sha(r.new_bytes)}
                    for r in p.rewrites
                ],
                state_done=False,
            )
        except BaseException:
            op.discard()
            raise
        op.commit()
        notes = finish_state(op)
    log(f"adopted {p.setup.folder.name}: {len(p.moves)} folder(s) and {len(p.rewrites)} profile(s) moved")
    return {
        "operation": str(op.dir),
        "profiles": [str(r.new) for r in p.rewrites],
        "moved": len(p.moves),
        "notes": notes,
    }


def finish_state(op: build.Operation) -> list[str]:
    """Re-key the launcher's own records for an adoption that is done (see the module notes), then say so in its
    journal. Safe to run again. Returns what could not be moved, in plain words."""
    lib = library.library_of(Path(op.info["profile"]))
    assert lib is not None
    with build.ops_lock(lib.state.root, ops=library.OPS):
        notes = _apply_state(op.info)
        op.note(state_done=True)
    return notes


def _apply_state(info: dict, *, back: bool = False) -> list[str]:
    from roundtable_souls.config.settings import change_settings, game_setting
    from roundtable_souls.mods.rebuild import _key

    pairs = [(Path(m["src"]), Path(m["dest"])) for m in info["moves"]]
    profs = [(Path(x["old"]), Path(x["new"])) for x in info["profiles"]]
    if back:
        pairs, profs = [(d, s) for s, d in pairs], [(n, o) for o, n in profs]
    notes: list[str] = []
    marks = {_key(o): _key(n) for o, n in profs}
    setups_ = {os.path.normcase(str(o)): str(n) for o, n in profs}
    game = info["game"]

    def change(cur):
        out: dict = {}
        ties = {_remap(k, pairs, True): [_remap(v, pairs) for v in vs] for k, vs in cur.native_configs.items()}
        if ties != cur.native_configs:
            out["native_configs"] = ties
        overlays = {marks.get(k, k): v for k, v in cur.parameter_overlays.items()}
        if overlays != cur.parameter_overlays:
            out["parameter_overlays"] = overlays
        now = game_setting(cur, game, "setup")
        if now and os.path.normcase(str(now)) in setups_:
            if game == "eldenring":
                out["setup"] = setups_[os.path.normcase(str(now))]
            else:
                out["games"] = {
                    **cur.games,
                    game: {**(cur.games.get(game) or {}), "setup": setups_[os.path.normcase(str(now))]},
                }
        return out

    try:
        change_settings(change)
    except OSError as e:
        notes.append(f"The launcher's settings could not be updated ({e})")
    for old, new in profs:
        try:
            if back:
                ps.clear(old)  # old here is the library profile
                (library.state_of(old).backups / (old.name + ".bak")).unlink(missing_ok=True)
                continue
            mine = ps.load(old)
            overlay = mine.get("overlay")
            if isinstance(overlay, dict):
                for k in ("package", "rebuild"):
                    if overlay.get(k):
                        moved = _remap(str(ps.from_stored(old, overlay[k])), pairs)
                        overlay = {**overlay, k: ps.to_stored(new, Path(moved))}
                mine["overlay"] = overlay
            if mine:
                ps.update(new, **mine)
            for bak in (library.state_of(old).backups / (old.name + ".bak"), old.with_name(old.name + ".bak")):
                if bak.is_file():
                    shutil.copy2(bak, library.profile_backup(new))
                    break
            seen = history.folder(old)
            if seen.is_dir():
                shutil.copytree(seen, history.folder(new), dirs_exist_ok=True)
        except (OSError, ps.Unreadable) as e:
            notes.append(f"The settings kept for {new.name if not back else old.name} could not be moved ({e})")
    return notes


# ----------------------------------------------------------------------------- taking it back
def undo_adopt(op_dir: Path, log=lambda s: None) -> str:
    """Put the setup back (see the module notes). Raises AdoptError, nothing changed, when an adopted profile changed
    since or the old places are taken again."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise AdoptError("This adoption can no longer be taken back.")
    lib = library.library_of(Path(info["profile"]))
    assert lib is not None
    profs, moves = info["profiles"], info["moves"]
    with operations.lock(Path(profs[0]["old"])), operations.lock(Path(profs[0]["new"])):
        for x in profs:
            new, old = Path(x["new"]), Path(x["old"])
            if not new.is_file():
                raise AdoptError(f"{new.name} is no longer in the library, so the adoption can't be taken back.")
            if _sha(new.read_bytes()) != x["new_sha"]:
                raise AdoptError(
                    f"{new.name} changed after it was adopted. Undoing would lose those changes, so everything is left "
                    "as it is."
                )
            if old.exists():
                raise AdoptError(f"{old.name} is back at its old place; undoing would overwrite it.")
        for m in moves:
            if not Path(m["dest"]).is_dir() or Path(m["src"]).exists():
                raise AdoptError(f"{Path(m['src']).name} is not where adopting left it, so it is left as it is.")
        back = build.Operation(lib.state.root, f"undo of the adoption of {info.get('name', '')}", ops=library.OPS)
        try:
            for m in moves:
                back.replace_folder(Path(m["src"]), Path(m["dest"]), keep=True)
            for x in profs:
                step = next(s for s in op.steps if s["type"] == "file" and s["live"] == x["old"])
                back.write_file(Path(x["new"]), None, expect=x["new_sha"])
                back.write_file(Path(x["old"]), (op.dir / step["before"]).read_bytes(), expect="missing")
        except BaseException:
            back.discard()
            raise
        back.commit()
        back.release()
        op.release()
    for n in _apply_state(info, back=True):
        log(f"undo: {n}")
    return f"took back the adoption of {info.get('name', 'the setup')}: its files are where they were"
