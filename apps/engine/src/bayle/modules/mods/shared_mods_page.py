"""The Library as the Mods page uses it: sharing a profile's game-file mods, linking other profiles, separate copies,
updates and removing unused versions. Each leaves the Activity undo record (mods.undo); the work is mods.shared_mods'."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.adapters.system import logging as run_logging
from bayle.errors import OperationError
from bayle.modules.games.locate import Locations
from bayle.modules.mods import service as mod_service
from bayle.modules.mods import shared_mods
from bayle.modules.mods.mod_configs import logged, stamp
from bayle.work.jobs import JobManager

if TYPE_CHECKING:
    from bayle.modules.games.locate import Locations

Error = shared_mods.LibraryError


def undo_of(kind: str, out: dict) -> dict:
    """The Activity undo record of one Library change (what share, use_in, ... returned)."""
    return {"type": kind, "profile": out["profile"], "name": out.get("name", ""), "operation": out["operation"]}


def chain(name: str, *undos: dict) -> dict:
    """One Activity undo for several changes a job made, given in the order they were made: Undo takes the last one
    back first, and is offered only while every one still can be."""
    return {"type": "multi", "name": name, "profile": undos[0].get("profile", ""), "undos": list(reversed(undos))}


def _record(kind: str, out: dict) -> dict:
    out["undo"] = undo_of(kind, out)
    run_logging.set_undo(out["undo"])
    return out


def share(profile: Path, indexes: list[int], *, loc: Locations) -> dict:
    """Share these Separate packages. Raises Error (nothing changed) when it can't be done."""
    return _record("library-share", shared_mods.share(profile, indexes, loc=loc))


def use_in(mod_id: str, version: str, targets: dict[Path, bool], *, loc: Locations) -> dict:
    """Link profiles to a version; targets: profile -> replace its own Separate copy."""
    return _record("library-use", shared_mods.use_in(mod_id, version, targets, loc=loc))


def separate(profile: Path, indexes: list[int], *, loc: Locations) -> dict:
    return _record("library-separate", shared_mods.separate(profile, indexes, loc=loc))


def update(profile: Path, index: int, source: Path, *, everywhere: bool, loc: Locations, label: str = "") -> dict:
    return _record(
        "library-update", shared_mods.update(profile, index, source, everywhere=everywhere, loc=loc, label=label)
    )


def unused(loc: Locations) -> tuple[list[tuple[shared_mods.SharedMod, shared_mods.Version]], str | None]:
    """(versions no profile uses, why nobody can tell or None): for the confirm."""
    return shared_mods.unused(loc)


def remove_unused(*, loc: Locations) -> dict:
    out = shared_mods.remove_unused(loc=loc)
    if out["undoable"]:
        _record("library-clean", out)
    return out


def shared_ref(profile: Path, entry: dict, *, loc: Locations) -> tuple[str, str] | None:
    """(mod id, version id) when a profile entry is Shared, else None."""
    home = loc.me3_profiles_dir()
    if home is None or not entry.get("path"):
        return None
    root = shared_mods.library.library_root(home, loc.game.key)
    return shared_mods.link_target(Path(profile), root, entry["path"])


def version_size(mod_id: str, version: str, *, loc: Locations) -> int:
    rec = shared_mods.read_mod(shared_mods.root_of(loc), mod_id)
    found = rec.version(version) if rec else None
    return found.size if found else 0


def display_name(mod_id: str, *, loc: Locations) -> str:
    rec = shared_mods.read_mod(shared_mods.root_of(loc), mod_id)
    return rec.name if rec else mod_id


def candidates(profile: Path, mod_id: str, *, loc: Locations) -> list[shared_mods.Candidate]:
    return shared_mods.candidates(loc, profile, mod_id)


def listing(loc: Locations) -> list[shared_mods.ModInfo]:
    return shared_mods.listing(loc)


_scanned: dict[str, tuple[tuple, tuple[int, int]]] = {}  # per game: (profile files' stamp, result)
_scan_lock = threading.Lock()


def _stamp(loc: Locations) -> tuple:
    home = loc.me3_profiles_dir()
    if home is None:
        return ()
    try:
        found = shared_mods.profiles_in(shared_mods.library.profiles_root(home, loc.game.key))
        return tuple((str(p), p.stat().st_mtime_ns) for p in found)
    except OSError:
        return ()


def duplicates(loc: Locations) -> tuple[int, int]:
    """(mods in several profiles as Separate copies, bytes they waste) for the Mods page's hint; (0, 0) when it can't
    be worked out. Scanned again only when a profile file changed (an install, remove or share rewrites one), so a
    page refresh costs a few stats."""
    with _scan_lock:
        stamp = _stamp(loc)
        hit = _scanned.get(loc.game.key)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            twins = shared_mods.duplicates(loc)
        except OSError:
            return 0, 0
        out = len({t.name.lower() for t in twins}), shared_mods.duplicate_total(twins)
        _scanned[loc.game.key] = stamp, out
        return out


def separate_copies(profile: Path, *, loc: Locations) -> list[shared_mods.Copy]:
    return shared_mods.separate_copies(loc, only=Path(profile))


@dataclass(frozen=True)
class LibraryVersion:
    id: str
    installed: str  # the date, "" when unknown
    label: str
    size: int
    used_by: tuple[str, ...]  # profile names
    unused: bool


@dataclass(frozen=True)
class LibraryMod:
    id: str
    name: str
    size: int
    versions: tuple[LibraryVersion, ...]


@dataclass(frozen=True)
class SharePlan:
    """What sharing or separating one entry would do: the client words it and sends stamp back to start it."""

    name: str
    size: int  # of the shared version (separate only; 0 for share)
    stamp: tuple[int, int] | None  # of the profile when planned


@dataclass(frozen=True)
class UseProfile:
    profile: str  # the .me3 path
    name: str
    has_copy: bool  # its own Separate copy of the mod: linking replaces it
    uses: bool  # it already uses the mod (another version, or this one)


@dataclass(frozen=True)
class UseChoices:
    name: str
    mod_id: str
    version: str
    profiles: tuple[UseProfile, ...]


@dataclass(frozen=True)
class UnusedVersion:
    mod_id: str
    version: str
    name: str
    installed: str
    size: int


@dataclass(frozen=True)
class UnusedPlan:
    versions: tuple[UnusedVersion, ...]
    size: int

    @property
    def token(self) -> tuple[str, ...]:
        """What a start is checked against: the versions the client was shown."""
        return tuple(f"{v.mod_id}/{v.version}" for v in self.versions)


class ModLibraryService:
    """The shared mod Library (versions kept once for every profile) for one engine: jobs is its JobManager, locations the current game's Locations (None: no game selected).
    Returns data and OperationError codes, never wording: the Qt page words them.

    A change is a check (facts, writes nothing) and a start (with the stamp, or the versions, the client confirmed;
    stale when they changed since); the starts are logged jobs with the Activity undo record, their ids are returned
    and a refusal of the Library (nothing changed) fails the job with code library_refused. Entries are named by
    their index in the profile and must be there (not_found); profiles to link must be ones use_choices lists."""

    def __init__(self, jobs: JobManager, locations: Callable[[], Locations | None]) -> None:
        self._jobs, self._locations = jobs, locations

    def _loc(self) -> Locations:
        try:
            loc = self._locations()
        except OperationError:
            loc = None
        if loc is None:
            raise OperationError("no_game", "No game is selected.")
        return loc

    @staticmethod
    def _profile(profile: str | Path) -> Path:
        if not profile or not Path(profile).is_file():
            raise OperationError("not_found", "That profile is not there.", {"profile": str(profile)})
        return Path(profile)

    def _entry(self, profile: str | Path, index: int) -> dict:
        prof = self._profile(profile)
        entry = next((e for e in mod_service.profile_entries(prof) if e["index"] == index), None)
        if entry is None:
            raise OperationError("not_found", "The profile changed; look again.", {"index": index})
        return entry

    def _shared(self, profile: str | Path, index: int) -> tuple[tuple[str, str], str]:
        """The Shared mod (id, version) the entry uses and its name. Raises not_shared."""
        loc = self._loc()
        ref = shared_ref(self._profile(profile), self._entry(profile, index), loc=loc)
        if ref is None:
            raise OperationError("not_shared", "This mod is not shared.")
        return ref, display_name(ref[0], loc=loc)

    @staticmethod
    def _expect(prof: Path, expect: tuple[int, int] | None) -> None:
        if stamp(prof) != (tuple(expect) if expect is not None else None):
            raise OperationError("stale", "The profile changed since you were asked. Ask again.")

    def _job(self, title: str, what: str, work: Callable[[Locations], object]) -> str:
        """work(loc) as a logged job of its own inside a session job (writing: not while the game or another write
        runs); returns the session job's id. The Library refuses with its reason and changes nothing."""
        loc = self._loc()

        def body() -> dict:
            try:
                work(loc)
            except Error as e:
                raise OperationError("library_refused", str(e)) from e
            run_logging.log(f"done: {what}")
            return {"note": what}

        return self._jobs.start(lambda _ctx: logged(f"launcher: {what}", loc, body), title=title, quiet=True)

    # ---- reading
    def mods(self) -> list[LibraryMod]:
        """Every Shared mod with its versions and who uses each ([] when it cannot be read)."""
        try:
            found = listing(self._loc())
        except Exception:
            return []
        return [
            LibraryMod(
                m.mod.id,
                m.mod.name,
                m.size,
                tuple(
                    LibraryVersion(
                        v.version.id, v.version.installed, v.version.label, v.version.size, tuple(v.used_by), v.unused
                    )
                    for v in m.versions
                ),
            )
            for m in found
        ]

    def use_choices(self, profile: str | Path, index: int) -> UseChoices:
        """The other profiles a Shared mod could be linked into. Raises not_found, not_shared, no_other_profiles."""
        ref, name = self._shared(profile, index)
        found = candidates(Path(profile), ref[0], loc=self._loc())
        if not found:
            raise OperationError("no_other_profiles", "There are no other profiles.")
        rows = tuple(UseProfile(str(c.profile), c.profile.stem, c.has_copy, c.uses) for c in found)
        return UseChoices(name, ref[0], ref[1], rows)

    # ---- share, separate
    def check_share(self, profile: str | Path, index: int) -> SharePlan:
        """Raises not_found."""
        return SharePlan(self._entry(profile, index)["name"], 0, stamp(self._profile(profile)))

    def share(self, profile: str | Path, index: int, expect: tuple[int, int] | None) -> str:
        """Share a Separate package (its files become shared mods and the profile uses them from there) as a job
        with an Undo; returns its id. Raises not_found, stale, busy."""
        prof = self._profile(profile)
        name = self._entry(prof, index)["name"]
        self._expect(prof, expect)
        return self._job(f"Sharing {name}...", f"share {name}", lambda loc: share(prof, [index], loc=loc))

    def check_separate(self, profile: str | Path, index: int) -> SharePlan:
        """Raises not_found, not_shared."""
        ref, name = self._shared(profile, index)
        return SharePlan(name, version_size(*ref, loc=self._loc()), stamp(self._profile(profile)))

    def separate(self, profile: str | Path, index: int, expect: tuple[int, int] | None) -> str:
        """Give the profile its own editable copy of a Shared mod, as a job with an Undo; returns its id. The other
        profiles keep the shared files. Raises not_found, not_shared, stale, busy."""
        prof = self._profile(profile)
        _ref, name = self._shared(prof, index)
        self._expect(prof, expect)
        return self._job(
            f"Copying {name}...",
            f"separate copy of {name}",
            lambda loc: separate(prof, [index], loc=loc),
        )

    def use_in(self, profile: str | Path, index: int, targets: list[str]) -> str:
        """Link the chosen profiles (use_choices' ones: a profile with its own copy has it replaced) to the version
        this profile uses, as a job with an Undo; returns its id. Raises not_found, not_shared, nothing_chosen, busy."""
        if not targets:
            raise OperationError("nothing_chosen", "Nothing was chosen.")
        ref, name = self._shared(profile, index)
        listed = {str(c.profile): c.profile for c in candidates(Path(profile), ref[0], loc=self._loc())}
        missing = [t for t in targets if str(t) not in listed]
        if missing:
            raise OperationError("not_found", "That profile cannot use this mod.", {"profiles": missing})
        chosen = {listed[str(t)]: True for t in targets}
        return self._job(
            f"Linking {name}...",
            f"use {name} in other profiles",
            lambda loc: use_in(ref[0], ref[1], chosen, loc=loc),
        )

    # ---- unused versions
    def check_remove_unused(self) -> UnusedPlan:
        """The versions no profile uses. Raises cannot_tell (the reason is the message), nothing_unused."""
        found, why = unused(self._loc())
        if why:
            raise OperationError("cannot_tell", why)
        if not found:
            raise OperationError("nothing_unused", "Every shared version is in use.")
        return UnusedPlan(
            tuple(UnusedVersion(m.id, v.id, m.name, v.installed, v.size) for m, v in found),
            sum(v.size for _m, v in found),
        )

    def remove_unused(self, expect: tuple[str, ...]) -> str:
        """Remove the versions the client was shown (to the Recycle Bin; Undo in Activity brings them back), as a
        job; returns its id. expect: check_remove_unused' token. Raises cannot_tell, nothing_unused, stale, busy."""
        if tuple(expect) != self.check_remove_unused().token:
            raise OperationError("stale", "The Library changed since you were asked. Ask again.")
        return self._job(
            "Removing unused versions...",
            "remove unused library versions",
            lambda loc: remove_unused(loc=loc),
        )
