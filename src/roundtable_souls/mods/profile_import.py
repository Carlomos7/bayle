"""Importing a me3 profile a download ships (a modpack's .me3 beside its mods): its entries go into the current
profile, or into a new profile beside it, with the mods they point at copied in; one undoable operation.

The bundled profile is read as configuration only: nothing in the download runs, and only the folders its entries
point at are copied (a me3.exe or an installer beside them is not). Each entry's path is read relative to the
.me3's place in the download and points at its installed copy afterwards; an entry pointing outside the download, or
at nothing, is left out and said. Each entry keeps its options (enabled, load_early, initializer, finalizer,
load_after, load_before). A package id the profile already has is renamed (-2, -3, ...) and every load_after /
load_before naming it is changed with it; a DLL is never renamed (me3 names DLLs by file name: two switched-on DLLs
with one name are refused by the profile writer, as is a required dependency that would be missing). A folder name
already taken where the mods go gets -2 the same way, unless the folder there is byte-identical to the one in the
download: then the profile points at the installed folder and nothing is copied (reused, and the space saved is said).
A folder whose name matches an installed one but whose files differ is a Clash: the player chooses per mod to use the
incoming copy (into the current profile it replaces the folder inside the same operation, the old copy kept for Undo;
a folder another profile also lists is never replaced: -2 for this profile only), to keep their own, or to keep both
(-2). Versions are shown as labels, never compared to decide.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import shutil
import tomllib
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.formats import me3_profile
from roundtable_souls.mods import extract, library, naming, operations
from roundtable_souls.mods import order as mod_order
from roundtable_souls.mods.profile_edit import ModError, roots
from roundtable_souls.mods.profile_writer import Plan as WriterPlan
from roundtable_souls.mods.profile_writer import ProfileWriter

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

JUNK = {"__MACOSX", "Thumbs.db", ".DS_Store"}
NEW_PROFILE = 'profileVersion = "v1"\n\n[[supports]]\ngame = "{game}"\n'
CHUNK = 4 * 1024 * 1024
SMALL = 8 * 1024 * 1024  # a settings file bigger than this is not read for the preview
HEADROOM = 64 * 1024**2  # free space kept beyond the bytes written (at least; a tenth of them when more)


def bundled(unpacked: Path) -> list[str]:
    """The .me3 profiles in an unpacked download, as paths from its top (what plan["profiles_inside"] lists)."""
    unpacked = Path(unpacked)
    return sorted((m.relative_to(unpacked).as_posix() for m in unpacked.rglob("*.me3")), key=str.lower)


class ZipSource:
    """A full-export zip read in place, so its mods are never unpacked twice. skeleton() makes the folder tree the
    preview walks under root: the real bytes of the few small files the preview reads, empty placeholders for
    everything else (never copied from: extract() writes the real bytes from the zip straight into the staging
    folder). Names and sizes come from the zip's own list; identity with an installed folder hashes members as they
    stream out of the zip."""

    def __init__(self, archive: Path, root: Path):
        self.archive, self.root = Path(archive), Path(root).resolve()
        self.members: dict[str, tuple[str, zipfile.ZipInfo]] = {}  # lower-case name -> (name, info), files only
        self.dirs: list[str] = []
        self._z: zipfile.ZipFile | None = None
        with zipfile.ZipFile(self.archive) as z:
            for info in z.infolist():
                extract.check_entry(info.filename)
                name = info.filename.replace("\\", "/")
                if JUNK.intersection(name.split("/")):
                    continue
                if info.is_dir():
                    self.dirs.append(name)
                else:
                    self.members[name.lower()] = (name, info)

    @contextlib.contextmanager
    def reading(self):
        with zipfile.ZipFile(self.archive) as z:
            self._z = z
            try:
                yield self
            finally:
                self._z = None

    def skeleton(self, wanted: Callable[[str], bool]) -> None:
        """Create the tree; wanted(name): this small file is extracted for real."""
        for d in self.dirs:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        with self.reading():
            assert self._z is not None
            for name, info in self.members.values():
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if not wanted(name):
                    path.touch()
                elif info.file_size <= SMALL:
                    path.write_bytes(self._z.read(info))

    def under(self, path: Path) -> dict[str, tuple[str, zipfile.ZipInfo]]:
        """The members of a folder of the skeleton (lower-case path inside it -> (name, info)), or {"": ...} for a file."""
        rel = Path(path).resolve().relative_to(self.root).as_posix().lower()
        if rel in self.members:
            return {"": self.members[rel]}
        pre = rel + "/"
        return {k[len(pre) :]: v for k, v in self.members.items() if k.startswith(pre)}

    def read(self, path: Path, rel: str, limit: int = SMALL) -> bytes:
        """The first limit bytes of one member (rel: its lower-case path inside the folder)."""
        assert self._z is not None
        with self._z.open(self.under(path)[rel][1]) as f:
            return f.read(limit)

    def size(self, path: Path) -> int:
        return sum(i.file_size for _n, i in self.under(path).values())

    def sha(self, path: Path, rel: str) -> str:
        """sha256 of one member (rel: its lower-case path inside the folder), streamed out of the zip."""
        assert self._z is not None
        h = hashlib.sha256()
        with self._z.open(self.under(path)[rel][1]) as f:
            while chunk := f.read(CHUNK):
                h.update(chunk)
        return h.hexdigest()

    def extract(self, path: Path, staged: Path, tick: Callable[[int], None] = lambda n: None) -> None:
        """The folder (or the lone file) at path in the skeleton, written into staged straight from the zip."""
        found = self.under(path)
        lone = "" in found
        staged.mkdir(parents=True, exist_ok=True)
        pre = Path(path).resolve().relative_to(self.root).as_posix()
        try:
            with self.reading():
                assert self._z is not None
                for name, info in found.values():
                    target = staged / (Path(name).name if lone else name[len(pre) + 1 :])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with self._z.open(info) as src, target.open("wb") as dst:
                        while chunk := src.read(CHUNK):
                            dst.write(chunk)
                            tick(len(chunk))
        except zipfile.BadZipFile as e:
            raise ModError(f"The zip is damaged ({e}); nothing was imported.") from e


CHOICES = ("incoming", "mine", "both")


@dataclass
class Clash:
    """A folder in the download with the name of an installed one but other files. changed / added / removed:
    (files, bytes) as the incoming copy has them (removed: the bytes of the installed files the incoming copy lacks).
    choice: what happens (None: the player has not picked and there is no default, so the import waits)."""

    key: str  # the folder's name in the download: what a choice is stored under
    incoming: Path
    mine: Path
    changed: tuple[int, int] = (0, 0)
    added: tuple[int, int] = (0, 0)
    removed: tuple[int, int] = (0, 0)
    label_in: str = ""  # a version hint, shown as a label only
    label_mine: str = ""
    installed: str = ""  # the installed folder's date (ISO)
    recorded: bool = False  # from the launcher's own record rather than the folder's modified time
    users: list[str] = field(default_factory=list)  # profiles listing the installed folder
    shared: bool = False  # another profile lists it, so it is never replaced from here
    default: str | None = None
    choice: str | None = None


@dataclass
class ImportPreview:
    """What importing does, worked out with nothing written."""

    profile: Path  # the profile written: the current one, or the new one
    new: bool
    writer: ProfileWriter
    change: WriterPlan | None
    copies: list[tuple[Path, Path]]  # (a folder or DLL in the download, the folder it becomes)
    renamed: dict[str, str]  # package id in the bundled profile -> the id it gets
    skipped: list[str]
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    reused: list[tuple[Path, Path]] = field(
        default_factory=list
    )  # (a folder in the download, the identical installed one)
    saved: int = 0  # bytes not copied because of reuse
    clashes: list[Clash] = field(default_factory=list)
    kept: list[tuple[Path, Path]] = field(default_factory=list)  # (a folder in the download, the installed one kept)
    source: ZipSource | None = None  # the zip the folders in copies are read from (None: they are real folders)

    @property
    def ok(self) -> bool:
        return not self.refusals

    @property
    def undecided(self) -> list[str]:
        """The mods the player still has to choose for."""
        return [c.key for c in self.clashes if c.choice is None]


def _inside(path: Path, top: Path) -> bool:
    try:
        path.relative_to(top)
    except ValueError:
        return False
    return True


def _files(folder: Path) -> dict[str, int]:
    """Relative path (lower case) -> size of every file in a folder, junk left out."""
    out: dict[str, int] = {}
    for root, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in JUNK]
        for n in names:
            if n not in JUNK:
                f = Path(root) / n
                out[f.relative_to(folder).as_posix().lower()] = f.stat().st_size
    return out


def _sha(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def identical(a: Path, b: Path, source: ZipSource | None = None) -> int | None:
    """The total size when two folders hold the same files byte for byte, else None. Names and sizes first; the
    hashes (stopping at the first difference) only when those match. source: a is a folder of that zip."""
    fa = {k: i.file_size for k, (_n, i) in source.under(a).items()} if source else _files(a)
    fb = _files(b)
    if fa != fb:
        return None
    for rel in fa:
        if (source.sha(a, rel) if source else _sha(a / rel)) != _sha(b / rel):
            return None
    return sum(fa.values())


def _installed_twin(item: Path, root: Path, source: ZipSource | None = None) -> tuple[Path, int] | None:
    """An installed folder in root (the same name, or that name with -2, -3...) identical to the folder item."""
    base = naming.mod_id(item.name)
    if not item.is_dir() or not root.is_dir():
        return None
    with source.reading() if source else contextlib.nullcontext():
        for p in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if p.is_dir() and re.fullmatch(re.escape(base) + r"(-\d+)?", p.name, re.IGNORECASE):
                size = identical(item, p, source)
                if size is not None:
                    return p, size
    return None


def _candidates(item: Path, root: Path) -> list[Path]:
    """Installed folders in root called like item (or with -2, -3...), the exact name first."""
    base = naming.mod_id(item.name)
    if not item.is_dir() or not root.is_dir():
        return []
    found = [
        p
        for p in sorted(root.iterdir(), key=lambda p: p.name.lower())
        if p.is_dir() and re.fullmatch(re.escape(base) + r"(-\d+)?", p.name, re.IGNORECASE)
    ]
    return sorted(found, key=lambda p: p.name.lower() != base)


def _version_in(text: str) -> str:
    m = re.search(r"(?im)^[\s#*>_-]*version\s*[:\-]?\s*v?(\d+(?:\.\d+)*[\w-]*)", text)
    return m.group(1) if m else ""


def _label(top: dict[str, int], read: Callable[[str], bytes]) -> str:
    """A version hint from the files at the top of a mod's folder (top: lower-case name -> size): a version file, a
    "version" key in a json / toml manifest, or a "Version x.y" line in a README. "" when there is none."""
    for name in sorted(top):
        if top[name] > 65536:
            continue
        try:
            if name == "version.txt" or name.endswith(".version"):
                line = next((x.strip() for x in read(name).decode("utf-8", "replace").splitlines() if x.strip()), "")
                if len(line) <= 32 and re.search(r"\d", line):
                    return line.removeprefix("v")
            elif name.endswith((".json", ".toml")):
                raw = read(name).decode("utf-8-sig", "replace")
                doc = json.loads(raw) if name.endswith(".json") else tomllib.loads(raw)
                v = doc.get("version") if isinstance(doc, dict) else None
                if isinstance(v, (str, int, float)) and not isinstance(v, bool) and re.search(r"\d", str(v)):
                    return str(v).strip().removeprefix("v")[:32]
        except OSError, ValueError, KeyError, zipfile.BadZipFile:
            continue
    for name in sorted(top):
        if name.startswith("readme") and top[name] <= 65536:
            try:
                got = _version_in(read(name).decode("utf-8", "replace"))
            except OSError, KeyError, zipfile.BadZipFile:
                continue
            if got:
                return got
    return ""


def _name_version(name: str) -> str:
    """A dotted version in a download's name (MapForGoblins-2.1.zip -> 2.1), or ""."""
    m = re.search(r"(?<![\w.])v?(\d+\.\d+(?:\.\d+)*)(?![\w])", Path(name).stem)
    return m.group(1) if m else ""


def _newer(a: str, b: str) -> bool:
    """a is a higher version than b (numbers only; either empty: no)."""
    ta, tb = ([int(x) for x in re.findall(r"\d+", v)] for v in (a, b))
    for t in (ta, tb):
        while t and t[-1] == 0:
            t.pop()
    return bool(ta and tb and ta > tb)


def _installed_on(folder: Path) -> tuple[str, bool]:
    """(date, from the launcher's record): when the launcher says it installed the folder, else its modified time."""
    try:
        when = json.loads((folder / "roundtable.json").read_text(encoding="utf-8")).get("installed")
        return datetime.datetime.fromisoformat(str(when).replace("Z", "+00:00")).date().isoformat(), True
    except OSError, ValueError, AttributeError:
        return datetime.date.fromtimestamp(folder.stat().st_mtime).isoformat(), False


def _clash(item: Path, mine: Path, source: ZipSource | None) -> Clash:
    """How the folder item differs from the installed folder mine: names and sizes first, hashes only of the files
    that kept their size. Call inside source.reading()."""
    fa = {k: i.file_size for k, (_n, i) in source.under(item).items()} if source else _files(item)
    fb = _files(mine)
    c = Clash(item.name, item, mine)
    for rel, size in fa.items():
        if rel not in fb:
            c.added = (c.added[0] + 1, c.added[1] + size)
        elif size != fb[rel] or (source.sha(item, rel) if source else _sha(item / rel)) != _sha(mine / rel):
            c.changed = (c.changed[0] + 1, c.changed[1] + size)
    for rel, size in fb.items():
        if rel not in fa:
            c.removed = (c.removed[0] + 1, c.removed[1] + size)
    tops = {k: s for k, s in fa.items() if "/" not in k}
    if source:
        c.label_in = _label(tops, lambda n: source.read(item, n, 65536))
    else:
        c.label_in = _label(tops, lambda n: (item / n).read_bytes()[:65536])
    c.label_mine = _label({k: s for k, s in fb.items() if "/" not in k}, lambda n: (mine / n).read_bytes()[:65536])
    c.installed, c.recorded = _installed_on(mine)
    return c


def _users(folder: Path, profile: Path) -> list[str]:
    """The profiles listing folder: those of the library, or the ones beside profile."""
    lib = library.library_of(profile)
    return library.users_of(lib.profiles if lib is not None else profile.parent, folder)


def preview_import(
    unpacked: Path,
    me3: str,
    current: Path,
    *,
    loc: Locations,
    new_name: str | None = None,
    tune: Callable[[ProfileWriter], None] | None = None,
    archive: ZipSource | None = None,
    choices: dict[str, str] | None = None,
    download: str = "",
) -> ImportPreview:
    """What importing the bundled profile me3 (its path in the unpacked download) would do: into current, or, with
    new_name, into a new profile of that name beside current. tune(writer): more edits for the same write (a shared
    profile's settings), made before it is planned. archive: unpacked is the skeleton of this zip (ZipSource.skeleton).
    choices: the player's pick per clashing mod (lower-case folder name -> one of CHOICES). download: the download's
    file name, a version hint when it holds one mod. Raises ModError when it can't be read."""
    unpacked, current = Path(unpacked).resolve(), Path(current)
    source = (unpacked / me3).resolve()
    if not _inside(source, unpacked) or not source.is_file():
        raise ModError(f"{me3} is not in the download.")
    try:
        found = me3_profile.entries(me3_profile.read_text(source))
    except ValueError as e:
        raise ModError(f"{Path(me3).name} could not be read: {e}") from e
    if new_name:
        target = current.parent / f"{naming.mod_id(new_name)}.me3"
        if target.exists():
            raise ModError(f"There is already a profile named {target.name}.")
        writer = ProfileWriter.create(target, NEW_PROFILE.format(game=loc.game.key), loc=loc)
    else:
        target = current
        writer = ProfileWriter(target, loc)
    pk_root, nt_root = roots(target, writer.text)
    taken_ids = {str(e.get("id") or "").lower() for e in writer.entries() if e["kind"] == "package"}
    taken_dirs = {p.name.lower() for root in (pk_root, nt_root) if root.is_dir() for p in root.iterdir()}
    out = ImportPreview(target, bool(new_name), writer, None, [], {}, [], source=archive)
    place: dict[Path, Path] = {}  # a folder (or lone DLL) in the download -> where it goes
    found_rows: list[tuple[dict, Path, Path]] = []  # (the entry, its item in the download, its path there)
    pending: dict[Path, tuple[Clash, Path]] = {}  # an item that clashes with an installed folder -> (clash, root)
    for e in found:
        path = (source.parent / e["path"]).resolve() if e["path"] else None
        if path is None or not _inside(path, unpacked) or not path.exists():
            out.skipped.append(f"{e['name']}: {e['path'] or 'no path'} is not in the download, so it is left out")
            continue
        if e["kind"] == "package":
            item = path
        else:  # a DLL brings its folder, unless it sits loose beside the profile or at the download's top
            item = path if path.parent in (source.parent, unpacked) else path.parent
        if item not in place:
            root = pk_root if e["kind"] == "package" else nt_root
            twin = _installed_twin(item, root, archive)
            if twin is not None:  # already installed, byte for byte: the profile points at it
                place[item] = twin[0]
                out.reused.append((item, twin[0]))
                out.saved += twin[1]
            elif cands := _candidates(item, root):
                with archive.reading() if archive else contextlib.nullcontext():
                    pending[item] = (_clash(item, cands[0], archive), root)
                place[item] = cands[0]  # until the choice is applied below
            else:
                name = naming.unique(naming.mod_id(item.stem if item.is_file() else item.name), taken_dirs)
                taken_dirs.add(name)
                place[item] = root / name
                out.copies.append((item, root / name))
        found_rows.append((e, item, path))
        ident = str(e["id"] or "") if e["kind"] == "package" else ""
        if ident and ident.lower() in taken_ids:
            out.renamed[ident] = naming.unique(ident, taken_ids)
        if ident:
            taken_ids.add(out.renamed.get(ident, ident).lower())
    claimed: set[Path] = set()
    for item, (c, root) in pending.items():
        c.users = _users(c.mine, target)
        c.shared = bool(c.users) and not out.new and any(u.lower() != target.stem.lower() for u in c.users)
        if len(place) == 1 and not c.label_in:
            c.label_in = _name_version(download)
        c.default = "incoming" if _newer(c.label_in, c.label_mine) else None
        pick = (choices or {}).get(c.key.lower())
        # a new profile risks nothing of the player's: with no pick it gets the incoming copy as name-2, as before
        c.choice = pick if pick in CHOICES else c.default or ("incoming" if out.new else None)
        out.clashes.append(c)
        if c.choice == "mine":
            out.kept.append((item, c.mine))
        elif c.choice == "incoming" and not out.new and not c.shared and c.mine not in claimed:
            claimed.add(c.mine)
            out.copies.append((item, c.mine))  # replaces the folder; the journal keeps the old one for Undo
        else:  # keep both (and, until the player picks, the same plan)
            name = naming.unique(naming.mod_id(item.name), taken_dirs)
            taken_dirs.add(name)
            place[item] = root / name
            out.copies.append((item, root / name))
    rows: list[tuple[dict, Path]] = []
    for e, item, path in found_rows:
        dest = place[item]
        rows.append(
            (e, dest if e["kind"] == "package" else dest / (path.name if item.is_file() else path.relative_to(item)))
        )
    for e, live in rows:
        row = {
            k: e[k] for k in ("enabled", "optional", "load_early", "initializer", "finalizer") if e.get(k) is not None
        }
        row["load_after"] = mod_order.rename_refs(e["load_after"], out.renamed)
        row["load_before"] = mod_order.rename_refs(e["load_before"], out.renamed)
        if e["kind"] == "package":
            row["id"] = out.renamed.get(e["id"], e["id"]) if e["id"] else None
        row["path"] = live
        writer.add_entry(e["kind"], row, deepest=_deepest(live))
    if not rows:
        out.refusals.append(f"None of {Path(me3).name}'s entries point at mods in the download.")
        return out
    if tune is not None:
        tune(writer)
    out.change = writer.plan(f"before importing {Path(me3).name}")
    # the imported folders are copied in only when the operation commits: "whose folder is missing" about one of
    # them is not a problem (shortcut: matched on the writer's wording, which test_mod_operations pins)
    coming = {f"'{out.renamed.get(e['id'], e['id'])}'" for e, _ in rows if e["kind"] == "package" and e["id"]}
    coming |= {f"'{live.name}'" for e, live in rows if e["kind"] == "native"}
    out.change.refusals = [
        r
        for r in out.change.refusals
        if not ("whose folder is missing" in r.message and any(c in r.message for c in coming))
    ]
    out.refusals += [r.message for r in out.change.refusals]
    out.lines = [
        (f"A new profile {target.name} is made beside {current.name}" if new_name else f"{target.name} gets")
        + f" {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} from {Path(me3).name}, with their options",
        *(f"{src.name} is copied into {dest}" for src, dest in out.copies),
        *(
            f"{src.name} is already installed ({dest}, identical), so it is reused and not copied"
            for src, dest in out.reused
        ),
        *([f"Reusing installed mods saves {_size(out.saved)} of copying"] if out.reused else []),
        *(
            f"{src.name} differs from your installed {dest.name}: your copy is kept, nothing is copied"
            for src, dest in out.kept
        ),
        *(
            f"{src.name} replaces your installed {dest.name}; the old copy is kept so Undo import brings it back"
            for src, dest in out.copies
            if any(c.incoming == src and c.mine == dest for c in out.clashes)
        ),
        *(
            f"{c.key} is also used by {', '.join(c.users)}, so it is not replaced: this profile gets its own copy"
            for c in out.clashes
            if c.shared and c.choice == "incoming"
        ),
        *(f"{old} is called {new}: {target.name} already has a mod with that id" for old, new in out.renamed.items()),
        *out.skipped,
        "Nothing in the download runs; your other mods are not touched",
    ]
    return out


def _size(n: int) -> str:
    return f"{n / 1024**3:.1f} GB" if n >= 1024**3 else f"{n / 1024**2:.1f} MB"


def _deepest(path: Path) -> int:
    return (
        max((len(p.relative_to(path).as_posix()) for p in path.rglob("*") if p.is_file()), default=0)
        if path.is_dir()
        else 0
    )


def _need_space(copies: list[tuple[Path, Path]], source: ZipSource) -> None:
    """Refuse, before anything is written, when a drive can't hold the folders about to be unpacked onto it."""
    per: dict[int, list] = {}
    for src, dest in copies:
        where = dest.parent
        while not where.exists() and where != where.parent:
            where = where.parent
        row = per.setdefault(where.stat().st_dev, [where, 0])
        row[1] += source.size(src)
    for where, need in per.values():
        want = need + max(HEADROOM, need // 10)
        free = shutil.disk_usage(where).free
        if free < want:
            raise ModError(
                f"There is not enough free space on {where.anchor or where}: the import needs about {_size(want)} "
                f"and {_size(free)} is free. Nothing was imported."
            )


def apply_import(
    preview: ImportPreview,
    *,
    log=lambda s: None,
    after_copy: Callable[[Path, Path], None] | None = None,
    progress: Callable[[int, int], None] = lambda done, total: None,
) -> dict:
    """Import as previewed, as one operation. after_copy(dest, staged): called for each folder copied, before it
    goes live (a shared profile's settings files are written into the copy). progress(done, total): bytes unpacked
    from a zip. Returns {operation, profile, new}. A mod still undecided (ImportPreview.undecided; the page waits for
    the player's pick) is imported as name-2, which changes nothing of theirs."""
    p = preview
    if not p.ok or p.change is None:
        raise ModError("; ".join(p.refusals) or "Nothing to import.")
    total, done = 1, 0
    if p.source is not None:
        _need_space(p.copies, p.source)
        total = sum(p.source.size(src) for src, _ in p.copies) or 1

    def tick(n: int) -> None:
        nonlocal done
        done += n
        progress(done, total)

    with operations.lock(p.profile):
        operations.recover(p.profile)
        op = operations.start(p.profile, f"import into {p.profile.name}")
        made = {}
        try:
            for src, dest in p.copies:
                staged = dest.with_name(f".{dest.name}.staging-{op.id}")
                try:  # not yet a step of the operation, so discard() would not remove it
                    if p.source is not None:
                        p.source.extract(src, staged, tick)
                    elif src.is_file():
                        staged.mkdir(parents=True)
                        shutil.copy2(src, staged / src.name)
                    else:
                        shutil.copytree(src, staged, ignore=shutil.ignore_patterns(*JUNK))
                    if after_copy is not None:
                        after_copy(dest, staged)
                except BaseException:
                    shutil.rmtree(staged, ignore_errors=True)
                    raise
                made[str(dest)] = operations.manifest(staged)
                op.replace_folder(dest, staged)
            p.writer.commit(p.change, operation=op)
            op.note(
                kind="profile-import",
                name=p.profile.name,
                new_profile=p.new,
                made=made,
                entries=[c.path for c in p.change.changes if c.action == "add" and c.path],
            )
        except BaseException:
            op.discard()
            raise
        operations.commit(op)
    log(f"imported {len(p.copies)} mod folder(s) into {p.profile.name}")
    return {"operation": str(op.dir), "profile": str(p.profile), "new": p.new}


def undo_import(op_dir: Path, log=lambda s: None) -> str:
    """Take an import back (operations.take_back); a profile it made goes too."""
    from roundtable_souls.merging import build

    op = build.Operation.load(Path(op_dir))
    profile = Path(op.info["profile"])
    said = operations.take_back(Path(op_dir), log)
    if op.info.get("new_profile") and profile.is_file() and not profile.read_bytes():
        profile.unlink()  # take_back gives a file it made its earlier bytes: none
    return said
