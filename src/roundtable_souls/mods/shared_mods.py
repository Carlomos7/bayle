"""The Library: game-file mods (packages) that several profiles use from one copy. Opt-in: a profile keeps its own
copy (Separate) until the player shares it.

    <game folder>/.shared/<mod-id>/mod.json            display name, source, versions: [{id, installed, label, size}]
    <game folder>/.shared/<mod-id>/<version id>/       the files; the id is the first 16 hex of a sha256 over the sorted
                                                       (path, size, file hash) of the tree, so equal files are one version
    <profile>.me3:  path = '../.shared/<mod-id>/<version id>'   (relative: a renamed or copied profile still works)

A version never changes: its files are read-only once the verified copy is made. Who uses what is never stored; usage()
reads every profile's entries. Only packages in a profile's own folder under the game root can be shared (a DLL mod's
.ini sits beside it, so sharing it would share its settings).

Each action is one merging.build.Operation, journaled in <game folder>/.roundtable-ops (so
operations.recover finds it), taken under the profiles' locks and then the root lock:

    share        a Separate package becomes a version (an identical one is reused) and the entry links to it; the old
                 folder goes aside, then to the Recycle Bin
    use_in       other profiles link to a version; a Separate copy of the same mod in them is replaced only when asked
    separate     the version is copied back into packages/ and the entry points at the copy
    add_version  a new archive over a Shared mod: a version is added; this profile, or every profile using the mod, links
                 to it
    remove_unused  versions no profile uses go (Recycle Bin when there is one)

undo() reverses an operation from its journal: moves go back, files get their earlier bytes, only while nothing it
touched has changed since. Same drive only (everything is renamed, never copied across drives).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.formats import me3_profile
from roundtable_souls.merging import build
from roundtable_souls.mods import library, migrate, operations
from roundtable_souls.mods.profile_edit import ModError
from roundtable_souls.mods.profile_writer import ProfileWriter

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

LIBRARY = "library"
RECORD = "mod.json"
KEPT = ".previous"  # in the library: what an operation replaced, until it is let go of
ID_LENGTH = 16
GAME_OPEN = "Close the game first: it has these files open."
KINDS = {
    "library-share": "Undo share",
    "library-use": "Undo",
    "library-separate": "Undo",
    "library-update": "Undo update",
    "library-clean": "Undo",
}


class LibraryError(ModError):
    pass


# ----------------------------------------------------------------------------- hashing and copying
def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _files(folder: Path) -> list[tuple[str, Path]]:
    out = []
    for dirpath, _dirs, names in os.walk(folder):
        for n in names:
            p = Path(dirpath) / n
            out.append((p.relative_to(folder).as_posix(), p))
    return sorted(out)


def tree_hash(folder: Path) -> tuple[str, int]:
    """(version id, size in bytes) of a folder's files: the same files give the same id wherever they are."""
    h, total = hashlib.sha256(), 0
    for rel, p in _files(folder):
        size = p.stat().st_size
        total += size
        h.update(f"{rel}\0{size}\0{_digest(p)}\n".encode())
    return h.hexdigest()[:ID_LENGTH], total


def _manifest(folder: Path) -> list[tuple[str, int, int]]:
    return [(rel, (st := p.stat()).st_size, st.st_mtime_ns) for rel, p in _files(folder)]


def _chmod(folder: Path, *, write: bool) -> None:
    for _rel, p in _files(folder):
        try:
            mode = p.stat().st_mode
            p.chmod(
                mode | stat.S_IWRITE
                if write
                else (mode | stat.S_IREAD) & ~(stat.S_IWRITE | stat.S_IWGRP | stat.S_IWOTH)
            )
        except OSError:
            pass


def _delete(folder: Path) -> None:
    """A folder gone, read-only files included."""
    if folder.exists():
        _chmod(folder, write=True)
        shutil.rmtree(folder, ignore_errors=True)


def _copy_verified(src: Path, dst: Path, digest: str) -> None:
    """src copied to dst and read back: the copy must hash to `digest`, else nothing is kept."""
    try:
        shutil.copytree(src, dst)
        if tree_hash(dst)[0] != digest:
            raise LibraryError(f"The copy of {src.name} does not match the original, so nothing was changed.")
    except BaseException:
        _delete(dst)
        raise


def _canon(p: Path | str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _today() -> str:
    return time.strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------- the store
def root_of(loc: Locations) -> Path:
    home = loc.me3_profiles_dir()
    if home is None:
        raise LibraryError("me3's profiles folder was not found.")
    return library.library_root(home, loc.game.key)


@dataclass
class Version:
    id: str
    installed: str = ""
    label: str = ""
    size: int = 0

    def row(self) -> dict:
        return {"id": self.id, "installed": self.installed, "label": self.label, "size": self.size}


@dataclass
class SharedMod:
    id: str
    name: str = ""
    source: str = ""
    versions: list[Version] = field(default_factory=list)

    def version(self, ident: str) -> Version | None:
        return next((v for v in self.versions if v.id == ident), None)

    def dump(self) -> bytes:
        body = {
            "schema": 1,
            "id": self.id,
            "name": self.name or self.id,
            "source": self.source,
            "versions": [v.row() for v in self.versions],
        }
        return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode()


def read_mod(root: Path, mod_id: str) -> SharedMod | None:
    """The record of one mod, or None when it has none (or it is unreadable)."""
    try:
        data = json.loads((Path(root) / mod_id / RECORD).read_text(encoding="utf-8"))
        versions = [
            Version(str(v["id"]), str(v.get("installed") or ""), str(v.get("label") or ""), int(v.get("size") or 0))
            for v in data.get("versions") or []
            if isinstance(v, dict) and v.get("id")
        ]
        return SharedMod(mod_id, str(data.get("name") or mod_id), str(data.get("source") or ""), versions)
    except OSError, ValueError, TypeError, AttributeError:
        return None


def mods(root: Path) -> list[SharedMod]:
    try:
        names = sorted(d.name for d in Path(root).iterdir() if d.is_dir() and not d.name.startswith("."))
    except OSError:
        return []
    return [m for n in names if (m := read_mod(root, n)) is not None]


def version_path(root: Path, mod_id: str, version: str) -> Path:
    return Path(root) / mod_id / version


# ----------------------------------------------------------------------------- who uses what
@dataclass(frozen=True)
class Use:
    profile: Path
    index: int
    enabled: bool
    mod: str
    version: str


@dataclass
class Usage:
    uses: list[Use] = field(default_factory=list)
    unreadable: list[Path] = field(
        default_factory=list
    )  # profiles that could not be read: nobody can say they don't use it
    texts: str = ""  # every profile's text, slashes forward and lower case, to catch a use the parser missed

    def of(self, mod: str, version: str | None = None) -> list[Use]:
        return [u for u in self.uses if u.mod == mod and (version is None or u.version == version)]

    def mentions(self, mod: str, version: str) -> bool:
        return f"{library.layout().shared}/{mod}/{version}".lower() in self.texts


def profiles_in(profiles_root: Path) -> list[Path]:
    """Every profile of the launcher's folder for a game: <name>/<name>.me3."""
    out: list[Path] = []
    try:
        for d in sorted(Path(profiles_root).iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                out += migrate.own_profiles(d)
    except OSError:
        pass
    return out


def link_target(profile: Path, root: Path, path: str) -> tuple[str, str] | None:
    """(mod id, version id) when an entry's path points into the library, else None."""
    resolved, top = Path(os.path.abspath(me3_profile.resolve(profile, path))), Path(os.path.abspath(root))
    if not _canon(resolved).startswith(_canon(top) + os.sep):
        return None
    parts = resolved.parts[len(top.parts) :]
    return (parts[0].lower(), parts[1]) if len(parts) >= 2 else None


def usage(profiles_root: Path, root: Path) -> Usage:
    out = Usage()
    texts = []
    for profile in profiles_in(profiles_root):
        try:
            raw = profile.read_bytes().decode("utf-8")
            found = me3_profile.entries(raw)
        except OSError, ValueError:
            out.unreadable.append(profile)
            continue
        texts.append(raw.replace("\\", "/").lower())
        for e in found:
            if e["kind"] == "package" and e["path"] and (hit := link_target(profile, root, e["path"])) is not None:
                out.uses.append(Use(profile, e["index"], e["enabled"], *hit))
    out.texts = "\n".join(texts)
    return out


# ----------------------------------------------------------------------------- a job: one operation on the library
class _Job:
    """The pieces of one operation: locks, the journal, one writer per profile, the places things go aside."""

    def __init__(self, loc: Locations, profiles: Iterable[Path], kind: str, what: str, *, strict: bool = True):
        home = loc.me3_profiles_dir()
        if home is None:
            raise LibraryError("me3's profiles folder was not found.")
        self.loc, self.kind, self.what, self.strict, self.home = loc, kind, what, strict, home
        self.root = library.library_root(home, loc.game.key)
        self.profiles_root = library.profiles_root(home, loc.game.key)
        self.profiles = sorted({Path(p) for p in profiles}, key=_canon)
        self.stack = ExitStack()
        self.op: build.Operation | None = None
        self.writers: dict[str, ProfileWriter] = {}
        self.records: dict[str, SharedMod | None] = {}
        self.created: list[dict] = []  # versions (or copies) this operation adds: {mod, version, path, stage}
        self.asides: list[dict] = []  # folders it takes out of their place: {src, dst, mod, version}
        self.sources: list[tuple[Path, list]] = []  # folders it reads, and what they held: checked again at commit

    def __enter__(self) -> _Job:
        for p in self.profiles:
            if not p.is_file():
                raise LibraryError(f"{p.name} is not there any more.")
            if self.strict and not (library.in_game_root(p, self.home, self.loc.game.key) and library.own_folder(p)):
                raise LibraryError(f"{p.stem} keeps its mods outside Roundtable's folder, so it can't share them.")
        for p in self.profiles:
            self.stack.enter_context(operations.lock(p))
        self.profiles_root.mkdir(parents=True, exist_ok=True)
        self.stack.enter_context(build.ops_lock(self.profiles_root))
        try:
            for p in self.profiles:
                operations.recover(p)
                if (why := operations.problem(p)) is not None:
                    raise LibraryError(f"Another change to {p.stem} is not finished: {why}")
            clean_stages(self.root)  # what an interrupted run staged: gone, as the lock is ours
            if self.loc.game_running():
                raise LibraryError(GAME_OPEN)
            self.op = build.Operation(self.profiles_root, self.what)
        except BaseException:
            self.stack.close()
            raise
        return self

    def __exit__(self, *exc) -> None:
        op = self.op
        try:
            if op is not None and op.state == build.PREPARED and op.dir.exists():  # given up before the commit
                op.discard()
                for c in self.created:
                    _delete(Path(c["stage"]))
                prune(self.root)
        finally:
            self.stack.close()

    # -------------------------------------------------------------- reading
    def writer(self, profile: Path) -> ProfileWriter:
        key = _canon(profile)
        if key not in self.writers:
            self.writers[key] = ProfileWriter(profile, self.loc)
        return self.writers[key]

    def record(self, mod_id: str) -> SharedMod | None:
        if mod_id not in self.records:
            rec = read_mod(self.root, mod_id)
            if rec is None and (self.root / mod_id / RECORD).exists():
                raise LibraryError(f"The record of the shared mod {mod_id} can't be read, so nothing was changed.")
            self.records[mod_id] = rec
        return self.records[mod_id]

    def own_package(self, profile: Path, index: int) -> tuple[dict, Path]:
        """(the entry's options, its folder) for a package in the profile's own packages/ folder."""
        o = self.writer(profile).options(index)
        if o["kind"] != "package" or not o["path"]:
            raise LibraryError("Only game-file mods can be shared.")
        folder = me3_profile.resolve(profile, o["path"])
        if _canon(folder.parent) != _canon(library.ProfileFolder.of(profile).packages) or not folder.is_dir():
            raise LibraryError(f"{o['id'] or folder.name} is not a Separate copy in {profile.stem}'s own folder.")
        return o, folder

    def shared_package(self, profile: Path, index: int) -> tuple[dict, str, str]:
        o = self.writer(profile).options(index)
        hit = link_target(profile, self.root, o["path"]) if o["kind"] == "package" and o["path"] else None
        if hit is None:
            raise LibraryError(f"{o['id'] or Path(o['path']).name} is not Shared.")
        return o, *hit

    def verified(self, mod_id: str, version: str) -> SharedMod:
        rec = self.record(mod_id)
        folder = version_path(self.root, mod_id, version)
        if rec is None or rec.version(version) is None or not folder.is_dir():
            raise LibraryError(f"{mod_id} is not in Shared mods.")
        if tree_hash(folder)[0] != version:
            raise LibraryError(f"The shared copy of {rec.name} does not match its record. Nothing was changed.")
        return rec

    # -------------------------------------------------------------- steps
    def read_source(self, folder: Path) -> tuple[str, int]:
        """The version id and size of a folder, which must still hold the same files when the operation commits."""
        self.sources.append((folder, _manifest(folder)))
        return tree_hash(folder)

    def add_version(self, mod_id: str, name: str, source: Path, note: str, label: str = "") -> tuple[str, bool]:
        """The files of `source` as a version of the mod (an identical one is reused). Returns (id, reused)."""
        op = self.op
        assert op is not None
        digest, size = self.read_source(source)
        rec = self.record(mod_id) or SharedMod(mod_id, name, note)
        live = version_path(self.root, mod_id, digest)
        if rec.version(digest) is not None:
            self.verified(mod_id, digest)
            return digest, True
        if live.exists():
            raise LibraryError(f"Shared mods has a folder for this version of {name} that it has no record of.")
        stage = self.root / mod_id / f".stage-{op.id}-{digest}"
        stage.parent.mkdir(parents=True, exist_ok=True)
        _copy_verified(source, stage, digest)
        _chmod(stage, write=False)
        op.replace_folder(live, stage)
        self.created.append({"mod": mod_id, "version": digest, "path": str(live), "stage": str(stage)})
        record = self.root / mod_id / RECORD
        old = record.read_bytes() if record.is_file() else None
        rec.versions.append(Version(digest, _today(), label, size))
        self.records[mod_id] = rec
        op.write_file(record, rec.dump(), expect=_sha(old) if old is not None else "missing")
        return digest, False

    def link(self, profile: Path, index: int, mod_id: str, version: str) -> None:
        self.writer(profile).set_path(index, self.relative(profile, version_path(self.root, mod_id, version)))

    @staticmethod
    def relative(profile: Path, target: Path) -> str:
        return os.path.relpath(target, Path(profile).parent).replace("\\", "/")

    def put_aside(self, folder: Path, mod_id: str, version: str) -> None:
        """A folder leaves its profile: kept in the library's .previous until the operation is let go of. `version`:
        the library version that holds exactly these files, or "" when none does."""
        assert self.op is not None
        dst = self.root / KEPT / self.op.id / f"{len(self.asides)}-{folder.name}"
        self.op.move_folder(folder, dst)
        self.asides.append({"src": str(folder), "dst": str(dst), "mod": mod_id, "version": version})

    def changed(self) -> str | None:
        if self.loc.game_running():
            return GAME_OPEN
        for folder, seen in self.sources:
            if not folder.is_dir() or _manifest(folder) != seen:
                return f"{folder.name} changed while it was being shared. Try again."
        return None

    def finish(self, extra: dict, *, bin_required: bool = False, delete_without_bin: bool = False) -> dict:
        """Write every profile touched, record the operation and commit it. What was put aside goes to the Recycle Bin
        as one item when the commit is done."""
        op = self.op
        assert op is not None
        container = self.root / KEPT / op.id
        try:
            for w in self.writers.values():
                if w.changes:
                    w.commit(w.plan(f"before {self.what}"), operation=op)
            op.note(
                kind=self.kind,
                root=str(self.profiles_root),
                library=str(self.root),
                profiles=[str(p) for p in self.profiles],
                created=self.created,
                asides=self.asides,
                container=str(container) if self.asides else "",
                trash=None,
                **extra,
            )
        except BaseException:
            op.discard()
            for c in self.created:
                _delete(Path(c["stage"]))
            prune(self.root)
            raise
        try:
            op.commit(refuse=self.changed, then=self._to_bin(container, bin_required, delete_without_bin))
        except build.BuildError as e:
            for c in self.created:
                _delete(Path(c["stage"]))
            prune(self.root)
            raise LibraryError(str(e)) from e
        prune(self.root)  # the .previous folder when its content went to the bin
        return {"operation": str(op.dir), "profile": str(self.profiles[0]) if self.profiles else ""}

    def _to_bin(self, container: Path, required: bool, delete_without_bin: bool) -> Callable[[], None]:
        from roundtable_souls.platform import trash

        op = self.op
        assert op is not None

        def run() -> None:
            if not self.asides:
                return
            _chmod(container, write=True)
            if trash.available():
                op.gone_when(container)
                try:
                    op.note(trash=trash.send(container))
                    return
                except OSError as e:
                    op.info.pop("gone_when", None)
                    if required:
                        raise LibraryError("The Recycle Bin did not take them, so nothing was changed.") from e
            elif delete_without_bin:
                op.gone_when(container)
                _delete(container)

        return run


def clean_stages(root: Path) -> None:
    """What an interrupted operation staged in the library (copies only, never a version). Only under the lock."""
    if Path(root).is_dir():
        for stage in Path(root).glob("*/.stage-*"):
            _delete(stage)
        prune(root)


def prune(root: Path) -> None:
    """Empty folders of the library go (a mod with no versions left, finished .previous folders, the library itself)."""
    root = Path(root)
    try:
        for d in [*sorted(root.glob("*")), *(sorted((root / KEPT).glob("*")) if (root / KEPT).is_dir() else [])]:
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        if root.is_dir() and not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


# ----------------------------------------------------------------------------- the actions
def share(profile: Path, indexes: list[int], *, loc: Locations, label: str = "") -> dict:
    """Make these Separate packages of the profile Shared. Returns {operation, profile, shared: [names], reused}."""
    profile = Path(profile)
    names: list[str] = []
    reused: list[str] = []
    versions: list[str] = []
    with _Job(loc, [profile], "library-share", f"sharing {len(indexes)} mod(s) of {profile.stem}") as job:
        for i in indexes:
            _o, folder = job.own_package(profile, i)
            mod_id = folder.name.lower()
            digest, was = job.add_version(mod_id, folder.name, folder, profile.stem, label)
            job.link(profile, i, mod_id, digest)
            job.put_aside(folder, mod_id, digest)
            names.append(folder.name)
            versions.append(digest)
            if was:
                reused.append(folder.name)
        out = job.finish({"names": names, "name": profile.stem})
    return {**out, "shared": names, "versions": versions, "reused": reused}


def use_in(mod_id: str, version: str, targets: dict[Path, bool], *, loc: Locations) -> dict:
    """Link the profiles in `targets` to a version of a mod. targets: profile -> replace its own Separate copy of the
    mod (False: a profile that has one is skipped, its copy untouched). A profile already using the mod moves to this
    version; one without it gets the entry. Returns {operation, linked: [profile names], skipped: [...]}."""
    linked: list[str] = []
    skipped: list[str] = []
    with _Job(loc, list(targets), "library-use", f"using {mod_id} in {len(targets)} profile(s)") as job:
        rec = job.verified(mod_id, version)
        for profile, replace in targets.items():
            profile = Path(profile)
            w = job.writer(profile)
            mine = next(
                (e for e in w.entries() if e["kind"] == "package" and _entry_mod(profile, job.root, e) == mod_id), None
            )
            if mine is None:
                w.add_package(rec.name, job.relative(profile, version_path(job.root, mod_id, version)))
            elif link_target(profile, job.root, mine["path"]) is not None:
                job.link(profile, mine["index"], mod_id, version)
            elif replace:
                _o, folder = job.own_package(profile, mine["index"])
                same = job.read_source(folder)[0] == version
                job.link(profile, mine["index"], mod_id, version)
                job.put_aside(folder, mod_id, version if same else "")
            else:
                skipped.append(profile.stem)
                continue
            linked.append(profile.stem)
        if not linked:
            raise LibraryError("Nothing to link: every profile keeps its own copy.")
        out = job.finish({"names": [rec.name], "name": rec.name})
    return {**out, "linked": linked, "skipped": skipped}


def _entry_mod(profile: Path, root: Path, entry: dict) -> str:
    """The library id an entry stands for: its library link, else its folder name (lower case)."""
    hit = link_target(profile, root, entry["path"]) if entry["path"] else None
    return hit[0] if hit else Path(entry["path"]).name.lower()


def separate(profile: Path, indexes: list[int], *, loc: Locations) -> dict:
    """Give the profile its own copy of these Shared mods again (the library keeps the versions)."""
    profile = Path(profile)
    names: list[str] = []
    packages = library.ProfileFolder.of(profile).packages
    with _Job(loc, [profile], "library-separate", f"separate copies for {profile.stem}") as job:
        assert job.op is not None
        for i in indexes:
            _o, mod_id, version = job.shared_package(profile, i)
            rec = job.verified(mod_id, version)
            name = rec.name if rec.name.lower() == mod_id else mod_id
            dest = packages / name
            if any(d.name.lower() == name.lower() for d in _children(packages)):
                raise LibraryError(f"{profile.stem} already has a folder called {name} in its packages.")
            stage = packages / f".{name}.separate-{job.op.id}"
            packages.mkdir(parents=True, exist_ok=True)
            _copy_verified(version_path(job.root, mod_id, version), stage, version)
            _chmod(stage, write=True)
            job.op.replace_folder(dest, stage)
            job.created.append({"mod": "", "version": "", "path": str(dest), "stage": str(stage)})
            job.writer(profile).set_path(i, job.relative(profile, dest))
            names.append(name)
        out = job.finish({"names": names, "name": profile.stem})
    return {**out, "separated": names}


def _children(folder: Path) -> list[Path]:
    try:
        return list(folder.iterdir())
    except OSError:
        return []


def update(profile: Path, index: int, source: Path, *, everywhere: bool, loc: Locations, label: str = "") -> dict:
    """A new download of a Shared mod: its files become a version (an identical one is reused). Update here links this
    profile; everywhere links every profile that uses the mod. Returns {operation, version, reused, profiles}."""
    profile = Path(profile)
    home = loc.me3_profiles_dir()
    if home is None:
        raise LibraryError("me3's profiles folder was not found.")
    root, profiles_root = library.library_root(home, loc.game.key), library.profiles_root(home, loc.game.key)
    o = ProfileWriter(profile, loc).options(index)
    hit = link_target(profile, root, o["path"]) if o["kind"] == "package" and o["path"] else None
    if hit is None:
        raise LibraryError(f"{o['id'] or Path(o['path']).name} is not Shared.")
    mod_id = hit[0]
    users = usage(profiles_root, root).of(mod_id) if everywhere else [Use(profile, index, True, *hit)]
    profiles = sorted({u.profile for u in users}, key=_canon)
    with _Job(loc, profiles, "library-update", f"updating {mod_id} in {len(profiles)} profile(s)") as job:
        rec = job.record(mod_id)
        name = rec.name if rec else mod_id
        digest, reused = job.add_version(mod_id, name, Path(source), "download", label)
        for u in users:
            job.link(u.profile, u.index, mod_id, digest)
        out = job.finish({"names": [name], "name": name})
    return {**out, "version": digest, "reused": reused, "profiles": [p.stem for p in profiles]}


def unused(loc: Locations) -> tuple[list[tuple[SharedMod, Version]], str | None]:
    """(the versions no profile uses, why nobody can tell: a profile that couldn't be read; else None)."""
    home = loc.me3_profiles_dir()
    if home is None:
        return [], None
    root = library.library_root(home, loc.game.key)
    seen = usage(library.profiles_root(home, loc.game.key), root)
    out = [(m, v) for m in mods(root) for v in m.versions if not seen.of(m.id, v.id) and not seen.mentions(m.id, v.id)]
    why = None
    if seen.unreadable:
        why = f"{seen.unreadable[0].name} could not be read, so nobody can say it doesn't use a version."
    return out, why


def remove_unused(*, loc: Locations) -> dict:
    """Delete the versions no profile uses (to the Recycle Bin when there is one). Returns {operation, removed, size,
    undoable}."""
    home = loc.me3_profiles_dir()
    if home is None:
        raise LibraryError("me3's profiles folder was not found.")
    everyone = profiles_in(library.profiles_root(home, loc.game.key))
    with _Job(loc, everyone, "library-clean", "removing unused versions of the library", strict=False) as job:
        op = job.op
        assert op is not None
        found, why = unused(loc)
        if why:
            raise LibraryError(why)
        if not found:
            raise LibraryError("Every shared version is in use.")
        size = 0
        by_mod: dict[str, list[Version]] = {}
        for m, v in found:
            by_mod.setdefault(m.id, []).append(v)
        for mod_id, gone in by_mod.items():
            rec = job.record(mod_id)
            assert rec is not None
            for v in gone:
                size += v.size
                if version_path(job.root, mod_id, v.id).is_dir():
                    job.put_aside(version_path(job.root, mod_id, v.id), mod_id, "")
            rec.versions = [v for v in rec.versions if v not in gone]
            record = job.root / mod_id / RECORD
            op.write_file(record, rec.dump() if rec.versions else None, expect=_sha(record.read_bytes()))
        out = job.finish(
            {"names": [m.name for m, _ in found], "name": "unused versions", "removed": len(found), "size": size},
            bin_required=True,
            delete_without_bin=True,
        )
    prune(job.root)
    return {**out, "removed": len(found), "size": size, "undoable": bool(op.info.get("trash"))}


# ----------------------------------------------------------------------------- taking it back
def undo(op_dir: Path, log: Callable[[str], None] = lambda s: None) -> str:
    """Reverse an operation of the library: everything it moved or wrote goes back as it was. Raises LibraryError,
    with nothing changed, when anything it touched has changed since."""
    op = build.Operation.load(Path(op_dir))
    info = op.info
    if info.get("kind") not in KINDS or op.state != build.ACTIVE:
        raise LibraryError("This change can no longer be taken back.")
    profiles, root = [Path(p) for p in info["profiles"]], Path(info["library"])
    container = Path(info["container"]) if info.get("container") else None
    with ExitStack() as stack:
        for p in sorted(profiles, key=_canon):
            if not p.is_file():
                raise LibraryError(f"{p.name} is not there any more, so this can't be taken back.")
            stack.enter_context(operations.lock(p))
        stack.enter_context(build.ops_lock(Path(info["root"])))
        _check_unchanged(op, root)
        _bring_back_asides(op, container, root)
        back = build.Operation(Path(info["root"]), f"undo of {op.what}")
        try:
            for step in reversed(op.steps):
                if step["type"] == "file":
                    live = Path(step["live"])
                    before = (op.dir / step["before"]).read_bytes() if step["before"] else None
                    back.write_file(live, before, expect=build._fingerprint(live))
                elif step["type"] == "move":
                    back.move_folder(Path(step["dst"]), Path(step["src"]))
                elif step["type"] == "folder":
                    back.move_folder(Path(step["live"]), Path(step["staged"]))
        except BaseException:
            back.discard()
            raise
        try:
            back.commit()
        except build.BuildError as e:
            raise LibraryError(str(e)) from e
        back.release()
        op.release()
    for c in info.get("created") or []:
        _delete(Path(c["stage"]))  # the version (or copy) the operation made is back in its stage folder
    if container is not None:
        _delete(container)
    prune(root)
    log(f"took back: {op.what}")
    return f"took back {op.what}"


def _restorable(op: build.Operation, aside: dict) -> bool:
    """Whether a folder the operation put aside can be brought back: it is still there, in the Recycle Bin, or it was
    exactly a library version."""
    from roundtable_souls.platform import trash

    if Path(aside["dst"]).exists() or trash.exists(op.info.get("trash")):
        return True
    return bool(aside["version"]) and version_path(Path(op.info["library"]), aside["mod"], aside["version"]).is_dir()


def _check_unchanged(op: build.Operation, root: Path) -> None:
    for step in op.steps:
        if step["type"] == "file":
            live = Path(step["live"])
            want = _sha((op.dir / step["after"]).read_bytes()) if step["after"] else "missing"
            if build._fingerprint(live) != want:
                raise LibraryError(
                    f"{live.name} changed after this was done. Undoing would lose that, so nothing was changed."
                )
        elif step["type"] == "move" and Path(step["src"]).exists():
            raise LibraryError(f"{Path(step['src']).name} is back at its old place, so nothing was changed.")
        elif step["type"] == "folder" and not Path(step["live"]).is_dir():
            raise LibraryError(f"{Path(step['live']).name} is not where it was left, so nothing was changed.")
    for a in op.info.get("asides") or []:
        if not _restorable(op, a):
            raise LibraryError(f"{Path(a['src']).name} can't be brought back any more, so nothing was changed.")
    mine = {_canon(p) for p in op.info["profiles"]}
    seen = usage(Path(op.info["root"]), root)
    for c in op.info.get("created") or []:
        if c["version"] and any(_canon(u.profile) not in mine for u in seen.of(c["mod"], c["version"])):
            raise LibraryError("Another profile uses this version now, so it can't be taken back.")


def _bring_back_asides(op: build.Operation, container: Path | None, root: Path) -> None:
    from roundtable_souls.platform import trash

    if container is None:
        return
    if not container.exists() and trash.exists(op.info.get("trash")):
        trash.restore(op.info["trash"], dest=container)
    for a in op.info.get("asides") or []:
        dst = Path(a["dst"])
        if not dst.exists():  # in the bin no more, but it was a library version: a verified copy of it
            dst.parent.mkdir(parents=True, exist_ok=True)
            _copy_verified(version_path(root, a["mod"], a["version"]), dst, a["version"])
            _chmod(dst, write=True)


# ----------------------------------------------------------------------------- listings (nothing is written)
HINT_BYTES = 1024**3  # the Mods page suggests sharing only when duplicated packages total more than this


@dataclass(frozen=True)
class Copy:
    """A Separate package of a profile."""

    profile: Path
    index: int
    name: str
    folder: Path


@dataclass
class Twins:
    """The same files in several profiles as Separate copies."""

    name: str
    version: str
    size: int
    copies: list[Copy]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.copies) - 1)


def _shape(folder: Path) -> tuple[int, int]:
    files = _files(folder)
    return len(files), sum(p.stat().st_size for _r, p in files)


def separate_copies(loc: Locations, only: Path | None = None) -> list[Copy]:
    """Every Separate package (in its profile's own packages/ folder) of the launcher's profiles, or of `only`."""
    home = loc.me3_profiles_dir()
    if home is None:
        return []
    out: list[Copy] = []
    for profile in [Path(only)] if only else profiles_in(library.profiles_root(home, loc.game.key)):
        packages = _canon(library.ProfileFolder.of(profile).packages)
        try:
            found = me3_profile.entries(profile.read_bytes().decode("utf-8"))
        except OSError, ValueError:
            continue
        for e in found:
            if e["kind"] != "package" or not e["path"]:
                continue
            folder = me3_profile.resolve(profile, e["path"])
            if _canon(folder.parent) == packages and folder.is_dir():
                out.append(Copy(profile, e["index"], folder.name, folder))
    return out


def duplicates(loc: Locations) -> list[Twins]:
    """Groups of identical Separate packages in two or more profiles, biggest saving first. Files are compared by
    name, file count and size first and hashed only when those agree."""
    by_shape: dict[tuple[str, int, int], list[Copy]] = {}
    for c in separate_copies(loc):
        by_shape.setdefault((c.name.lower(), *_shape(c.folder)), []).append(c)
    out: list[Twins] = []
    for (_name, _n, size), copies in by_shape.items():
        if len({_canon(c.profile) for c in copies}) < 2:
            continue
        by_hash: dict[str, list[Copy]] = {}
        for c in copies:
            by_hash.setdefault(tree_hash(c.folder)[0], []).append(c)
        out += [Twins(g[0].name, h, size, g) for h, g in by_hash.items() if len({_canon(c.profile) for c in g}) > 1]
    return sorted(out, key=lambda t: -t.wasted)


def duplicate_total(twins: list[Twins]) -> int:
    return sum(t.wasted for t in twins)


def identical_elsewhere(loc: Locations, folder: Path, profile: Path) -> list[Copy]:
    """Separate packages of OTHER profiles with exactly the files in `folder` (a mod about to be installed in
    `profile`). Empty when none."""
    shape = _shape(folder)
    digest = None
    out = []
    for c in separate_copies(loc):
        if _canon(c.profile) == _canon(profile) or _shape(c.folder) != shape:
            continue
        digest = digest or tree_hash(folder)[0]
        if tree_hash(c.folder)[0] == digest:
            out.append(c)
    return out


@dataclass
class VersionInfo:
    version: Version
    used_by: list[str]
    unused: bool


@dataclass
class ModInfo:
    mod: SharedMod
    versions: list[VersionInfo]

    @property
    def size(self) -> int:
        return sum(v.version.size for v in self.versions)


def listing(loc: Locations) -> list[ModInfo]:
    """The Library page: every Shared mod, its versions, who uses each."""
    home = loc.me3_profiles_dir()
    if home is None:
        return []
    root = library.library_root(home, loc.game.key)
    seen = usage(library.profiles_root(home, loc.game.key), root)
    out = []
    for m in mods(root):
        infos = []
        for v in m.versions:
            names = sorted({u.profile.stem for u in seen.of(m.id, v.id)}, key=str.lower)
            infos.append(VersionInfo(v, names, not names and not seen.mentions(m.id, v.id)))
        out.append(ModInfo(m, infos))
    return out


def shared_count(loc: Locations, profile: Path, index: int) -> int:
    """For a Shared entry: how many profiles use the mod it links to (0 when it is Separate)."""
    home = loc.me3_profiles_dir()
    if home is None:
        return 0
    root = library.library_root(home, loc.game.key)
    try:
        e = next(e for e in me3_profile.entries(Path(profile).read_bytes().decode("utf-8")) if e["index"] == index)
    except OSError, ValueError, StopIteration:
        return 0
    hit = link_target(Path(profile), root, e["path"]) if e["path"] else None
    if hit is None:
        return 0
    return len({_canon(u.profile) for u in usage(library.profiles_root(home, loc.game.key), root).of(*hit)})


def record_of(folder: Path) -> SharedMod | None:
    """The mod a library version folder belongs to (None for any other folder)."""
    folder = Path(folder)
    return read_mod(folder.parent.parent, folder.parent.name) if (folder.parent / RECORD).is_file() else None


def install_facts(loc: Locations, profile: Path, plan: dict, known: dict | None = None) -> dict:
    """What the Library adds to an install plan: {"shared": {index, name, profiles}} when the download is a new version
    of a mod the profile has Shared; {"identical": [profile names]} when other profiles have a Separate copy of exactly
    these files; {} otherwise (also for a profile that can't share). known: the facts of the plan before a rename, whose
    (slow) comparison of files is not done again."""
    profile = Path(profile)
    home = loc.me3_profiles_dir()
    if home is None or plan.get("kind") != "package" or not plan.get("root") or not plan.get("dest"):
        return {}
    if not (library.in_game_root(profile, home, loc.game.key) and library.own_folder(profile)):
        return {}
    root = library.library_root(home, loc.game.key)
    name, ident = Path(plan["dest"]).name.lower(), str(plan.get("id") or "").lower()
    try:
        found = me3_profile.entries(profile.read_bytes().decode("utf-8"))
    except OSError, ValueError:
        return {}
    for e in found:
        hit = link_target(profile, root, e["path"]) if e["kind"] == "package" and e["path"] else None
        if hit and (hit[0] == name or str(e["id"]).lower() == ident):
            rec = read_mod(root, hit[0])
            users = {_canon(u.profile) for u in usage(library.profiles_root(home, loc.game.key), root).of(hit[0])}
            return {"shared": {"index": e["index"], "name": rec.name if rec else hit[0], "profiles": len(users)}}
    if known is not None and "checked" in known:
        return known
    twins = identical_elsewhere(loc, Path(plan["root"]), profile)
    return {"identical": sorted({c.profile.stem for c in twins}, key=str.lower), "checked": True}


def share_everything(profile: Path, *, loc: Locations) -> dict | None:
    """Share every Separate package of the profile (None when it has none)."""
    job_less = [c.index for c in separate_copies(loc, only=Path(profile))]
    return share(Path(profile), job_less, loc=loc) if job_less else None


def page_info(loc: Locations, profile: Path, entries: list[dict]) -> tuple[dict[int, int], tuple[int, ...], bool]:
    """For the Mods page: ({entry index: profiles using that mod} for its Shared entries, the indexes of Separate
    packages that can be shared, whether the Library holds anything in use at all)."""
    home = loc.me3_profiles_dir()
    profile = Path(profile)
    if home is None or not (library.in_game_root(profile, home, loc.game.key) and library.own_folder(profile)):
        return {}, (), False
    root = library.library_root(home, loc.game.key)
    seen = usage(library.profiles_root(home, loc.game.key), root)
    count = {k: len({_canon(u.profile) for u in seen.of(*k)}) for k in {(u.mod, u.version) for u in seen.uses}}
    shared = {u.index: count[(u.mod, u.version)] for u in seen.uses if _canon(u.profile) == _canon(profile)}
    listed = {e["index"] for e in entries}
    can = tuple(c.index for c in separate_copies(loc, only=profile) if c.index in listed)
    return shared, can, bool(seen.uses)


@dataclass(frozen=True)
class Candidate:
    profile: Path
    has_copy: bool  # it has its own Separate copy of the mod: linking replaces it (only if the player ticks it)
    uses: bool  # it already uses the mod (another version, or this one)


def candidates(loc: Locations, profile: Path, mod_id: str) -> list[Candidate]:
    """The other profiles that can use a Shared mod, with what each has of it now."""
    home = loc.me3_profiles_dir()
    if home is None:
        return []
    out = []
    root = library.library_root(home, loc.game.key)
    for p in profiles_in(library.profiles_root(home, loc.game.key)):
        if _canon(p) == _canon(profile) or not library.own_folder(p):
            continue
        try:
            found = me3_profile.entries(p.read_bytes().decode("utf-8"))
        except OSError, ValueError:
            continue
        mine = next(
            (e for e in found if e["kind"] == "package" and e["path"] and _entry_mod(p, root, e) == mod_id), None
        )
        linked = mine is not None and link_target(p, root, mine["path"]) is not None
        out.append(Candidate(p, mine is not None and not linked, linked))
    return out
