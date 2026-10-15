"""Combine the parameter changes of several packs into one regulation.bin, against the game's own.

For every table, each pack is compared with the game's copy and only what it changed is applied, in load order:

- a changed row is applied field-agnostically, four bytes at a time: two packs that change different parts of the
  same row both apply; where they change the same bytes, the later pack wins (reported as a conflict)
- a row a pack adds is added (a later pack adding the same row wins, reported)
- a row a pack lacks is kept: packs made from older game data often lack newer rows, and dropping them would undo
  the game's own additions
- a table whose rows have another size than the game's is skipped for that pack (made for another game version)
- a table the game does not have is taken from the last pack that has it, and reported: the game matches tables by
  name and does not read one it doesn't know (the names known are the game's own regulation's)

Rows are matched by ID and, for the few tables that repeat an ID, by which occurrence it is.

What the game cannot take is refused (TableLimit): a table of more than 65,535 rows (its row count is 16 bits), and a
result missing a table the game's own regulation has (the game reads some tables without checking they exist). Rows
with negative IDs are reported: the game's lookup by ID never finds them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from roundtable_souls import formats

WORD = 4
MAX_ROWS = 0xFFFF  # the game's row count is 16 bits
NEGATIVE = 0x80000000  # IDs from here are negative as the game reads them (signed)
EXAMPLES = 3


class TableLimit(formats.FormatError):
    """A combined regulation the game could not read: refused, the previous result stays."""


@dataclass
class PackReport:
    name: str
    version: str
    tables: int = 0
    changed: int = 0
    added: int = 0
    skipped: list[str] = field(default_factory=list)  # "Table: why"
    warnings: list[str] = field(default_factory=list)  # what the game will make of this pack's changes


@dataclass
class Report:
    base_version: str
    packs: list[PackReport]
    conflicts: list[tuple[str, int, list[str]]] = field(default_factory=list)  # (table, row id, packs, in order)
    tables: int = 0

    def lines(self, limit: int = 12) -> list[str]:
        out = []
        for p in self.packs:
            what = f"{p.name}: {p.changed} changed and {p.added} new rows in {p.tables} tables"
            if p.version != self.base_version:
                what += f" (made for regulation {p.version}; the game has {self.base_version})"
            out.append(what)
            out += [f"  skipped {s}" for s in p.skipped]
            out += [f"  warning: {w}" for w in p.warnings]
        if self.conflicts:
            out.append(
                f"{len(self.conflicts)} rows changed by more than one pack; the later pack won where they overlap:"
            )
            out += [f"  {t} {rid}: {' then '.join(who)}" for t, rid, who in self.conflicts[:limit]]
            if len(self.conflicts) > limit:
                out.append(f"  and {len(self.conflicts) - limit} more")
        return out


def _short(name: str) -> str:
    return name.replace("\\", "/").rsplit("/", 1)[-1]


def _keyed(rows: list[formats.param.Row]) -> dict[tuple[int, int], formats.param.Row]:
    seen: dict[int, int] = {}
    out = {}
    for r in rows:
        k = seen.get(r.id, 0)
        seen[r.id] = k + 1
        out[(r.id, k)] = r
    return out


def _apply_words(result: bytearray, pack: bytes, base: bytes) -> bool:
    """Apply the bytes pack changed from base onto result. True when some of them had been changed differently by an
    earlier pack (the same field edited twice)."""
    clash = False
    for i in range(0, len(base), WORD):
        pw, bw = pack[i : i + WORD], base[i : i + WORD]
        if pw == bw:
            continue
        cur = result[i : i + WORD]
        if cur != bw and cur != pw:
            clash = True
        result[i : i + WORD] = pw
    return clash


def combine(base_raw: bytes, packs: list[tuple[str, bytes]], oodle=None) -> tuple[bytes, Report]:
    """(encrypted regulation.bin, report) combining packs (name, regulation bytes), in load order, onto base_raw (the
    game's own regulation.bin)."""
    base = formats.regulation.read_regulation(base_raw, oodle)
    regs = [(name, formats.regulation.read_regulation(raw, oodle)) for name, raw in packs]
    report = Report(base.version, [PackReport(name, r.version) for name, r in regs])
    names = [e.name or "" for e in base.bnd.entries]
    extra: dict[str, formats.bnd4.Entry] = {}
    for i, (_name, r) in enumerate(regs):
        for f in r.bnd.entries:
            short = _short(f.name or "")
            if base.bnd.get(short) is None:
                extra[short.lower()] = f  # a table the game does not have: the last pack's
                report.packs[i].warnings.append(
                    f"{report.packs[i].name} adds {short.rsplit('.', 1)[0]}, which the game does not read"
                )
    for full in names:
        short = _short(full)
        vfile = base.bnd.get(short)
        assert vfile is not None
        touched = [(i, r.bnd.get(short)) for i, (_n, r) in enumerate(regs)]
        touched = [(i, f) for i, f in touched if f is not None and f.data != vfile.data]
        if not touched:
            continue
        v = formats.param.read_param(vfile.data)
        vkeyed = _keyed(v.rows)
        out = {k: formats.param.Row(r.id, bytes(r.data), r.name) for k, r in vkeyed.items()}  # key -> row, in order
        ids = [r.id for r in v.rows]
        in_order = ids == sorted(ids)  # added rows go by ID if the game's are in order, else at the end
        changers: dict[tuple[int, int], list[str]] = {}
        clashed: set[tuple[int, int]] = set()
        table_changed = False
        for i, f in touched:
            pname = regs[i][0]
            rep = report.packs[i]
            try:
                p = formats.param.read_param(f.data)
            except formats.FormatError as e:
                rep.skipped.append(f"{short}: {e}")
                continue
            if p.stride != v.stride:
                rep.skipped.append(
                    f"{short}: rows are {p.stride} bytes, the game's are {v.stride} (another game version)"
                )
                continue
            did = False
            negative = [
                row.id
                for key, row in _keyed(p.rows).items()
                if row.id >= NEGATIVE and (key not in vkeyed or vkeyed[key].data != row.data)
            ]
            if negative:
                shown = ", ".join(str(n - (1 << 32)) for n in negative[:EXAMPLES]) + (
                    ", ..." if len(negative) > EXAMPLES else ""
                )
                rows = "row" if len(negative) == 1 else "rows"
                rep.warnings.append(
                    f"{pname} sets {len(negative)} {rows} of {short.rsplit('.', 1)[0]} with a negative ID ({shown}), "
                    "which the game's lookup never finds"
                )
            for key, row in _keyed(p.rows).items():
                if key in vkeyed:
                    vrow = vkeyed[key]
                    if row.data == vrow.data and (not row.name or row.name == out[key].name):
                        continue
                    cur = out[key]
                    data = bytearray(cur.data)
                    if row.data != vrow.data:
                        if _apply_words(data, row.data, vrow.data):
                            clashed.add(key)
                        rep.changed += 1
                        changers.setdefault(key, []).append(pname)
                    out[key] = formats.param.Row(cur.id, bytes(data), row.name or cur.name)
                    did = True
                elif key in out:  # added by an earlier pack too
                    clashed.add(key)
                    changers.setdefault(key, []).append(pname)
                    out[key] = formats.param.Row(row.id, bytes(row.data), row.name)
                    rep.added += 1
                    did = True
                else:
                    out[key] = formats.param.Row(row.id, bytes(row.data), row.name)
                    changers[key] = [pname]
                    rep.added += 1
                    did = True
            if did:
                rep.tables += 1
                table_changed = True
        for key in sorted(clashed):
            if len(changers.get(key, [])) > 1:
                report.conflicts.append((short.rsplit(".", 1)[0], key[0], changers[key]))
        if table_changed:
            out_rows = list(out.values())
            if in_order:  # stable: an added row goes after the rows with its ID already there, as inserted
                out_rows.sort(key=lambda r: r.id)
            if len(out_rows) > MAX_ROWS:
                raise TableLimit(
                    f"{short.rsplit('.', 1)[0]} would have {len(out_rows):,} rows; the game reads at most "
                    f"{MAX_ROWS:,} per table"
                )
            v.rows = out_rows
            vfile.data = formats.param.write_param(v)
            report.tables += 1
    for f in extra.values():
        new_id = max((x.id for x in base.bnd.entries), default=-1) + 1
        base.bnd.entries.append(formats.bnd4.Entry(f.name, new_id, f.data, f.flags))
        report.tables += 1
    lacking = missing_tables(names, base.bnd)
    if lacking:
        raise TableLimit(
            f"the result lacks {', '.join(lacking)}, which the game's own regulation has; the game would crash "
            "reading it"
        )
    return formats.regulation.write_regulation(base), report


def missing_tables(game_names: list[str], built: formats.bnd4.Bnd4) -> list[str]:
    """Tables (short names, no extension) the game's own regulation has (game_names: its entries' names) that the
    built regulation lacks."""
    have = {_short(e.name or "").lower() for e in built.entries}
    return [_short(n).rsplit(".", 1)[0] for n in game_names if _short(n).lower() not in have]
