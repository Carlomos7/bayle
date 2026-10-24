"""Taking over an overhaul its own installer set up: the profile loses the installer's entries (packages, natives,
and the load order lists on them), the settings the player chose to put back go back, and the installer's folders go
to the Recycle Bin, all as one undoable operation (overhaul_install.remove). The overhaul is then installed again
through the launcher by the player (nothing installs here). The player's own mod folders are never touched: only the
overhaul's folder, its installer's setup copy and, when chosen, its installer's backups go."""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from bayle.formats import me3_profile
from bayle.mods import installer_leftovers, overhaul_install, records
from bayle.mods.checks import same_folder
from bayle.mods.overhaul_install import Leftover, OverhaulError, RemovePreview, size_of, size_text
from bayle.mods.profile_writer import ProfileWriter
from bayle.overhauls import recipes
from bayle.overhauls.config import OverhaulConfig, Recognise

if TYPE_CHECKING:
    from bayle.game.locate import Locations


def _config_choices(profile: Path, *, loc: Locations) -> list[records.SideEffect | Leftover]:
    """What the player may also choose: each setting the installer changed (put back), then its backups folder
    (move to the Recycle Bin too). Nothing is chosen by default."""
    out: list[records.SideEffect | Leftover] = list(overhaul_install.legacy_effects(profile, loc=loc))
    out += [f for f in _installer_folders(Path(profile), loc=loc) if f.backups]
    return out


def _installer_folders(
    profile: Path, *, loc: Locations, configs: Sequence[OverhaulConfig] | None = None
) -> list[Leftover]:
    """The installer's setup copy and backups beside the profile (named by the config and the manifest), that no
    profile uses."""
    configs = list(configs) if configs is not None else recipes.load(loc.game.key)
    hit = overhaul_install.overhaul_in(profile, configs)
    if hit is None:
        return []
    config, base = hit[0], profile.parent
    names = list(config.recognise.installer_folders)
    try:
        data = json.loads(
            overhaul_install.own_folder(profile, config).joinpath(config.recognise.manifest).read_text("utf-8")
        )
        setup = data.get(installer_leftovers.rules().get("manifest_setup_key", ""))
        if isinstance(setup, str) and Path(setup).parent == base:
            names.append(Path(setup).name)
    except OSError, ValueError, AttributeError:
        pass
    out = [Leftover(base / n, size_of(base / n), False) for n in dict.fromkeys(names) if (base / n).is_dir()]
    if config.recognise.installer_backups and (base / config.recognise.installer_backups).is_dir():
        b = base / config.recognise.installer_backups
        out.append(Leftover(b, size_of(b), True))
    return [x for x in out if not installer_leftovers.used(base, x.path)]


def _config_preview(
    profile: Path,
    *,
    loc: Locations,
    chosen: Sequence[records.SideEffect | Leftover] = (),
    revert_asked: bool = False,
    configs: Sequence[OverhaulConfig] | None = None,
) -> RemovePreview:
    """What taking over does, with nothing written (run it with overhaul_install.remove). chosen: settings to put
    back and the backups folder, from choices(). Raises OverhaulError when the profile has no overhaul, or the
    launcher made its setup (Remove is for that)."""
    profile = Path(profile)
    effects = [c for c in chosen if isinstance(c, records.SideEffect)]
    r = overhaul_install.preview_remove(
        profile, loc=loc, revert_asked=revert_asked, legacy_choices=effects, configs=configs
    )
    if not r.legacy:
        raise OverhaulError(f"{r.config.label} in {profile.name} was installed with the launcher: use Remove.")
    if r.users:  # another profile still runs it: its folders, and so its installer's, stay
        return r
    want_backups = any(isinstance(c, Leftover) and c.backups for c in chosen)
    extra = [f for f in _installer_folders(profile, loc=loc, configs=configs) if want_backups or not f.backups]
    extra = [f for f in extra if not any(same_folder(f.path, t) for t in r.trash)]
    at = len(r.trash) - 1 if r.trash and same_folder(r.trash[-1], r.own) else len(r.trash)  # its folder stays last
    r.trash[at:at] = [f.path for f in extra]
    for f in extra:
        what = "Its installer's backups of your profiles" if f.backups else f"Its installer's setup copy {f.path.name}"
        r.lines.insert(-1, f"{what} ({size_text(f.size)}) goes to the Recycle Bin")
    return r


# ----------------------------------------------------------------------------- without an overhaul config
@dataclass(frozen=True)
class EntryChoice:
    """An entry in the profile that is not in the profile as it was before the installer, and does not point into the
    installer's folder: it may be the installer's or one the player added later, so removing it is the player's call."""

    kind: str
    name: str
    copied: bool = False  # there is evidence the installer made it: ticked at first

    @property
    def label(self) -> str:
        what = "DLL" if self.kind == "native" else "package"
        why = "copied by the installer" if self.copied else "not in the profile before the installer"
        return f"{self.name} ({what}): {why}"


def _key(kind: str, ident: str | None, path: str | None) -> tuple[str, str]:
    return kind, (ident if kind == "package" and ident else Path(str(path or "")).name).lower()


def _base(profile: Path, setup: installer_leftovers.Setup) -> dict | None:
    """The profile before the installer: kept in its manifest, else the oldest backup of it that a restore file
    names. None when neither is there."""
    kept = installer_leftovers.base_profile(setup, profile)
    if kept is not None:
        return kept
    for f in installer_leftovers.setup_folders(profile.parent):
        old = overhaul_install._oldest_backup(profile, f.path) if f.backups else None
        if old is not None:
            try:
                return tomllib.loads(old)
            except tomllib.TOMLDecodeError:
                continue
    return None


def _entries(profile: Path) -> list[dict]:
    try:
        return me3_profile.entries(me3_profile.read_text(profile))
    except OSError, ValueError:
        return []


def _inside(profile: Path, e: dict, folder: Path) -> bool:
    return bool(e.get("path")) and overhaul_install._inside(profile, e, folder)


def _settings(profile: Path, base: dict) -> list[records.SideEffect]:
    try:
        now = tomllib.loads(me3_profile.read_text(profile))
    except OSError, tomllib.TOMLDecodeError:
        return []
    return [
        records.SideEffect(setting=k, before=base.get(k), before_set=k in base, after=v)
        for k, v in now.items()
        if not isinstance(v, dict | list) and k != "profileVersion" and base.get(k) != v
    ]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _made_by_installer(profile: Path, e: dict, setup: installer_leftovers.Setup) -> bool:
    """The installer made this entry: its file is byte-identical to a file of the same name in the installer's folder,
    its setup copy or its backups, or the installer's manifest lists it."""
    if not e.get("path"):
        return False
    where = me3_profile.resolve(profile, e["path"])
    skip = set(installer_leftovers.rules().get("base_profile_keys", []))

    def without_base(o):  # the saved pre-install profile lists the player's own entries
        if isinstance(o, dict):
            return {k: without_base(v) for k, v in o.items() if k not in skip}
        return [without_base(v) for v in o] if isinstance(o, list) else o

    if not where.is_file():
        return False
    shown = json.dumps(without_base(setup.manifest))
    if where.name.lower() in {p.lower() for p in re.split(r'[\\/"]', shown) if p}:
        return True
    try:
        size, mine = where.stat().st_size, None
        for root in [setup.folder, *(f.path for f in installer_leftovers.setup_folders(profile.parent))]:
            for other in root.rglob(where.name):
                if other.is_file() and other != where and other.stat().st_size == size:
                    mine = mine or _sha(where)
                    if _sha(other) == mine:
                        return True
    except OSError:
        return False
    return False


def _setup_choices(profile: Path, setup: installer_leftovers.Setup) -> list:
    base = _base(profile, setup)
    out: list = []
    if base is not None:
        had = {_key("package", r.get("id"), r.get("path")) for r in base.get("packages", []) if isinstance(r, dict)}
        had |= {_key("native", None, r.get("path")) for r in base.get("natives", []) if isinstance(r, dict)}
        out += [
            EntryChoice(e["kind"], e["name"], _made_by_installer(profile, e, setup))
            for e in _entries(profile)
            if not _inside(profile, e, setup.folder) and _key(e["kind"], e.get("id"), e.get("path")) not in had
        ]
        out += _settings(profile, base)
    out += [
        Leftover(f.path, size_of(f.path), True) for f in installer_leftovers.setup_folders(profile.parent) if f.backups
    ]
    return out


def _stand_in(setup: installer_leftovers.Setup, game: str) -> OverhaulConfig:
    """A config with only what removing needs (a name), for a setup no config describes."""
    name = setup.folder.name
    ident = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "installer-setup"
    return OverhaulConfig(
        overhaul=1,
        id=ident,
        label=name,
        short_label=name,
        game=game,
        recognise=Recognise(folder=name, manifest=setup.manifest_name),
    )


def _drop_references(writer: ProfileWriter, refs: set[str]) -> int:
    """Take the removed entries (by id or DLL name) out of the other entries' load_after / load_before lists, so the
    profile stays valid. Returns how many entries changed."""
    changed = 0
    for e in writer.entries():
        edit = {}
        for key in ("load_after", "load_before"):
            kept = [d for d in e[key] if str(d["id"]).lower() not in refs]
            if len(kept) != len(e[key]):
                edit[key] = kept
        if edit:
            writer.set_options(e["index"], edit)
            changed += 1
    return changed


def _setup_preview(
    profile: Path, setup: installer_leftovers.Setup, *, loc: Locations, chosen: Sequence, revert_asked: bool
) -> RemovePreview:
    writer = ProfileWriter(profile)
    picked = {(c.kind, c.name) for c in chosen if isinstance(c, EntryChoice)}
    mine = [e for e in writer.entries() if _inside(profile, e, setup.folder) or (e["kind"], e["name"]) in picked]
    removed: list[str] = []
    refs = {me3_profile.entry_ref(e).lower() for e in mine}
    for e in sorted(mine, key=lambda e: e["index"], reverse=True):
        writer.remove_entry(e["index"])
        removed.insert(0, e["name"])
    fixed = _drop_references(writer, refs)
    r = RemovePreview(
        profile, _stand_in(setup, loc.game.key), setup.folder, None, True, writer, None, removed,
        [], [], [], [], [], [], revert_asked=revert_asked,
    )  # fmt: skip
    try:
        top = tomllib.loads(writer.text)
    except tomllib.TOMLDecodeError as e:
        r.refusals.append(f"{profile.name} could not be read: {e}")
        return r
    if not removed:
        r.refusals.append(f"{profile.name} has no entries of {setup.folder.name} to take over.")
    for eff in (c for c in chosen if isinstance(c, records.SideEffect)):
        overhaul_install._revert(r, eff, top)
    r.change = writer.plan(f"before taking over {setup.folder.name}")
    r.refusals += [x.message for x in r.change.refusals]
    r.users = installer_leftovers.other_users(profile, setup.folder)
    extra: list[installer_leftovers.Found] = []
    if not r.users:
        want = any(isinstance(c, Leftover) and c.backups for c in chosen)
        extra = [f for f in installer_leftovers.setup_folders(profile.parent) if want or not f.backups]
        extra = [f for f in extra if not installer_leftovers.used(profile.parent, f.path)]
        r.trash = [f.path for f in extra]
        if setup.folder.exists():
            r.trash.append(setup.folder)
    r.lines = overhaul_install._remove_lines(r)
    if fixed:
        r.lines.insert(
            1,
            f"{fixed} other entr{'y' if fixed == 1 else 'ies'} stop waiting for what is removed (load_after / load_before)",
        )
    for f in extra:
        what = "Its installer's backups of your profiles" if f.backups else f"Its installer's setup copy {f.path.name}"
        r.lines.insert(-1, f"{what} ({size_text(size_of(f.path))}) goes to the Recycle Bin")
    return r


def _hit(profile: Path, loc: Locations):
    return overhaul_install.overhaul_in(profile, recipes.load(loc.game.key))


def choices(profile: Path, *, loc: Locations) -> list:
    """What the player may also choose, none chosen at first: settings the installer changed (put back), entries
    that may be the installer's (remove), its backups folder (Recycle Bin). With no overhaul config the installer's
    own records say what it changed (its manifest's saved profile, else its oldest backup of it)."""
    profile = Path(profile)
    if _hit(profile, loc) is not None:
        return _config_choices(profile, loc=loc)
    setup = installer_leftovers.setup_of(profile)
    return _setup_choices(profile, setup) if setup is not None else []


def preview(
    profile: Path,
    *,
    loc: Locations,
    chosen: Sequence = (),
    revert_asked: bool = False,
    configs: Sequence[OverhaulConfig] | None = None,
) -> RemovePreview:
    """What taking over does, with nothing written (run it with overhaul_install.remove). chosen: from choices().
    The entries that point into the installer's folder always go. Raises OverhaulError when there is nothing to
    take over or the launcher made the setup (Remove is for that)."""
    profile = Path(profile)
    if configs is not None or _hit(profile, loc) is not None:
        return _config_preview(profile, loc=loc, chosen=chosen, revert_asked=revert_asked, configs=configs)
    setup = installer_leftovers.setup_of(profile)
    if setup is None:
        raise OverhaulError(f"{profile.name} has no setup made by an overhaul's own installer.")
    return _setup_preview(profile, setup, loc=loc, chosen=chosen, revert_asked=revert_asked)
