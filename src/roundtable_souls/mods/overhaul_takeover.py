"""Taking over an overhaul its own installer set up: the profile loses the installer's entries (packages, natives,
and the load order lists on them), the settings the player chose to put back go back, and the installer's folders go
to the Recycle Bin, all as one undoable operation (overhaul_install.remove). The overhaul is then installed again
through the launcher by the player (nothing installs here). The player's own mod folders are never touched: only the
overhaul's folder, its installer's setup copy and, when chosen, its installer's backups go."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls import overhauls
from roundtable_souls.mods import installer_leftovers, overhaul_install, records
from roundtable_souls.mods.checks import same_folder
from roundtable_souls.mods.overhaul_install import Leftover, OverhaulError, RemovePreview, size_of, size_text
from roundtable_souls.overhauls.config import OverhaulConfig

if TYPE_CHECKING:
    from roundtable_souls.game.locate import Locations


def choices(profile: Path, *, loc: Locations) -> list[records.SideEffect | Leftover]:
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
    configs = list(configs) if configs is not None else overhauls.load(loc.game.key)
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


def preview(
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
