"""Archives (BND4): changes inner file by inner file, matched the way the game finds them: by entry ID in archives whose
IDs are fixed role slots (part archives: 100 textures, 200 model...), by name (case and slashes aside) where the ID is
only a position, and by name where the two always agree (animation archives), which a mod's copy is then checked for.
The kind comes from the archive's file name and the game-model table (adapters.games.knowledge.binder_identity); a kind
not in the table is decided from the game's own copy (IDs 0..n-1, or a per-type base plus a position, mean name;
anything else means ID). A copy that repeats an ID cannot be matched by ID: names are used, and noted."""

from __future__ import annotations

from collections.abc import Callable

from bayle.adapters import formats
from bayle.adapters.games import knowledge
from bayle.adapters.merging.changes import REMOVED, Result

Nested = Callable[[bytes, list[tuple[str, bytes]], str], Result | None]
# inspect(path, mod, inner file as stored) -> what the game will make of that mod's inner file (game-level checks)
Inspect = Callable[[str, str, bytes], list[str]]
PAIRS_SHOWN = 3  # examples of a name/ID disagreement named in its warning


def merge(
    base: bytes,
    bodies: list[tuple[str, bytes]],
    where: str,
    nested: Nested,
    kind: str = "",
    inspect: Inspect | None = None,
) -> Result:
    """Inner file by inner file: what each mod changed, added or left out against the game's archive, applied in
    load order; an inner file several mods changed is merged inside when it is itself an archive or a text table.
    nested(base, bodies, where) is the merger's own dispatch for such an inner file (None: no rule for it). kind: the
    archive's kind ("partsbnd"; "" when not known). inspect: run on each mod's changed or added inner file.

    Inner files keep the game's order, added ones after them; but when the game's archive lists its inner files by
    ascending ID (as its effect and animation archives do) and the result's IDs are all different, the result is
    listed by ID too, so added files take their place among the game's (as the mods' own tools write them)."""
    van = formats.bnd4.read_bnd4(base)
    mods = [(label, formats.bnd4.read_bnd4(body)) for label, body in bodies]
    out = Result(b"")
    identity = knowledge.binder_identity(kind) if kind else None
    by_id = identity == "id" or identity is None and not _positional(van)
    if by_id:
        repeats = [whose for whose, b in [("the game's", van), *((f"{l}'s", b) for l, b in mods)] if _repeats_id(b)]
        if repeats:
            by_id = False
            out.notes.setdefault(where or "/", []).append(
                f"inner files matched by name: {repeats[0]} copy gives two inner files the same ID"
            )

    def key(e: formats.bnd4.Entry) -> str:
        return f"#{e.id}" if by_id else e.key

    _unique(van, "the game's", by_id)
    ascending = all(a.id < b.id for a, b in zip(van.entries, van.entries[1:], strict=False))
    vmap = {key(e): e for e in van.entries}
    shown = {k: e.key for k, e in vmap.items()}  # how a report names an inner file: the game's name for it
    order = [key(e) for e in van.entries]
    touched: dict[str, list[tuple[str, object]]] = {}
    for label, b in mods:
        _unique(b, f"{label}'s", by_id)
        lmap = {key(e): e for e in b.entries}
        for k, e in lmap.items():
            shown.setdefault(k, e.key)
            v = vmap.get(k)
            if v is None or v.data != e.data:
                touched.setdefault(k, []).append((label, e))
                if k not in vmap and k not in order:
                    order.append(k)
        lacks = [k for k in vmap if k not in lmap]
        for k in lacks:
            touched.setdefault(k, []).append((label, REMOVED))
        if lacks:
            out.omissions.setdefault(where, {})[label] = len(lacks)
        if identity == "both":
            _pairs(van, label, b, where, out)
    result = dict(vmap)
    for k, changes in touched.items():
        path = f"{where}/{shown[k]}" if where else shown[k]
        out.changed[path] = [label for label, _ in changes]
        kept = [(label, e) for label, e in changes if e is not REMOVED]
        if inspect is not None:
            for label, e in kept:
                assert isinstance(e, formats.bnd4.Entry)
                for said in inspect(path, label, e.data):
                    out.warnings.setdefault(path, []).append(said)
        distinct = {e.data if isinstance(e, formats.bnd4.Entry) else None for _, e in changes}
        if len(distinct) == 1 or len(changes) == 1:
            last = changes[-1][1]
        elif k in vmap and len(kept) == len(changes):  # all changed it: merge inside when it is a container
            inner_base, how = _inner(vmap[k].data)
            inner = [(label, _inner(e.data)[0]) for label, e in kept]  # type: ignore[union-attr]
            sub = nested(inner_base, inner, path)
            if sub is not None:
                out.take(sub)
                data = formats.dcx.pack(sub.data, how) if how is not None and sub.data != inner_base else sub.data
                if sub.data == inner_base:
                    data = vmap[k].data
                mine = kept[-1][1]
                assert isinstance(mine, formats.bnd4.Entry)
                last = formats.bnd4.Entry(mine.name, mine.id, data, mine.flags, len(sub.data))
            else:
                out.clashes[path] = [label for label, _ in changes]
                last = changes[-1][1]
        else:
            out.clashes[path] = [label for label, _ in changes]
            last = changes[-1][1]
        if last is REMOVED:
            result.pop(k, None)
            if k in vmap:
                out.removed[path] = [label for label, e in changes if e is REMOVED]
        else:
            assert isinstance(last, formats.bnd4.Entry)
            result[k] = last
    van.entries = [result[k] for k in order if k in result]
    if ascending and len({e.id for e in van.entries}) == len(van.entries):
        van.entries.sort(key=lambda e: e.id)
    out.data = formats.bnd4.write_bnd4(van)
    return out


def _positional(b: formats.bnd4.Bnd4) -> bool:
    """Whether the game's copy numbers its inner files by position: IDs 0..n-1 in order, or, per file type, a run
    of consecutive IDs from a base (some run longer than one), as effect archives do (fxr 0, 1... and tpf 100000...).
    Unique IDs that are neither are fixed slots. A copy that repeats an ID or has no inner files counts as
    positional (matched by name, as before)."""
    ids = [e.id for e in b.entries]
    if not ids or len(set(ids)) != len(ids) or ids == list(range(len(ids))):
        return True
    groups: dict[str, list[int]] = {}
    for e in b.entries:
        name = (e.name or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
        groups.setdefault(name.rsplit(".", 1)[-1] if "." in name else "", []).append(e.id)
    runs = [sorted(g) for g in groups.values()]
    consecutive = all(all(b - a == 1 for a, b in zip(r, r[1:], strict=False)) for r in runs)
    return consecutive and any(len(r) > 1 for r in runs)


def _repeats_id(b: formats.bnd4.Bnd4) -> bool:
    return len({e.id for e in b.entries}) != len(b.entries)


def _pairs(van: formats.bnd4.Bnd4, label: str, b: formats.bnd4.Bnd4, where: str, out: Result) -> None:
    """For archives whose names and IDs always agree in the game: the mod's inner files whose pairing differs from
    the game's (a known name with another ID, or a known ID under another name), as one warning."""
    names = {e.key: e for e in van.entries}
    ids = {e.id: e for e in van.entries}
    odd = []
    for e in b.entries:
        v = names.get(e.key)
        if v is not None and v.id != e.id:
            odd.append(f"{e.key} has ID {e.id}, the game's {v.id}")
        elif v is None and e.id in ids:
            odd.append(f"ID {e.id} is {e.key}, the game's {ids[e.id].key}")
    if odd:
        shown = "; ".join(odd[:PAIRS_SHOWN]) + ("; ..." if len(odd) > PAIRS_SHOWN else "")
        n = len(odd)
        out.warnings.setdefault(where or "/", []).append(
            f"{label}'s copy has {n} inner file{'s' if n != 1 else ''} whose name and ID don't match the game's "
            f"({shown}); the game may use another file than the mod meant"
        )


def _unique(b: formats.bnd4.Bnd4, whose: str, by_id: bool) -> None:
    """Inner files matched by name, case and slashes aside: two that differ only so cannot be told apart, and one
    would be lost. The game's own archives have none. (Matched by ID, repeats were ruled out before.)"""
    if by_id:
        return
    seen: dict[str, str] = {}
    for e in b.entries:
        other = seen.get(e.key)
        if other is not None:
            raise formats.FormatError(
                f"{whose} copy has two inner files that differ only in capital letters or slashes: {other} and {e.name}"
            )
        seen[e.key] = e.name or f"#{e.id}"


def _inner(data: bytes) -> tuple[bytes, formats.dcx.Dcx | None]:
    return formats.dcx.unpack(data) if data[:4] == b"DCX\0" and data[0x28:0x2C] != b"KRAK" else (data, None)
