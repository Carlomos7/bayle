"""Giving every profile of a crowded folder (several .me3 in one folder of the launcher's profiles folder) a folder of its
own, as one journaled operation (merging.build.Operation, journal in the profiles folder) with Undo:

    <folder>/<a>.me3, <b>.me3   ->   <folder-or-new>/<a>/<a>.me3 and profiles/<b>/<b>.me3, each with its own mods
    a mod folder only one profile uses         moved to that profile's folder
    a mod folder several profiles use          copied to all but the last (checked file by file against the
                                               original before anything is committed); the last takes the original
    entry paths                                rewritten for the new place; builds and settings follow their profile

The profile whose name is the folder's name keeps the folder and is always the last user of a shared mod. Nothing is
deleted: what no profile uses stays in the old folder. Undo puts the originals back (the new folders go to the
Recycle Bin once their mods are back).
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
from roundtable_souls.mods import folder_check, library, migrate, operations
from roundtable_souls.mods import profile_settings as ps
from roundtable_souls.mods.folder_check import FolderError, _sha
from roundtable_souls.platform import files

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

KIND = "folder-split"
MODS = ("mod", "packages", "natives")  # folders whose children are one mod each


@dataclass
class SplitPlan:
    folder: Path
    items: list[migrate.Item] = field(default_factory=list)
    keeper: migrate.Item | None = None
    copies: int = 0
    moves: int = 0
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals and bool(self.items)

    @property
    def profiles(self) -> int:
        return len(self.items)


def preview(profile: Path, loc: Locations) -> SplitPlan:
    """What splitting the profile's folder does, with nothing written. Refusals say why it can't be done."""
    profile = Path(profile)
    got = folder_check.check(profile, loc)
    folder = profile.parent
    out = SplitPlan(folder)
    if got.kind != folder_check.CROWDED:
        out.refusals.append("This folder holds just one profile.")
        return out
    if loc.game_running():
        out.refusals.append(folder_check.GAME_OPEN)
    if (why := operations.problem(profile)) is not None:
        out.refusals.append(f"Another change to this profile is not finished: {why}")
    keeper_name = folder.name.lower()
    users: dict[str, migrate.Unit] = {}
    names = sorted(got.profiles, key=lambda p: (p.stem.lower() == keeper_name, p.name.lower()))  # keeper last
    taken = {p.name.lower() for p in folder.parent.iterdir()}
    for p in names:
        try:
            raw = p.read_bytes()
            text = raw.decode("utf-8")
            if me3_profile.is_array_form(text):
                text = me3_profile.to_blocks(text)
            rows = me3_profile.entries(text)
        except (OSError, ValueError) as e:
            out.refusals.append(f"{p.name} could not be read ({e}), so nothing was split.")
            return out
        is_keeper = p.stem.lower() == keeper_name
        if not is_keeper and p.stem.lower() in taken:
            out.refusals.append(f"A folder called {p.stem} is already there, so nothing was split.")
        item = migrate.Item(
            p, p.stem, folder if is_keeper else folder.parent / p.stem, library.state_of(p).root, old_bytes=raw
        )
        out.items.append(item)
        if is_keeper:
            out.keeper = item

        def unit(src: Path, rel: str, _item=item) -> None:
            if not src.is_dir():
                return
            u = users.setdefault(migrate._n(src), migrate.Unit(src, rel))
            if _item.old.stem not in u.users:
                u.users.append(_item.old.stem)
                _item.units.append(u)

        for e in rows:
            if not e.get("path"):
                continue
            parts = migrate._rel(Path(os.path.abspath(me3_profile.resolve(p, e["path"]))), folder)
            if not parts or parts[0] == library.STATE or parts[0].lower().endswith(".me3"):
                continue
            if parts[0] in MODS and len(parts) >= 2:
                unit(folder / parts[0] / parts[1], f"{parts[0]}/{parts[1]}")
            else:
                unit(folder / parts[0], parts[0])
        mine = library.ProfileFolder.of(p).root  # a loose profile's builds and the like, kept apart per profile
        for child in sorted(mine.iterdir()) if mine.is_dir() and mine != folder else []:
            unit(child, child.name)
    for item in out.items:
        item.new_bytes = migrate._rewrite(item)
        for u in item.units:
            last = u.users[-1] == item.old.stem
            where = item.folder / u.dest_rel
            if not last:
                out.copies += 1
            elif migrate._n(where) != migrate._n(u.src):
                out.moves += 1
                if where.exists():
                    out.refusals.append(f"{where.name} is already in {item.folder.name}, so nothing was split.")
    return out


def split(profile: Path, loc: Locations, log: Callable[[str], None] = lambda s: None) -> dict:
    """Split as previewed, one operation. Returns {operation, profile, profiles, copies, moves, notes}. Raises
    FolderError with nothing changed."""
    profile = Path(profile)
    first = preview(profile, loc)
    if not first.ok:
        raise FolderError(" ".join(first.refusals) or "Nothing to split.")
    operations.recover(profile)
    root = first.folder.parent
    with build.ops_lock(root):
        p = preview(profile, loc)
        if not p.ok:
            raise FolderError(" ".join(p.refusals))
        if [(i.old, i.old_bytes) for i in p.items] != [(i.old, i.old_bytes) for i in first.items]:
            raise FolderError("The profiles changed since the preview; try again.")
        op = build.Operation(root, f"split of the folder {p.folder.name} into {p.profiles} profile folders")
        stage = root / f".split-{op.id}"
        try:
            _prepare(p, op, stage, loc.game.key)
        except BaseException:
            op.discard()
            shutil.rmtree(stage, ignore_errors=True)
            raise
        try:
            op.commit(refuse=lambda: _refuse(p, loc))
        except build.BuildError as e:
            shutil.rmtree(stage, ignore_errors=True)
            raise FolderError(str(e)) from e
        try:
            stage.rmdir()
        except OSError:
            pass
        notes = folder_check.finish_state(op)
    log(f"split the folder {p.folder.name} into {p.profiles} profile folders")
    new = next((i.new for i in p.items if migrate._n(i.old) == migrate._n(profile)), profile)
    return {
        "operation": str(op.dir),
        "profile": str(new),
        "name": p.folder.name,
        "profiles": p.profiles,
        "copies": p.copies,
        "moves": p.moves,
        "notes": notes,
    }


def _refuse(p: SplitPlan, loc: Locations) -> str | None:
    if loc.game_running():
        return folder_check.GAME_OPEN
    if any(not i.old.is_file() or i.old.read_bytes() != i.old_bytes for i in p.items):
        return "A profile changed while the folder was being split."
    return None


def _prepare(p: SplitPlan, op: build.Operation, stage: Path, game: str) -> None:
    stage.mkdir(parents=True)
    state = p.folder / library.STATE
    settings = state / library.SETTINGS
    data = ps._read(settings) if settings.is_file() else {}
    moved: list[dict] = []
    for item in p.items:
        if item is p.keeper:
            continue
        sd = stage / item.name
        sd.mkdir()
        (sd / f"{item.name}.me3").write_bytes(item.new_bytes)
        offline = item.old.with_name(item.old.stem + migrate.OFFLINE)
        if offline.is_file():
            shutil.copy2(offline, sd / f"{item.name}.offline.me3")
        own_state = sd / library.STATE
        own_state.mkdir()
        files.hide(own_state)
        entry = (data.get("profiles") or {}).get(item.old.name)
        if isinstance(entry, dict):
            body = {"version": 1, "schema": 1, "profiles": {f"{item.name}.me3": migrate._restored(entry, item)}}
            (own_state / library.SETTINGS).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", "utf-8")
        bak = state / library.BACKUPS / (item.old.name + ".bak")
        if bak.is_file():
            (own_state / library.BACKUPS).mkdir()
            shutil.copy2(bak, own_state / library.BACKUPS / f"{item.name}.me3.bak")
        for u in item.units:
            if u.users[-1] != item.old.stem:  # all but the last user get a verified copy
                (sd / u.dest_rel).parent.mkdir(parents=True, exist_ok=True)
                migrate._copy_verified(u.src, sd / u.dest_rel)
        op.move_folder(sd, item.folder)
    for item in p.items:
        for u in item.units:
            where = item.folder / u.dest_rel
            if u.users[-1] == item.old.stem and migrate._n(where) != migrate._n(u.src):
                op.move_folder(u.src, where)
                moved.append({"src": str(u.src), "dest": str(where)})
    k = p.keeper
    if k is not None and k.new_bytes != k.old_bytes:
        op.write_file(k.old, k.new_bytes, expect=_sha(k.old_bytes))
    for item in p.items:
        if item is k:
            continue
        op.write_file(item.old, None, expect=_sha(item.old_bytes))
        offline = item.old.with_name(item.old.stem + migrate.OFFLINE)
        if offline.is_file():
            op.write_file(offline, None, expect=_sha(offline.read_bytes()))
    pairs = [(Path(m["src"]), Path(m["dest"])) for m in moved]
    for item in p.items:  # a path of a copied folder follows to the first profile that has it
        for u in item.units:
            if not any(migrate._n(s) == migrate._n(u.src) for s, _d in pairs) and item is not k:
                pairs.append((u.src, item.folder / u.dest_rel))
    others = [i for i in p.items if i is not k]
    op.note(
        kind=KIND,
        name=p.folder.name,
        game=game,
        profile=str((k or others[0]).new),
        home=str(p.folder.parent),
        moves=moved,
        pairs=[[str(s), str(d)] for s, d in pairs],
        profiles=[
            {
                "old": str(i.old),
                "new": str(i.new),
                "folder": str(i.folder),
                "old_sha": _sha(i.old_bytes),
                "new_sha": _sha(i.new_bytes),
            }
            for i in others
        ],
        keeper={"path": str(k.old), "new_sha": _sha(k.new_bytes)} if k is not None else None,
        state_done=False,
    )


def clean_stages(root: Path) -> None:
    """Remove the staging folders an interrupted split left in the profiles folder (copies only: the recovery has put
    every original back). Call it after the recovery, never during a split."""
    with build.ops_lock(Path(root)):  # a split in another window holds it while its stage is in use
        for stage in Path(root).glob(".split-*"):
            shutil.rmtree(stage, ignore_errors=True)


def undo_split(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Put the folder back as it was. Raises FolderError, nothing changed, when a split-off profile changed since or an
    old place is taken again. The new folders go to the Recycle Bin after their mods are back."""
    from roundtable_souls.platform import trash

    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") != KIND or op.state != build.ACTIVE:
        raise FolderError("This split can no longer be taken back.")
    if not trash.available():
        raise FolderError("There is no Recycle Bin to put the new folders in, so nothing was changed.")
    profs, moves, keeper = info["profiles"], info["moves"], info.get("keeper")
    with build.ops_lock(Path(info["home"])):
        for x in profs:
            new, old = Path(x["new"]), Path(x["old"])
            if not new.is_file():
                raise FolderError(f"{new.name} is no longer in its folder, so the split can't be taken back.")
            if _sha(new.read_bytes()) != x["new_sha"]:
                raise FolderError(
                    f"{new.name} changed after the split. Undoing would lose those changes, so everything is left "
                    "as it is."
                )
            if old.exists():
                raise FolderError(f"{old.name} is back at its old place; undoing would overwrite it.")
        for m in moves:
            if not Path(m["dest"]).is_dir() or Path(m["src"]).exists():
                raise FolderError(f"{Path(m['src']).name} is not where the split left it, so it is left as it is.")
        back = build.Operation(Path(info["home"]), f"undo of the split of {info.get('name', '')}")
        try:
            for m in reversed(moves):
                back.move_folder(Path(m["dest"]), Path(m["src"]))
            for step in op.steps:  # removed files come back with their earlier bytes; the keeper's text too
                live = Path(step["live"])
                if step["type"] != "file" or not step["before"]:
                    continue
                if not step["after"]:
                    back.write_file(live, (op.dir / step["before"]).read_bytes(), expect="missing")
                elif keeper and live.is_file() and _sha(live.read_bytes()) == keeper["new_sha"]:
                    back.write_file(live, (op.dir / step["before"]).read_bytes(), expect=keeper["new_sha"])
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
    for n in migrate._apply_state(info, back=True):
        log(f"undo: {n}")
    return f"took back the split of {info.get('name', 'the folder')}"
