"""Installing an overhaul into a me3 profile with the launcher (preview), removing one, and cleaning up what an
overhaul's own installer left: each previewed in plain words first, each one undoable operation (mods.operations).
Nothing here knows a particular overhaul: everything comes from its config (overhauls.OverhaulConfig).

    install   a download the launcher recognises (a config's build with an install description, at a listed version)
              goes in as one operation: a copy of the download's files its build reads, the launcher's build of it
              (mods.engine, built against the profile as the install leaves it, the player's settings file kept),
              the profile's changes (overhauls.install_plan, written by the profile writer, with paths relative to the
              profile) and the launcher's records. A failure, or an interruption found on the next start, puts the
              previous state back. Installing again is an update of the earlier install (the plan replaces its
              entries); a profile with another overhaul is refused (one overhaul per profile for now). A setup made by
              the overhaul's own installer is not rewritten: it is removed first (adopting one comes later).
    remove    the overhaul's own entries leave the profile; each change its install made to other entries or
              settings (its side effects, recorded at install) is put back only where the value is still what the
              install set, anything else is left and said; a shared dependency (Seamless Co-op) is never removed, and
              switching it back off is asked. The overhaul's folder, its build and the launcher's copy of its download
              go to the Recycle Bin only when no other profile beside it uses them.
    legacy    a setup the overhaul's own installer made (found through the config's [recognise]: its folder and
              manifest, with no launcher install) is removed the same way; its side effects are worked out from the
              oldest of the installer's profile backups and offered to choose from; the installer's own folders are
              offered for removal with their sizes, its backups last and apart.

Where things are (owner, 2026-10-13): the overhaul's runtime folder stays beside the profile (recognise.folder,
where its installer puts it too, so Play, the offline launch and the rebuild before Play find it as before, with its
merged mod/ inside); the launcher's own files for it are in the game's library (mods.library, rs-<game>/ in me3's
profiles folder, made on first use), by its paths (Places):

    sources/<id>/                       the download's files its build reads, at their download paths (today's
                                        engine reads them there; sorting them by role is 3.23's), with roundtable.json
                                        (records.SourcesRecord: each file's origin and hash)
    overhauls/<id>/roundtable.json      the install (records.OverhaulRecord: its build, the download's fingerprint,
                                        when, from where)
    builds/<id>/<profile>/roundtable.json   what the install changed outside its own entries in that profile
                                        (records.SideEffectsRecord); the build itself stays in the runtime folder

The overhaul's own installer files are never written.
"""

from __future__ import annotations

import datetime
import fnmatch
import hashlib
import json
import os
import shutil
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from roundtable_souls import overhauls
from roundtable_souls.formats import me3_profile
from roundtable_souls.game import catalog as games
from roundtable_souls.mods import library, operations, records
from roundtable_souls.mods.checks import same_folder
from roundtable_souls.mods.library import ProfileFolder
from roundtable_souls.mods.overhaul_manifest import INSTALLED_BY, launcher_installed
from roundtable_souls.mods.profile_edit import ModError, quote
from roundtable_souls.mods.profile_writer import Plan as WriterPlan
from roundtable_souls.mods.profile_writer import ProfileWriter
from roundtable_souls.overhauls import install_plan, requirements, sources
from roundtable_souls.overhauls.config import Build, OverhaulConfig
from roundtable_souls.platform import trash

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations

# Keys of the overhaul installer's own manifest that describe its install, not the launcher's: left out of the
# manifest of a launcher install so nothing reads them as if they were true of it.
_INSTALLER_KEYS = ("baseProfile", "profiles", "sourceProfile", "launch", "me3", "seamless")


class OverhaulError(ModError):
    """Why an overhaul can't be installed or removed, in plain words; nothing was changed."""


class NotAnOverhaul(OverhaulError):
    """No overhaul config describes the download at all (as opposed to one at another version or edition)."""


# ----------------------------------------------------------------------------- where things are
@dataclass(frozen=True)
class Places:
    """The launcher's own files for one overhaul in one profile, in the profile's own folder (see the module notes)."""

    library: ProfileFolder
    overhaul: str
    profile: Path

    @property
    def sources(self) -> Path:
        """The download copy: its files at download paths, and its record."""
        return self.library.sources(self.overhaul).root

    @property
    def sources_record(self) -> Path:
        return self.library.sources(self.overhaul).record

    @property
    def record(self) -> Path:
        return self.library.overhaul_record(self.overhaul)

    @property
    def effects(self) -> Path:
        return self.library.build(self.overhaul).side_effects


def places(profile: Path, overhaul_id: str, loc: Locations) -> Places | None:
    """Where the launcher keeps its files for this overhaul in this profile's folder."""
    lib = library.ProfileFolder.of(profile)
    return Places(lib, overhaul_id, Path(profile))


def own_folder(profile: Path, config: OverhaulConfig) -> Path:
    """The overhaul's own folder beside the profile, where its installer puts it too."""
    return Path(profile).parent / config.recognise.folder


def _manifest(own: Path, config: OverhaulConfig) -> dict | None:
    try:
        data = json.loads((own / config.recognise.manifest).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return data if isinstance(data, dict) else None


def installed_by_launcher(profile: Path, config: OverhaulConfig) -> bool:
    data = _manifest(own_folder(profile, config), config)
    return data is not None and launcher_installed(data)


def installer_setup(profile: Path, config: OverhaulConfig) -> Path | None:
    """The overhaul's folder beside the profile when its own installer made it (its manifest is there and the
    launcher did not install it), else None."""
    own = own_folder(profile, config)
    data = _manifest(own, config)
    return own if data is not None and not launcher_installed(data) else None


def size_of(path: Path) -> int:
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.is_dir() else 0


def size_text(n: int) -> str:
    """A size in plain words: 12 KB, 3.4 MB, 1.2 GB."""
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{max(1, n // 1024)} KB"


def _game(loc: Locations) -> str:
    return loc.game.key


# ----------------------------------------------------------------------------- recognising a download
@dataclass(frozen=True)
class Found:
    """A download the launcher can install: its folder, the overhaul's config, the build, its version."""

    folder: Path
    config: OverhaulConfig
    build: Build
    version: str

    @property
    def label(self) -> str:
        return f"{self.config.label} {self.version}".strip()


def _json_value(folder: Path, file: str, key: str):
    try:
        data = json.loads((folder / file).read_text(encoding="utf-8-sig"))
    except OSError, ValueError:
        return None
    return data.get(key) if isinstance(data, dict) else None


def find_download(folder: Path, game: str, configs: Sequence[OverhaulConfig] | None = None) -> Found:
    """The overhaul a download folder is (the folder picked, or the one folder inside it), or OverhaulError saying
    why not in plain words."""
    from roundtable_souls.mods import engine

    folder = Path(folder)
    if not folder.is_dir():
        raise OverhaulError(f"{folder} is not a folder.")
    configs = list(configs) if configs is not None else overhauls.load()
    tries = [folder, *sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name.lower())]
    newer = None
    for place in tries:
        for config, build in ((c, b) for c in configs for b in c.builds):  # by config: two may share a build id
            recipe, version, why = engine.match(place, [config.recipe(build)])
            if recipe is None:
                newer = newer or why
                continue
            if config.game != game:
                name = next((g.name for g in games.GAMES if g.key == config.game), config.game)
                raise OverhaulError(f"{config.label} is a mod for {name}; pick that game first.")
            if build.install is None:
                raise OverhaulError(
                    f"The launcher builds {config.label} but has no description of how to install this edition; "
                    "use its own installer."
                )
            # a config without a version file (one made with the Overhaul setup form) has its label
            return Found(place, config, build, version or (config.basic.version if config.basic else None) or "")
    for place in tries:  # an edition its config names as one the launcher doesn't install
        for config in configs:
            for b in config.builds:
                for c in b.match.json_:
                    value = _json_value(place, c.file, c.key)
                    if isinstance(value, str) and value in config.install_unsupported:
                        raise OverhaulError(
                            f"{config.label} {value} is not installed by the launcher: "
                            f"{config.install_unsupported[value]} Use its own installer."
                        )
    if newer:
        raise OverhaulError(
            f"{newer}, so it can't install it. Use its own installer, or a launcher with a newer config for it."
        )
    raise NotAnOverhaul(
        f"The launcher doesn't know {folder.name} as an overhaul it can install. Pick the folder you unpacked the "
        "overhaul's download into."
    )


def _needed(download: Path, build: Build, recipe: dict) -> list[str]:
    """The download's files its build reads (the files and folders its steps name, what it matches on, what its
    layout takes, licence and notice files): what the launcher keeps a copy of. Installer programs are left out."""
    from roundtable_souls.mods import engine

    all_files = sources.download_files(download)
    exact: set[str] = set(build.match.files)
    exact |= {c.file for c in build.match.json_}
    if build.match.version is not None:
        exact.add(build.match.version.file)
    globs: list[str] = []
    folders: list[str] = []
    places = {"."}  # where licence and notice files are looked for (mods.engine._notices): the top, beside its DLLs
    for step in recipe["steps"]:
        for key in ("from", "patch", "base", "fragment"):
            value = step.get(key)
            if not value:
                continue
            if step["do"] == "copy_tree" and key == "from":
                folders.append(value)
            elif "{" in value:
                globs.append(value.replace("{each}", "*"))
            else:
                exact.add(value)
        for value in (step.get("texts") or {}).values():
            exact.add(value)
        if (step.get("each") or {}).get("folders_in"):
            folders.append(step["each"]["folders_in"])
        if step["do"] == "copy" and str(step.get("to", "")).lower().endswith(".dll"):
            places.add(str(PurePosixPath(step["from"]).parent).lower())
    exact |= set(sources.translate(all_files, build).taken())
    low_exact = {e.lower() for e in exact}
    out = []
    for f in all_files:
        low = f.lower()
        if (
            low in low_exact
            or any(low.startswith(d.lower().rstrip("/") + "/") for d in folders)
            or any(fnmatch.fnmatch(low, g.lower()) for g in globs)
            or _notice(PurePosixPath(f), places, engine)
        ):
            out.append(f)
    return out


def _notice(f: PurePosixPath, places: set[str], engine) -> bool:
    """A licence or notice file the build copies next to the DLLs (a file, or a file in a licences folder), from
    the places mods.engine looks in."""
    if str(f.parent).lower() in places and engine.NOTICE_NAMES.match(f.name):
        return True
    parts = f.parts
    for i in range(len(parts) - 1):
        here = str(PurePosixPath(*parts[:i])) if i else "."
        if here.lower() in places and parts[i].lower() in engine.NOTICE_FOLDERS:
            return True
    return False


# ----------------------------------------------------------------------------- the profile edits
def _key(path: str) -> str:
    return str(path).replace("\\", "/").lower()


def _find(writer: ProfileWriter, kind: str, key: str) -> dict | None:
    """The entry an install plan's change names: a package by its id (its folder name without one), a DLL by its
    path as the profile has it."""
    for e in writer.entries():
        if e["kind"] != kind:
            continue
        if (kind == "package" and e["name"] == key) or (kind == "native" and _key(e["path"]) == _key(key)):
            return e
    return None


def _entry_named(writer: ProfileWriter, name: str) -> dict | None:
    """An entry by the name a requirement or a side effect uses: a package's id, a DLL's file name (case aside)."""
    low = name.lower()
    return next((e for e in writer.entries() if requirements.entry_name(e["kind"], e).lower() == low), None)


def _value(row: dict | None, setting: str) -> tuple[bool, Any]:
    """(present, value) of an entry's key as written; enabled is true when not written."""
    row = row or {}
    if setting == "enabled":
        return True, row.get("enabled", True)
    return setting in row, row.get(setting)


def _set_path(writer: ProfileWriter, index: int, path: str) -> None:
    import re

    b = me3_profile.blocks(writer.as_blocks())[index]
    lines = list(b["lines"])
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*path\s*=\s*).*?(\r?\n)?$", line)
        if m:
            lines[i] = f"{m.group(1)}{quote(path)}{m.group(2) or ''}"
            break
    writer.replace_block(index, lines)


def _set_entry(writer: ProfileWriter, index: int, setting: str, value, present: bool = True) -> None:
    if setting == "path":
        _set_path(writer, index, str(value))
    else:
        writer.set_options(index, {setting: value if present else None})


# ----------------------------------------------------------------------------- installing
@dataclass
class InstallPreview:
    """What installing does, worked out with nothing written. refusals: why it can't (nothing may go ahead);
    lines: what it will do, in plain words; notes: what the player should know."""

    profile: Path
    found: Found
    own: Path
    places: Places | None
    update: bool
    writer: ProfileWriter
    change: WriterPlan | None
    side_effects: list[records.SideEffect]
    files: list[str]
    size: int
    lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals

    @property
    def label(self) -> str:
        return self.found.label


def preview_install(
    profile: Path, download: Path, *, loc: Locations, configs: Sequence[OverhaulConfig] | None = None
) -> InstallPreview:
    """What installing the download into the profile would do (see the module notes). Raises OverhaulError when
    the download isn't one the launcher installs; other reasons are the preview's refusals."""
    profile = Path(profile)
    configs = list(configs) if configs is not None else overhauls.load(_game(loc))
    found = find_download(download, _game(loc), configs)
    config, build = found.config, found.build
    assert build.install is not None
    own = own_folder(profile, config)
    where = places(profile, config.id, loc)
    writer = ProfileWriter(profile)  # no Locations: the overhaul goes last by its own load order lists
    text = writer.original
    game_dir = loc.game_dir()
    plan = install_plan.plan(
        text,
        profile,
        build,
        own,
        game_dir=Path(game_dir) if game_dir else None,
        others=[c for c in configs if c.id != config.id],
    )
    out = InstallPreview(profile, found, own, where, plan.update, writer, None, [], [], 0)
    out.refusals += [p.message for p in plan.problems if p.blocks]
    out.notes += [p.message for p in plan.problems if not p.blocks]
    if installer_setup(profile, config) is not None:
        out.refusals.append(
            f"{config.label} in {profile.parent.name} was installed by its own installer, and the launcher doesn't "
            f"take over a setup it didn't make yet. Remove it first with Remove {config.short_label} (your other "
            "mods stay), then install it with the launcher."
        )
    elif own.exists() and not installed_by_launcher(profile, config):
        out.refusals.append(
            f"There is already a folder named {own.name} beside {profile.name} that the launcher didn't make. Move "
            "it somewhere else first."
        )
    if not game_dir or not Path(game_dir).is_dir():
        out.refusals.append("The game folder was not found, and the launcher builds the overhaul from its files.")
    if where is None:
        out.refusals.append(
            "me3's profiles folder was not found on this PC, and the launcher keeps an overhaul's files in its "
            "folder there. Set it under Settings > Locations."
        )
    if out.refusals:
        return out
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        out.refusals.append(f"{profile.name} could not be read: {e}")
        return out
    out.side_effects = _apply(writer, plan, before)
    out.change = writer.plan(f"before installing {config.label}")
    out.refusals += [r.message for r in out.change.refusals]
    out.files = _needed(found.folder, build, config.recipe(build))
    out.size = sum((found.folder / f).stat().st_size for f in out.files)
    assert where is not None
    out.lines = _install_lines(out, plan)
    return out


def _apply(writer: ProfileWriter, plan: install_plan.Plan, before: dict) -> list[records.SideEffect]:
    """Make the plan's changes through the writer (in memory) and return the side effects: what it changes outside
    the overhaul's own entries."""
    effects: list[records.SideEffect] = []
    removes = [c for c in plan.changes if c.action == "remove"]
    found = [_find(writer, c.kind, c.key) for c in removes]
    for e in sorted((e for e in found if e is not None), key=lambda e: e["index"], reverse=True):
        writer.remove_entry(e["index"])
    for c in plan.changes:
        if c.action == "set":
            for k, v in c.values.items():
                effects.append(records.SideEffect(setting=k, before=before.get(k), before_set=k in before, after=v))
                writer.set_setting(k, v)
        elif c.action == "update":
            e = _find(writer, c.kind, c.key)
            if e is None:
                continue
            name = requirements.entry_name(e["kind"], e)
            for k, v in c.values.items():
                present, was = _value(e["row"], k)
                value = _relative(writer.profile, str(v)) if k == "path" else v
                effects.append(records.SideEffect(entry=name, setting=k, before=was, before_set=present, after=value))
                _set_entry(writer, e["index"], k, value)
                e = _entry_named(writer, name) or e
        elif c.action == "add":
            row = dict(c.values)
            writer.add_entry(c.kind, row)
            if c.why not in ("the overhaul's DLL", "the overhaul's package"):  # a required mod, not its own
                name = requirements.entry_name(c.kind, row)
                effects.append(
                    records.SideEffect(entry=name, setting="added", before=None, before_set=False, after=True)
                )
    return effects


def _relative(profile: Path, path: str) -> str:
    """A path the launcher writes into the profile: relative to it when it is below the profile's folder."""
    from roundtable_souls.mods.profile_edit import rel

    p = Path(path)
    return rel(profile, p) if p.is_absolute() else str(path).replace("\\", "/")


def _shown(value) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, dict) and value.get("function"):
        return value["function"]
    return str(value)


def _effect_line(e: records.SideEffect) -> str:
    if e.setting == "added":
        return f"{e.entry} is added to the profile: it is needed and wasn't there"
    what = f"{e.entry}'s {e.setting}" if e.entry else e.setting
    was = _shown(e.before) if e.before_set else "not set"
    return f"{what}: {was} becomes {_shown(e.after)} (put back when you remove it, if you haven't changed it)"


def choice_text(e: records.SideEffect) -> str:
    """A change an overhaul's own installer made, as a choice to put back (legacy_effects)."""
    what = f"{e.entry}'s {e.setting}" if e.entry else e.setting
    was = _shown(e.before) if e.before_set else "not set"
    return f"{what}: back to {was} (its installer made it {_shown(e.after)})"


def _install_lines(p: InstallPreview, plan: install_plan.Plan) -> list[str]:
    cfg = p.found.config
    assert p.places is not None
    out = []
    if p.update:
        out.append(
            f"{cfg.label} already in {p.profile.name} is replaced by {p.label}; the version there now is kept, "
            "so Undo can put it back"
        )
    where = os.path.join(p.places.library.root.name, "builds", p.places.sources.parent.name, p.places.sources.name)
    out.append(
        f"A copy of the {len(p.files)} files its build needs ({size_text(p.size)}) is kept in the launcher's "
        f"folder ({where}); the folder you picked isn't needed afterwards"
    )
    kept = ", ".join(_kept_settings(p.found.build))
    out.append(
        f"The launcher builds {cfg.label} into {p.own.name} from the {len(_packages_before(p))} enabled package(s) "
        f"before it{f', keeping your {kept}' if kept else ''}; nothing of the mod's runs"
    )
    removes = [c for c in plan.changes if c.action == "remove"]
    if removes:
        out.append(f"Its earlier entries in {p.profile.name} ({len(removes)}) are replaced")
    adds = [c for c in plan.changes if c.action == "add"]
    names = ", ".join(
        PurePosixPath(str(c.values.get("path", ""))).name if c.kind == "native" else str(c.values.get("id"))
        for c in adds
    )
    out.append(f"{p.profile.name} gets its entries, loading after your mods: {names}")
    out += [_effect_line(e) for e in p.side_effects]
    return out


def _kept_settings(build: Build) -> list[str]:
    return [s.to for s in build.steps if s.do == "config"]


def _packages_before(p: InstallPreview) -> list[dict]:
    assert p.change is not None
    return [
        e for e in p.change.entries() if e["kind"] == "package" and e["enabled"] and not _inside(p.profile, e, p.own)
    ]


def _inside(profile: Path, entry: dict, folder: Path) -> bool:
    if not entry.get("path"):
        return False
    where = os.path.normcase(os.path.abspath(me3_profile.resolve(profile, entry["path"])))
    top = os.path.normcase(os.path.abspath(folder))
    return where == top or where.startswith(top + os.sep)


def _now() -> str:
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _expect(path: Path) -> str:
    """What Operation.write_file expects to find: the file's sha256 now, or missing."""
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "missing"


def install(
    preview: InstallPreview, *, loc: Locations, log=lambda s: None, config_file: tuple[Path, bytes] | None = None
) -> dict:
    """Install as previewed, as one operation (see the module notes). config_file: the overhaul's config, written
    to this file in the same operation (a setup made with the form), so an undo takes it back too. Returns
    {operation, update, name}; raises OverhaulError (refused, nothing written) or the error that stopped it (the
    previous state is back)."""
    from roundtable_souls import __version__
    from roundtable_souls.mods import engine

    p = preview
    if not p.ok or p.change is None or p.places is None:
        raise OverhaulError("; ".join(p.refusals) or "Nothing to install.")
    profile, cfg, build, where = p.profile, p.found.config, p.found.build, p.places
    recipe = cfg.recipe(build)
    with operations.lock(profile):
        operations.recover(profile)
        op = operations.start(profile, f"{'update' if p.update else 'install'} of {cfg.label}")
        temp = profile.with_name(f".{profile.name}.installing-{op.id}")
        built: Path | None = None
        try:
            lib = where.library
            lib.ensure(where.sources.parent, where.record.parent, where.effects.parent)
            # the download copy: the files its build reads, at their download paths, with where each came from
            staged = where.sources.with_name(f".{where.sources.name}.staging-{op.id}")
            rows = {}
            for rel in p.files:
                (staged / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p.found.folder / rel, staged / rel)
                rows[rel] = records.SourceFile(**{"from": rel, "sha256": _sha(staged / rel)})
            (staged / library.RECORD).write_text(
                records.SourcesRecord(files=rows).text(), encoding="utf-8", newline="\n"
            )
            op.replace_folder(where.sources, staged)
            # the build, against the profile as the install leaves it, staged beside the overhaul's folder
            temp.write_text(p.change.text, encoding="utf-8", newline="")
            result = engine.build(
                temp, p.own / build.output.mod, staged, recipe, p.found.version, log, loc=loc, swap=False
            )
            built = Path(result["output"])
            _own_manifest(built / build.output.manifest, profile, temp, p, __version__)
            op.replace_folder(p.own, built)
            # the profile (the first file the operation writes: what an undo puts back), then the records
            p.writer.commit(p.change, operation=op)
            record = records.OverhaulRecord.model_validate(
                {
                    "build": build.id,
                    "fingerprint": sources.fingerprint(p.found.folder, build),
                    "installed": _now(),
                    "from": str(p.found.folder),
                }
            )
            op.write_file(where.record, record.text().encode("utf-8"), expect=_expect(where.record))
            effects = records.SideEffectsRecord(changes=p.side_effects)
            op.write_file(where.effects, effects.text().encode("utf-8"), expect=_expect(where.effects))
            if config_file is not None:
                config_file[0].parent.mkdir(parents=True, exist_ok=True)
                op.write_file(config_file[0], config_file[1], expect=_expect(config_file[0]))
            op.note(
                kind="overhaul-update" if p.update else "overhaul-install",
                name=cfg.label,
                overhaul=cfg.id,
                dest=str(p.own),
                made={str(p.own): operations.manifest(built), str(where.sources): operations.manifest(staged)},
                entries=[c.path for c in p.change.changes if c.action == "add" and c.path],
            )
        except BaseException:
            op.discard()
            if built is not None:
                shutil.rmtree(built, ignore_errors=True)
            raise
        finally:
            temp.unlink(missing_ok=True)
        operations.commit(op)
    log(f"overhaul: {'updated' if p.update else 'installed'} {p.label} in {profile.name} ({p.own})")
    return {"operation": str(op.dir), "update": p.update, "name": cfg.label}


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _own_manifest(path: Path, profile: Path, temp: Path, p: InstallPreview, version: str) -> None:
    """The build's manifest as a launcher install keeps it: its download copy (where it will be) is its setup, the
    real profile (the build was made against a copy of its new text), who installed it; the installer's own state
    keys are left out."""
    assert p.change is not None and p.places is not None
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in _INSTALLER_KEYS:
        data.pop(key, None)
    data["maintenance"] = str(p.places.sources)
    data["profile"] = str(profile)
    data[INSTALLED_BY] = f"Roundtable Souls {version}"
    sha = hashlib.sha256(p.change.text.encode("utf-8")).hexdigest()
    for row in data.get("sources") or []:
        if isinstance(row, dict) and str(row.get("path")) == str(temp):
            row["path"], row["sha256"] = str(profile), sha
    path.write_text(json.dumps(data, indent=2), encoding="utf-8", newline="\n")


# ----------------------------------------------------------------------------- what a profile has
def overhaul_in(profile: Path, configs: Sequence[OverhaulConfig]) -> tuple[OverhaulConfig, list[dict]] | None:
    """The overhaul whose entries the profile has (the first), with those entries; None without one."""
    try:
        entries = me3_profile.entries(me3_profile.read_text(Path(profile)))
    except OSError, ValueError:
        return None
    owned = requirements.owned_by(configs, entries)
    for config in configs:
        if config.id in owned:
            return config, owned[config.id]
    return None


def _users(profile: Path, config: OverhaulConfig, own: Path, *, others: bool = True) -> list[Path]:
    """The profiles beside this one (others: not counting it) whose entries point into the overhaul's folder."""
    out = []
    for other in sorted(Path(profile).parent.glob("*.me3")):
        if others and other.name.lower() == Path(profile).name.lower():
            continue
        try:
            entries = me3_profile.entries(me3_profile.read_text(other))
        except OSError, ValueError:
            continue
        mine = requirements.owned_by([config], entries).get(config.id, [])
        if any(_inside(other, e, own) for e in mine):
            out.append(other)
    return out


def users_of(profile: Path, config: OverhaulConfig, entries: list[dict]) -> list[Path]:
    """Every profile whose entries use this overhaul's folder: the profile itself first, then the ones beside it."""
    return [Path(profile), *_users(profile, config, _own_of(profile, config, entries))]


def _own_of(profile: Path, config: OverhaulConfig, entries: list[dict]) -> Path:
    """The overhaul's folder its package entry points into (its package folder's parent), else the usual place."""
    for b in config.builds:
        if b.install is None or b.install.package is None:
            continue
        for e in entries:
            if e["kind"] == "package" and e.get("path") and requirements.owns(b.install, "package", e):
                where = me3_profile.resolve(profile, e["path"])
                for _part in PurePosixPath(b.install.package.folder).parts:
                    where = where.parent
                return where
    return own_folder(profile, config)


def _coop_dlls() -> set[str]:
    return {g.coop_dll.lower() for g in games.GAMES if g.coop_dll}


# ----------------------------------------------------------------------------- removing
@dataclass
class RemovePreview:
    """What Remove overhaul does, worked out with nothing written."""

    profile: Path
    config: OverhaulConfig
    own: Path
    places: Places | None
    legacy: bool
    writer: ProfileWriter
    change: WriterPlan | None
    removed: list[str]
    reverted: list[records.SideEffect]
    left: list[str]  # side effects left, each with why
    asked: list[records.SideEffect]  # reverting these switches a shared dependency back off: asked first
    trash: list[Path]  # folders going to the Recycle Bin, the overhaul's folder last
    users: list[Path]  # other profiles still using it (then its folders stay)
    delete_files: list[Path]  # launcher files removed with it (this profile's side-effects record, say)
    revert_asked: bool = False
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals


def preview_remove(
    profile: Path,
    *,
    loc: Locations,
    revert_asked: bool = False,
    legacy_choices: Sequence[records.SideEffect] = (),
    configs: Sequence[OverhaulConfig] | None = None,
) -> RemovePreview:
    """What removing the profile's overhaul would do. revert_asked: switch a shared dependency back off where the
    install switched it on. legacy_choices: for a setup its own installer made, the side effects (legacy_effects)
    the player chose to put back. Raises OverhaulError when the profile has no overhaul."""
    profile = Path(profile)
    configs = list(configs) if configs is not None else overhauls.load(_game(loc))
    hit = overhaul_in(profile, configs)
    if hit is None:
        raise OverhaulError(f"{profile.name} has no overhaul the launcher knows.")
    config, owned = hit
    own = _own_of(profile, config, owned)
    where = places(profile, config.id, loc)
    effects_file = where.effects if where is not None else None
    if own.exists() and same_folder(own, own_folder(profile, config)):
        legacy = installer_setup(profile, config) is not None
    else:  # its folder is gone, or elsewhere: a launcher install leaves its record
        legacy = effects_file is None or not effects_file.is_file()
    writer = ProfileWriter(profile)
    removed = []
    for e in sorted(owned, key=lambda e: e["index"], reverse=True):
        writer.remove_entry(e["index"])
        removed.insert(0, e["name"])
    effects: list[records.SideEffect] = list(legacy_choices)
    if not legacy and effects_file is not None and effects_file.is_file():
        try:
            effects = list(records.SideEffectsRecord.load(effects_file).changes)
        except records.RecordError:
            effects = []
    out = RemovePreview(
        profile, config, own, where, legacy, writer, None, removed, [], [], [], [], [], [], revert_asked=revert_asked
    )
    try:
        top = tomllib.loads(writer.text)
    except tomllib.TOMLDecodeError as e:
        out.refusals.append(f"{profile.name} could not be read: {e}")
        return out
    for eff in effects:
        _revert(out, eff, top)
    out.change = writer.plan(f"before removing {config.label}")
    out.refusals += [r.message for r in out.change.refusals]
    out.users = _users(profile, config, own)
    if effects_file is not None and effects_file.is_file():
        out.delete_files.append(effects_file)
    if where is not None and not legacy:
        # its download copy and its record go too
        if where.sources.is_dir():
            out.trash.append(where.sources)
        if where.record.is_file():
            out.delete_files.append(where.record)
    if not out.users:
        built = _engine_previous(profile, own)
        if built is not None:
            out.trash.append(built)
            out.delete_files.append(built.parent / "restore.json")
        if own.exists() and not any(p.name.lower() in _coop_dlls() for p in own.rglob("*.dll")):
            out.trash.append(own)  # last: once it is gone the removal counts as done
    out.lines = _remove_lines(out)
    return out


def _engine_previous(profile: Path, own: Path) -> Path | None:
    """The launcher's previous build of the overhaul kept for Undo rebuild (mods.engine), when it is this one's."""
    from roundtable_souls.mods import engine

    work = Path(profile).parent / engine.WORK
    try:
        data = json.loads((work / "restore.json").read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    rows = data.get("directories") if isinstance(data, dict) else None
    for row in rows or []:
        if isinstance(row, dict) and os.path.normcase(str(row.get("path"))) == os.path.normcase(str(own)):
            prev = Path(str(row.get("original")))
            return prev if prev.exists() else None
    return None


def _revert(out: RemovePreview, eff: records.SideEffect, top: dict) -> None:
    w = out.writer
    if eff.setting == "added":
        out.left.append(
            f"{eff.entry} stays in the profile: it was added for {out.config.label}, and other mods may use it"
        )
        return
    if eff.entry is None:
        present, now = eff.setting in top, top.get(eff.setting)
        if present and now == eff.after:
            w.set_setting(eff.setting, eff.before if eff.before_set else None)
            out.reverted.append(eff)
        else:
            out.left.append(
                f"{eff.setting} stays {_shown(now) if present else 'not set'}: you changed it after the install"
            )
        return
    e = _entry_named(w, eff.entry)
    if e is None:
        out.left.append(f"{eff.entry} is no longer in the profile, so its {eff.setting} isn't put back")
        return
    present, now = _value(e["row"], eff.setting)
    if not (present and now == eff.after):
        out.left.append(
            f"{eff.entry}'s {eff.setting} stays {_shown(now) if present else 'not set'}: you changed it after the install"
        )
        return
    shared = e["kind"] == "native" and Path(e["path"]).name.lower() in _coop_dlls()
    if shared and eff.setting == "enabled" and not out.revert_asked:
        out.asked.append(eff)
        return
    _set_entry(w, e["index"], eff.setting, eff.before, eff.before_set)
    out.reverted.append(eff)


def _remove_lines(r: RemovePreview) -> list[str]:
    cfg = r.config
    out = [f"{r.profile.name} loses {cfg.label}'s entries: {', '.join(r.removed)}"]
    for e in r.reverted:
        what = f"{e.entry}'s {e.setting}" if e.entry else e.setting
        out.append(f"{what} goes back to {_shown(e.before) if e.before_set else 'not set'}, as before the install")
    out += r.left
    for e in r.asked:
        out.append(f"{e.entry} stays switched on unless you choose to switch it back off (other mods may need it)")
    if r.users:
        names = ", ".join(u.name for u in r.users)
        out.append(f"Its folder {r.own.name} stays: {names} still use{'s' if len(r.users) == 1 else ''} it")
    for t in r.trash:
        size = size_text(size_of(t))
        if r.places is not None and same_folder(t, r.places.sources):
            out.append(f"The launcher's copy of its download ({size}) goes to the Recycle Bin")
        elif same_folder(t, r.own):
            out.append(
                f"Its folder {t.name}, with its build and your settings for it ({size}), goes to the Recycle Bin"
            )
        else:
            out.append(f"Its previous build, kept for Undo rebuild ({size}), goes to the Recycle Bin")
    out.append("Seamless Co-op and your other mods are not touched")
    return out


def _tidy(where: Places | None) -> None:
    """Folders of the launcher's that a removal left empty go, up to the library itself (builds/<id>/<profile>,
    overhauls/<id>, sources/<id>, then builds/, overhauls/, sources/ when nothing else is in them)."""
    if where is None:
        return
    for folder in (where.effects.parent, where.record.parent, where.sources):
        where.library.prune(folder)


def remove(preview: RemovePreview, *, log=lambda s: None) -> dict:
    """Remove as previewed, as one operation: the profile (and the launcher's records) change first, then the
    folders go to the Recycle Bin, the overhaul's folder last; an interruption before that is undone, one after it
    is finished. Returns the undo record's facts: {operation, trash, name, kept}."""
    r = preview
    if not r.ok or r.change is None:
        raise OverhaulError("; ".join(r.refusals) or "Nothing to remove.")
    profile = r.profile
    gone: list[dict] = []
    kept: list[str] = []
    with operations.lock(profile):
        operations.recover(profile)
        op = operations.start(profile, f"removal of {r.config.label}")
        try:
            r.writer.commit(r.change, operation=op)
            for f in r.delete_files:
                op.write_file(f, None)
            op.note(kind="overhaul-remove", name=r.config.label, overhaul=r.config.id, dest=str(r.own))
            if r.trash:
                op.gone_when(r.trash[-1])
        except BaseException:
            op.discard()
            raise

        operations.commit(op, lambda: _to_bin(r.trash, op.id, gone, kept))
        _tidy(r.places)
    for name in kept:
        log(f"warning: {name} stayed (the Recycle Bin did not take it)")
    log(f"overhaul: removed {r.config.label} from {profile.name}")
    return {"operation": str(op.dir), "trash": gone, "name": r.config.label, "kept": kept}


def _to_bin(folders: Sequence[Path], op_id: str, gone: list[dict], kept: list[str]) -> None:
    """Send folders to the Recycle Bin (deleted where there is none), the last one last; gone gets each bin record,
    kept the names of those that stayed."""
    for folder in folders:
        try:
            if trash.available():
                gone.append(trash.send(folder))
            else:
                aside = folder.with_name(f".{folder.name}.removing-{op_id}")
                os.replace(folder, aside)
                shutil.rmtree(aside, ignore_errors=True)
        except trash.TrashError:
            kept.append(folder.name)  # cancelled at Windows' warning, or no bin: it stays


def undo_remove(undo: dict, log=lambda s: None) -> str:
    """Put a removal back: the profile's exact bytes from before it (only when it hasn't changed since), the
    launcher's files it removed, and the folders from the Recycle Bin."""
    from roundtable_souls.merging import build

    op = build.Operation.load(Path(undo["operation"]))
    profile = Path(op.info["profile"])
    name = op.info.get("name") or "the overhaul"
    steps = [s for s in op.steps if s["type"] == "file"]
    folders = [s for s in op.steps if s["type"] == "folder"]  # Turn off's ordinary copy of the mod
    made = op.info.get("made") or {}
    emptied: list[Path] = []
    prof = next((s for s in steps if Path(s["live"]) == profile), None)
    if prof is not None and profile.read_bytes() != (op.dir / prof["after"]).read_bytes():
        raise OverhaulError(
            f"{profile.name} changed since {name} was removed, so it can't be put back as it was. Install it again "
            "instead."
        )
    for record in undo.get("trash") or []:
        if not trash.exists(record):
            raise OverhaulError(f"{Path(str(record.get('original'))).name} is no longer in the Recycle Bin.")
    with operations.lock(profile):
        new = operations.start(profile, f"undo of the removal of {name}")
        try:
            for s in steps:
                live = Path(s["live"])
                live.parent.mkdir(parents=True, exist_ok=True)  # a launcher folder the removal left empty went
                if s["before"]:
                    now = live.read_bytes() if live.is_file() else None
                    expect = hashlib.sha256(now).hexdigest() if now is not None else "missing"
                    new.write_file(live, (op.dir / s["before"]).read_bytes(), expect=expect)
                else:
                    new.write_file(live, None)
            for s in folders:
                live, previous = Path(s["live"]), Path(s["previous"]) if s["previous"] else None
                if previous is not None and previous.is_dir():
                    new.replace_folder(live, previous)
                elif live.is_dir():  # it made the folder: it goes, except files changed or added since
                    created = made.get(str(live)) or {}
                    staged = live.with_name(f".{live.name}.staging-{new.id}")
                    staged.mkdir()
                    for rel, rec in operations.manifest(live).items():
                        if created.get(rel) != rec:
                            (staged / rel).parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(live / rel, staged / rel)
                    new.replace_folder(live, staged)
                    emptied.append(live)
        except BaseException:
            new.discard()
            raise
        back: list[str] = []

        def bring_back() -> None:
            for record in reversed(undo.get("trash") or []):
                back.append(str(trash.restore(record)))

        new.commit(then=bring_back)
        new.release()
        for folder in emptied:
            if folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
        op.release()
    log(
        f"undo: {name} is back in {profile.name}"
        + (f" with {len(back)} folder(s) from the Recycle Bin" if back else "")
    )
    return f"put {name} back in {profile.name}"


# ----------------------------------------------------------------------------- what an overhaul's installer left
@dataclass(frozen=True)
class Leftover:
    path: Path
    size: int
    backups: bool  # its installer's backups of the profile: the only copy from before it; offered apart

    @property
    def label(self) -> str:
        return f"{self.path.name} ({size_text(self.size)})"


def leftovers(profile: Path, *, loc: Locations, configs: Sequence[OverhaulConfig] | None = None) -> list[Leftover]:
    """What the game's overhauls' own installers left beside the profile that no profile there uses any more: their
    folder (when no profile's entries point into it), the folders they keep (installer_folders), and their backups
    (installer_backups), last."""
    profile = Path(profile)
    configs = list(configs) if configs is not None else overhauls.load(_game(loc))
    out: list[Leftover] = []
    backups: list[Leftover] = []
    for config in configs:
        own = installer_setup(profile, config)
        users = _users(profile, config, own_folder(profile, config), others=False)
        if users:
            continue  # still in use by a profile here
        if own is not None:
            out.append(Leftover(own, size_of(own), False))
        for name in config.recognise.installer_folders:
            p = profile.parent / name
            if p.is_dir():
                out.append(Leftover(p, size_of(p), False))
        if config.recognise.installer_backups:
            p = profile.parent / config.recognise.installer_backups
            if p.is_dir():
                backups.append(Leftover(p, size_of(p), True))
    return out + backups


def remove_leftovers(paths: Sequence[Path], log=lambda s: None) -> list[dict]:
    """Send these to the Recycle Bin (what leftovers() listed and the player chose). Returns the bin's records."""
    out = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        out.append(trash.send(p))
        log(f"overhaul: {p} moved to the Recycle Bin")
    return out


def legacy_effects(
    profile: Path, *, loc: Locations, configs: Sequence[OverhaulConfig] | None = None
) -> list[records.SideEffect]:
    """For a setup an overhaul's own installer made: what it changed outside its own entries, worked out by
    comparing the profile with the installer's oldest backup of it (the settings its install sets, the
    initializers it gives other mods' DLLs) where the profile still has the value the install sets. Each is offered
    to choose from; none is put back unless chosen. Empty when there is no backup to compare with."""
    profile = Path(profile)
    configs = list(configs) if configs is not None else overhauls.load(_game(loc))
    hit = overhaul_in(profile, configs)
    if hit is None or not hit[0].recognise.installer_backups:
        return []
    config = hit[0]
    old = _oldest_backup(profile, profile.parent / str(config.recognise.installer_backups))
    if old is None:
        return []
    try:
        before = tomllib.loads(old)
        now = tomllib.loads(me3_profile.read_text(profile))
    except tomllib.TOMLDecodeError, OSError:
        return []
    out: list[records.SideEffect] = []
    seen: set[tuple[str | None, str]] = set()
    for b in config.builds:
        if b.install is None:
            continue
        for key, value in b.install.profile_settings.items():
            if now.get(key) == value and before.get(key) != value and (None, key) not in seen:
                seen.add((None, key))
                out.append(
                    records.SideEffect(setting=key, before=before.get(key), before_set=key in before, after=value)
                )
        for rule in b.install.set_initializers:
            was = {install_plan.dll_name(n): n for n in install_plan.rows(before, "natives")}
            for n in install_plan.rows(now, "natives"):
                name = install_plan.dll_name(n)
                if not name.startswith(rule.name_prefix.lower()) or (name, "initializer") in seen:
                    continue
                old_row = was.get(name)
                if (
                    n.get("initializer") == {"function": rule.function}
                    and old_row is not None
                    and "initializer" not in old_row
                ):
                    seen.add((name, "initializer"))
                    out.append(
                        records.SideEffect(
                            entry=Path(str(n.get("path"))).name, setting="initializer", before=None, before_set=False,
                            after={"function": rule.function},
                        )
                    )  # fmt: skip
    return out


def _oldest_backup(profile: Path, folder: Path) -> str | None:
    """The profile's text in the oldest of an installer's backups (each a folder with a restore.json listing the
    files it kept: {path, original})."""
    if not folder.is_dir():
        return None
    for sub in sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name):
        try:
            data = json.loads((sub / "restore.json").read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        for row in data.get("files") or [] if isinstance(data, dict) else []:
            if not isinstance(row, dict) or not row.get("original"):
                continue
            if os.path.normcase(os.path.abspath(str(row.get("path")))) == os.path.normcase(os.path.abspath(profile)):
                try:
                    return (sub / str(row["original"])).read_bytes().decode("utf-8", errors="replace")
                except OSError:
                    return None
    return None


# ----------------------------------------------------------------------------- the Overhaul setup form
def setup_config(config: OverhaulConfig, folder: Path) -> OverhaulConfig:
    """The config the form's values give for the mod's folder: at the basic level derived again from its files (so
    the steps follow the form), at the advanced level as it is."""
    if config.basic is None:
        return config
    return overhauls.basic.make(
        id=config.id,
        label=config.label,
        game=config.game,
        basic=config.basic,
        folder=folder,
        short_label=config.short_label,
    )


def config_path(config: OverhaulConfig) -> Path | None:
    """Where the config is written: the local file it was loaded from, else <id>.toml in the local folder (None
    before the launcher's data folder is set). Call after overhauls.load()."""
    found = overhauls.origin(config.id)
    if found is not None and not overhauls.verified(config.id):
        return found
    folder = overhauls.local_dir()
    return folder / f"{config.id}.toml" if folder is not None else None


def preview_setup(profile: Path, folder: Path, config: OverhaulConfig, *, loc: Locations) -> InstallPreview:
    """What installing the mod in folder as an overhaul with this config (the Overhaul setup form's) would do, the
    config written to the launcher's local overhauls folder in the same operation. folder: an unpacked download,
    or an installed mod's folder (its entries, when the config owns them, are replaced as an update). Raises
    OverhaulError when it can't be set up."""
    from roundtable_souls.overhauls import writer

    configs = overhauls.load(_game(loc))
    if config.basic is not None and overhauls.verified(config.id):
        raise OverhaulError(f"{config.label} already has a verified setup that comes with the launcher.")
    try:
        made = setup_config(config, Path(folder))
        writer.render(made)
    except ValueError as e:
        raise OverhaulError(str(e)) from e
    path = config_path(made)
    if path is None:
        raise OverhaulError("The launcher's data folder is not set.")
    # its own config first: a folder another config also fits is still the one the player set up
    out = preview_install(profile, folder, loc=loc, configs=[made, *(c for c in configs if c.id != made.id)])
    if path.is_file():
        out.notes.append(f"Your profile in {path.name} is replaced by this one (Undo puts the old one back).")
    return out


def install_setup(preview: InstallPreview, *, loc: Locations, log=lambda s: None) -> dict:
    """Install as previewed (preview_setup), its config written in the same operation."""
    from roundtable_souls.overhauls import writer

    config = preview.found.config
    path = config_path(config)
    if path is None:
        raise OverhaulError("The launcher's data folder is not set.")
    return install(preview, loc=loc, log=log, config_file=(path, writer.render(config).encode("utf-8")))


@dataclass
class TurnOffPreview:
    """What Turn off does: Remove overhaul's changes, then the launcher's copy of its download installed as an
    ordinary mod, and its config kept aside as <file>.off; all one operation (Undo turn off)."""

    remove: RemovePreview
    config_file: Path | None
    plain: dict  # the ordinary install's plan (mods.install)
    reuse: bool  # its ordinary folder is already there with the same files: listed again, not copied
    lines: list[str] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.refusals


def _same_files(folder: Path, sources: Path) -> bool:
    """folder holds exactly the download copy's files (its record left out), byte for byte."""
    want = [rel for rel in operations.manifest(sources) if rel != library.RECORD]
    have = operations.manifest(folder)
    return set(want) == set(have) and all(_sha(folder / rel) == _sha(sources / rel) for rel in want)


def preview_turn_off(profile: Path, *, loc: Locations) -> TurnOffPreview:
    """What turning the profile's overhaul setup off would do (the mod made ordinary again). Raises OverhaulError
    when the profile has no overhaul."""
    from roundtable_souls.mods import install as mod_install

    configs = overhauls.load(_game(loc))
    r = preview_remove(profile, loc=loc, configs=configs)
    cfg = r.config
    path = overhauls.origin(cfg.id)
    out = TurnOffPreview(r, path, {}, False, refusals=list(r.refusals))
    if path is None or overhauls.verified(cfg.id):
        out.refusals.append(f"{cfg.label} comes with the launcher's own setup; use Remove {cfg.short_label} instead.")
    if r.legacy or r.places is None or not r.places.sources.is_dir():
        out.refusals.append(
            f"The launcher's copy of {cfg.label}'s download is gone, so it can't become an ordinary mod again. "
            f"Remove {cfg.short_label} instead."
        )
    if out.refusals:
        return out
    assert r.places is not None and path is not None
    plan = mod_install.plan_install(Path(profile), r.places.sources, name=cfg.id, pkg_id=cfg.id, loc=loc)
    plan["exclude"] = [library.RECORD]
    out.plain = plan
    if plan.get("error"):
        out.refusals.append(plan["error"])
        return out
    dest = Path(plan["dest"])
    if dest.exists():
        if not _same_files(dest, r.places.sources):
            out.refusals.append(
                f"There is already a folder {dest.name} in {dest.parent}. Move it somewhere else first."
            )
            return out
        out.reuse = True
    deepest = max((len(rel) for rel in operations.manifest(r.places.sources)), default=0)
    for e in plan["entries"]:
        r.writer.add_entry(e["kind"], e, deepest=deepest)
    r.change = r.writer.plan(f"before turning {cfg.label} off")
    out.refusals += [x.message for x in r.change.refusals]
    keep = [line for line in r.lines if not line.startswith("Seamless Co-op")]
    out.lines = [
        *keep,
        f"{cfg.label} goes back into {Path(profile).name} as an ordinary mod"
        + (f", from {dest.name}, which is already there" if out.reuse else f", copied into {dest}"),
        f"Its setup {path.name} is kept as {path.name}.off, so it can be set up again",
        "Seamless Co-op and your other mods are not touched",
    ]
    return out


def turn_off(preview: TurnOffPreview, *, log=lambda s: None) -> dict:
    """Turn the setup off as previewed, as one operation. Returns {operation, trash, name, kept}."""
    from roundtable_souls.mods import install as mod_install

    t, r = preview, preview.remove
    if not t.ok or r.change is None or t.config_file is None:
        raise OverhaulError("; ".join(t.refusals) or "Nothing to turn off.")
    profile, path = r.profile, t.config_file
    gone: list[dict] = []
    kept: list[str] = []
    made: dict = {}
    with operations.lock(profile):
        operations.recover(profile)
        op = operations.start(profile, f"turning off {r.config.label}")
        try:
            if not t.reuse:  # the ordinary copy, staged before anything goes
                dest = Path(t.plain["dest"])
                staged = dest.with_name(f".{dest.name}.staging-{op.id}")
                mod_install._copy_into(t.plain, staged)
                made[str(dest)] = operations.manifest(staged)
                op.replace_folder(dest, staged)
            r.writer.commit(r.change, operation=op)
            for f in r.delete_files:
                op.write_file(f, None)
            off = path.with_name(path.name + ".off")
            op.write_file(off, path.read_bytes(), expect=_expect(off))
            op.write_file(path, None, expect=_expect(path))
            op.note(kind="overhaul-turn-off", name=r.config.label, overhaul=r.config.id, dest=str(r.own), made=made)
            if r.trash:
                op.gone_when(r.trash[-1])
        except BaseException:
            op.discard()
            raise
        operations.commit(op, lambda: _to_bin(r.trash, op.id, gone, kept))
        _tidy(r.places)
    for name in kept:
        log(f"warning: {name} stayed (the Recycle Bin did not take it)")
    log(f"overhaul: turned {r.config.label} off in {profile.name}; it is an ordinary mod again")
    return {"operation": str(op.dir), "trash": gone, "name": r.config.label, "kept": kept}
