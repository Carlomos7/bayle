"""The Merge page's facts, read from what the last build left (its record) and the profile's merge health: which game
files were merged from which mods, where the copies of one file met (the later mod's wins), what was left out. File
level only: nothing here looks inside a file, and nothing is invented: a fact the record does not hold is absent.

    report    GET /v1/builds: the state, why it is stale, the files, the mods in load order, what was left out
    preview   what a rebuild would need now (a tool's approval, the files it would combine); writes nothing
    accept    remember that the player plays without a left-out change (kept in the profile's settings.json)

Mods are named by their profile entry index (the page maps it to the id it uses); no wording here.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from bayle.errors import OperationError
from bayle.modules.games.locate import Locations
from bayle.modules.mods import ports as tool_ports
from bayle.modules.mods import profile_mods, rebuild
from bayle.modules.mods import profile_settings as ps
from bayle.work.jobs import JobManager

ACCEPTED = "accepted_dropped"  # profile_settings key: ids of left-out changes the player plays without
REGULATION = rebuild.REGULATION

# (family, extension or path part): first match wins; the rest is "other"
_FAMILIES = (
    ("params", ("regulation.bin", ".param")),
    ("text", ("msgbnd",)),
    ("animations", ("anibnd", ".tae", ".hkx")),
    ("scripts", ("talkesdbnd", "luabnd", ".lua", ".esd")),
    ("behaviour", ("behbnd",)),
    ("textures", ("texbnd", ".tpf", ".dds")),
)


def family_of(path: str) -> str:
    low = path.lower()
    return next((fam for fam, marks in _FAMILIES if any(m in low for m in marks)), "other")


@dataclass(frozen=True)
class BuildMod:
    index: int  # the profile entry's block index
    name: str


@dataclass(frozen=True)
class ClashPart:
    part: str  # the inner path, e.g. SB_KG.layout
    mods: list[int]  # entry indexes, in load order; the last one's is used


@dataclass(frozen=True)
class BuildFile:
    path: str  # relative to the game, with /
    family: str
    mods: list[int]  # the mods that ship it, in load order (the last one wins what is not merged)
    merged: bool  # the copies were combined; False: the last mod's whole copy is used
    skipped: str = ""  # why it was not merged (the record's words)
    parts: int = 0  # inner parts that changed
    clashes: list[ClashPart] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)  # "part: text"


@dataclass(frozen=True)
class Dropped:
    id: str
    mod: int
    file: str
    family: str
    kind: str  # "whole_copy" (an unmerged file: this mod's copy is not used) | "left_out" (parts its copy leaves out) | "lacks" (inner files the game has)
    detail: str = ""  # whole_copy: why; lacks: the record's notice
    count: int = 0  # left_out: how many parts
    accepted: bool = False


@dataclass(frozen=True)
class BuildFacts:
    state: str | None  # rebuild.health's: single | stacked | current | stale | failed; None: no Elden Ring profile
    reasons: list[str]  # why it is not current, in the engine's words
    built_on: str  # the record's "when", "" when there is no record
    mods: list[BuildMod]  # load order (the combined package itself is left out)
    files: list[BuildFile]
    dropped: list[Dropped]


@dataclass(frozen=True)
class BuildPreview:
    state: str | None
    blocked: str  # "" or the code the rebuild would be refused with (rebuild_game_running, rebuild_blocked, nothing_to_rebuild)
    detail: str  # the refusal's detail
    tool: str  # the rebuild tool's label, "" when the launcher combines itself
    needs_allow: bool  # the tool has not been allowed yet
    problem: str  # why the tool cannot run, ""
    files: list[str]  # shared game files a combine would merge
    packs: list[str]  # packs whose parameters it would combine
    reasons: list[str]


def _dropped_id(mod: str, file: str, what: str) -> str:
    return hashlib.sha1(f"{mod}|{file}|{what}".encode()).hexdigest()[:16]


class BuildsService:
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
        path = Path(profile) if profile else None
        if path is None or path.suffix.lower() != ".me3" or not path.is_file():
            raise OperationError("not_found", "That profile is not there.", {"profile": str(profile)})
        return path

    # ------------------------------------------------------------------ report
    def report(self, profile: str | Path) -> BuildFacts:
        """Raises not_found, no_game."""
        path, loc = self._profile(profile), self._loc()
        health = rebuild.health(path, loc=loc)
        if health["state"] is None:
            return BuildFacts(None, [], "", [], [], [])
        all_layers = rebuild.layers(path)
        combine = tool_ports.combine().find(path, all_layers, loc=loc)
        record = combine.record() if combine is not None else {}
        own = os.path.normcase(str(combine.folder)) if combine is not None else None
        layers = [l for l in all_layers if own is None or os.path.normcase(str(l["folder"])) != own]
        by_name = {l["name"]: l["index"] for l in layers}
        files, dropped = _files(record, layers, by_name)
        accepted = set(ps.load(path).get(ACCEPTED) or [])
        dropped = [Dropped(**{**vars(d), "accepted": d.id in accepted}) for d in dropped]
        built = str(record.get("when") or "")
        if not built and health["run"]:
            built = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(health["run"]["when"]))
        return BuildFacts(
            health["state"],
            list(health["reasons"]),
            built,
            [BuildMod(l["index"], l["name"]) for l in layers],
            files,
            dropped,
        )

    # ------------------------------------------------------------------ preview
    def preview(self, profile: str | Path) -> BuildPreview:
        """What a rebuild needs now. Raises not_found, no_game."""
        path, loc = self._profile(profile), self._loc()
        health = rebuild.health(path, loc=loc)
        refusal = profile_mods.rebuild_refusal(path, loc=loc, game_running=self._jobs.game_running)
        tool = profile_mods.tool_state(path, loc=loc) if health["state"] is not None else None
        return BuildPreview(
            health["state"],
            refusal[0] if refusal else "",
            refusal[1] if refusal else "",
            tool.tool.label if tool is not None and tool.tool is not None else "",
            tool is not None and tool.tool is not None and not tool.allowed,
            tool.problem if tool is not None else "",
            list(health.get("shared_files") or []),
            list(health["packs"]),
            list(health["reasons"]),
        )

    # ------------------------------------------------------------------ accept
    def accept_dropped(self, profile: str | Path, dropped_id: str) -> None:
        """Play without this left-out change. Raises not_found (the profile, or no such change now),
        profile_write_failed."""
        path = self._profile(profile)
        if all(d.id != dropped_id for d in self.report(path).dropped):
            raise OperationError("not_found", "That change is not left out now.", {"id": dropped_id})
        kept = list(ps.load(path).get(ACCEPTED) or [])
        if dropped_id in kept:
            return
        try:
            ps.update(path, **{ACCEPTED: [*kept, dropped_id]})
        except (OSError, ps.Unreadable) as e:
            raise OperationError("profile_write_failed", "The choice could not be saved.", {"why": str(e)}) from e


def _files(record: dict, layers: list[dict], by_name: dict[str, int]) -> tuple[list[BuildFile], list[Dropped]]:
    """The files the build combined or left to the later mod, from the record, and what that leaves out."""
    owner = {os.path.normcase(str(Path(l["folder"]))): l for l in layers}
    out: list[BuildFile] = []
    dropped: list[Dropped] = []

    def drop(name: str, index: int, file: str, kind: str, *, detail: str = "", count: int = 0) -> Dropped:
        return Dropped(_dropped_id(name, file, kind), index, file, family_of(file), kind, detail, count)

    def who(source_path: str, rel: str) -> dict | None:
        """The layer whose folder holds this copy of the game file rel."""
        up = Path(source_path).parents
        n = len(Path(rel).parts)
        return owner.get(os.path.normcase(str(up[n - 1]))) if len(up) >= n else None

    packs = [p for p in record.get("packs") or [] if isinstance(p, dict) and p.get("path")]
    if packs:
        mods = [m["index"] for p in packs if (m := who(p["path"], REGULATION))]
        out.append(BuildFile(REGULATION, "params", mods, True))
    for entry in (record.get("files") or {}).values():
        rel = entry.get("rel") or ""
        owners = [m for s in entry.get("sources") or [] if (m := who(s.get("path", ""), rel))]
        mods = [m["index"] for m in owners]
        merged = bool(entry.get("output"))
        clashes = []
        for part, names in (entry.get("clashes") or {}).items():
            idx = [by_name[n] for n in names if n in by_name]
            if len(idx) > 1:
                clashes.append(ClashPart(part, idx))
        warnings = [f"{part}: {t}" for part, said in (entry.get("warnings") or {}).items() for t in said]
        out.append(
            BuildFile(
                rel,
                family_of(rel),
                mods,
                merged,
                str(entry.get("skipped") or ""),
                int(entry.get("parts") or 0),
                clashes,
                warnings,
            )
        )
        skipped = str(entry.get("skipped") or "")
        for m in owners[:-1] if not merged else []:  # an unmerged file: only the last mod's copy is used
            dropped.append(drop(m["name"], m["index"], rel, "whole_copy", detail=skipped))
        left: dict[str, int] = {}
        for names in (entry.get("removed") or {}).values():
            for n in names:
                if n in by_name:
                    left[n] = left.get(n, 0) + 1
        for n, count in left.items():
            dropped.append(drop(n, by_name[n], rel, "left_out", count=count))
        for om in entry.get("omissions") or []:
            notice = str(om.get("notice") or "")
            name = next((n for n in by_name if notice.startswith(f"{n} lacks")), None)
            # a notice that names no mod is not attributed to one; one whose left-out parts are counted above is the same fact
            if name is not None and name not in left:
                dropped.append(drop(name, by_name[name], str(om.get("path") or rel), "lacks", detail=notice))
    return out, dropped
