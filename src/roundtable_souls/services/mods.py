"""Profile mods as the Mods page sees them: enable / disable, install, options, remove, profiles, me3 facts."""

from __future__ import annotations

import re
import time
import tomllib
from pathlib import Path

from roundtable_souls.config.settings import load_settings, save_settings
from roundtable_souls.formats import me3_profile
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import install, models, profile_writer, remove
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import profile_edit as mod_manage
from roundtable_souls.platform import logging as run_logging
from roundtable_souls.platform import me3_info


def _plain_line(line: str) -> str:
    return re.sub(r"^[ \t]*#[ \t]?", "", line.rstrip("\r\n")).strip()


def read_profile_mods(profile):
    """Mods me3 will load, in file order.

    An entry loads unless it sets enabled = false. enabled defaults to true.
    Commented-out blocks are comments, not entries. Both me3 shapes are read:
    [[packages]] blocks, and the packages = [ { ... } ] form Revive's installer writes.
    """
    try:
        text = me3_profile.read_text(Path(profile))
        found = me3_profile.entries(text)
    except OSError, tomllib.TOMLDecodeError:
        return []
    out = []
    for e in found:
        ident = e["id"] or Path(e["path"]).name
        if e["enabled"] and ident:
            out.append(dict(index=e["index"], kind=e["kind"], id=ident, path=e["path"], name=ident))
    return out


def _rewrite_block(block_lines, enabled: bool):
    lines = []
    for line in block_lines:
        nl = "\r\n" if line.endswith("\r\n") else ("\n" if line.endswith("\n") else "")
        body = line[: -len(nl)] if nl else line
        if enabled:
            m = re.match(r"^([ \t]*)#[ \t]?(.*)$", body)
            inner = m.group(2).strip() if m else ""
            if m and (inner.startswith("[[") or re.match(r"^[A-Za-z0-9_]+\s*=", inner) or inner[:1] in "{]}"):
                body = m.group(1) + m.group(2)
        lines.append(body + nl)
    val = "true" if enabled else "false"
    for i, line in enumerate(lines):
        if re.search(r"enabled\s*=", _plain_line(line), re.I):
            lines[i] = re.sub(r"(enabled\s*=\s*)(true|false)", r"\g<1>" + val, line, count=1, flags=re.I)
            return lines
    nl = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    lines.insert(1, f"enabled = {val}{nl}")
    return lines


def set_profile_mod_enabled(profile, index: int, enabled: bool) -> bool:
    """Turn one package or native on or off. Commented-out keys in its block are uncommented when turned on. Returns
    whether it changed."""
    w = profile_writer.ProfileWriter(Path(profile))
    blocks = me3_profile.blocks(w.text)
    if index < 0 or index >= len(blocks):
        raise IndexError(index)
    i, j = blocks[index]["start"], blocks[index]["end"]
    lines = w.text.splitlines(keepends=True)
    new_block = _rewrite_block(lines[i:j], enabled)
    if new_block == lines[i:j]:
        return False
    w.replace_block(index, new_block)
    w.write(f"before turning a mod {'on' if enabled else 'off'}")
    return True


def me3_facts(setup, loc: Locations) -> dict:
    """Installed version, `me3 info` folders, and (cached daily) the latest release. Never raises. reload: True when
    me3 reported its folders (cached in settings): the caller reads the settings again, as the profile folder falls
    back to that cache."""
    me3 = setup.me3_path() if setup else loc.me3_exe()
    facts = {
        "path": str(me3) if me3 else "",
        "version": me3_info.me3_version(me3),
        "info": me3_info.me3_info(me3),
        "latest": None,
        "update": False,
        "reload": False,
    }
    s = load_settings()
    if facts["info"].get("profile_dir") or facts["info"].get("logs_dir"):
        cache = {k: facts["info"].get(k, "") for k in ("profile_dir", "logs_dir", "install_prefix")}
        if cache != s.me3_info_cache:
            save_settings(me3_info_cache=cache)
            s.me3_info_cache = cache
        facts["reload"] = True
    if s.check_me3_updates:
        cached = s.me3_latest
        when = float(s.me3_latest_checked or 0)
        if not cached or time.time() - when > 86400:
            rel = me3_info.latest_release()
            if rel:
                cached = rel
                save_settings(me3_latest=rel, me3_latest_checked=time.time())
        if isinstance(cached, dict):
            facts["latest"] = cached
            facts["update"] = me3_info.update_available(facts["version"], cached.get("version"))
    return facts


def read_profile_settings(profile) -> dict:
    try:
        return profile_tools.read_settings(me3_profile.read_text(Path(profile)))
    except OSError:
        return {}


def write_profile_setting(profile, key: str, value) -> bool:
    """Set (or None: remove) one top-level me3 setting in the profile text, keeping comments; one .bak. Returns whether it changed."""
    w = profile_writer.ProfileWriter(Path(profile))
    w.set_setting(key, value)
    if w.text == w.before:
        return False
    w.write(f"before changing {key}")
    return True


def save_profile_text(profile, text: str) -> None:
    """The profile's whole text as the player wrote it in the editor: one .bak and a history copy first, written
    as it is (no rule but the safety ones applies to the player's own text)."""
    w = profile_writer.ProfileWriter(Path(profile))
    w.replace_text(text)
    w.write("before saving the editor")


def scan_profile_conflicts(profile) -> dict:
    return profile_tools.scan_conflicts(Path(profile))


def profile_entries(profile) -> list:
    """Every package and native block, enabled or not, with options (mod_manage.entries)."""
    try:
        return mod_manage.entries(Path(profile))
    except Exception:
        return []


def plan_mod_install(profile, source, name=None, pkg_id=None, variant=None, *, loc: Locations) -> dict:
    plan = install.plan_install(Path(profile), Path(source), name, pkg_id, variant, loc=loc)
    models.ModPlan.model_validate(plan)
    return plan


def replan_mod_install(profile, plan, name=None, pkg_id=None, variant=None, *, loc: Locations) -> dict:
    """The same unpacked mod with another folder name, id or variant (nothing is unpacked again)."""
    new = install.replan(Path(profile), plan, name, pkg_id, variant, loc=loc)
    models.ModPlan.model_validate(new)
    return new


def install_mod(profile, plan, overwrite=False, rebuild=False, *, loc: Locations) -> dict:
    """Install (or update) as one recoverable operation (mods.operations); with rebuild, the merged mods are rebuilt
    inside it, so a failed rebuild leaves the previous installation as it was."""
    from roundtable_souls.mods import rebuild as merge

    def then():
        merge.rebuild(Path(profile), run_logging.log, loc=loc)

    out = install.install(Path(profile), plan, overwrite=overwrite, then=then if rebuild else None, loc=loc)
    run_logging.log(f"{'updated' if out['update'] else 'installed'} {plan['kind']} {plan['name']} -> {out['dest']}")
    for rel in out.get("kept") or []:
        run_logging.log(f"kept your changed {rel} (the new version's copy is beside it as .new)")
    return out


def recover_interrupted(profile, timeout: float = 30.0) -> list[str]:
    """Finish or undo an install, update or removal in this profile's folder that was interrupted (the window or
    the PC closed during it). Returns what was done; [] when there was nothing, or the folder is busy."""
    from roundtable_souls.merging.build import BuildError
    from roundtable_souls.mods import operations

    try:
        said = operations.recover(Path(profile), timeout)
    except (BuildError, OSError) as e:
        run_logging.log(f"warning: could not check for an interrupted install: {e}")
        return []
    for line in said:
        run_logging.log(f"mods: {line}")
    return said


def uninstall_mod(profile, index: int, delete_folder=True, *, loc: Locations) -> dict:
    out = remove.uninstall(Path(profile), index, delete_folder=delete_folder, loc=loc)
    run_logging.log(
        f"removed {out['kind']} {out['path']}"
        + (
            ""
            if not out["removed_folder"]
            else f" and moved its folder {out['folder']} to the Recycle Bin"
            if out.get("trash") and out["trash"].get("kind") != "gone"
            else f" and deleted its folder {out['folder']}"
        )
    )
    return out


def set_mod_options(profile, index: int, opts: dict, *, loc: Locations):
    return mod_manage.set_options(Path(profile), index, opts, loc=loc)


def create_profile(name: str, copy_from=None, *, loc: Locations) -> Path:
    """A new profile for loc's game in me3's profile folder."""
    folder = loc.me3_profiles_dir()
    if not folder:
        raise RuntimeError("me3's profile folder is unknown on this PC (no LOCALAPPDATA).")
    return mod_manage.create_profile(folder, name, game=loc.game.key, copy_from=copy_from)


def create_first_profile(name: str, include_seamless: bool, *, loc: Locations, log=lambda s: None) -> Path:
    """The Play page's "Get started": a new profile for loc's game (create_profile), and, when asked and Seamless
    Co-op sits in the game folder, Seamless Co-op moved into it (services.coop). Returns the profile."""
    from roundtable_souls.services import coop as coop_service
    from roundtable_souls.services import play as play_service

    path = create_profile(name, loc=loc)
    log(f"profile: created {path}")
    if include_seamless:
        setup = play_service.Setup("me3", path, loc=loc)
        found = coop_service.game_folder_seamless(setup)
        if found is not None and found.kind == "move":
            coop_service.move_seamless_into_setup(setup, found, log)
    return path


def delete_profile(path) -> Path:
    return mod_manage.delete_profile(Path(path))


# ----------------------------------------------------------------------------- overhauls with the launcher (preview)
# The Mods page's Overhaul button (Widgets) and the Qt Quick page share these; the decisions and every word shown are
# in mods.overhaul_install. Previews read only; install_overhaul, remove_overhaul and remove_overhaul_leftovers run
# inside a logged job and leave the undo record Activity offers (mods.undo).


def installable_overhauls(game: str) -> list[str]:
    """The overhauls and editions the launcher can install for this game (a config's build with an install
    description), in plain words: the overhaul's name, the values its download must have (its edition) and the
    versions the build was written for."""
    from roundtable_souls import overhauls

    out: list[str] = []
    for config in overhauls.load(game):
        for b in config.builds:
            if b.install is None:
                continue
            edition = " ".join(str(j.equals) for j in b.match.json_ if isinstance(j.equals, str))
            words = " ".join(w for w in (config.label, edition, " or ".join(b.match.versions)) if w)
            if words not in out:
                out.append(words)
    return out


def overhaul_library_folder(game: str) -> str:
    """The name of the game's library folder in me3's profiles folder, where the launcher keeps its files."""
    from roundtable_souls.mods import library

    return library.ModLibrary.at(Path(), game).root.name


def overhaul_switch_text(game: str) -> str:
    """The line under the Settings switch: what it covers for this game, and where the launcher keeps its files."""
    names = installable_overhauls(game)
    covered = ", ".join(names) if names else "none for this game yet"
    return (
        "Adds an Overhaul button to the Mods page: install an overhaul into a profile from the folder you unpacked "
        "its download into, without running its installer, and remove it again. It covers only the overhauls the "
        f"launcher has an install description for ({covered}); others aren't offered, so use their own installer. "
        f"The launcher keeps its copy of the download in {overhaul_library_folder(game)}, in me3's profiles folder."
    )


def overhaul_button_tip(game: str) -> str:
    """The Overhaul button's tooltip on the Mods page."""
    names = installable_overhauls(game)
    return (
        "Install an overhaul with the launcher, remove one, or clean up what its own installer left. Only overhauls "
        f"the launcher has an install description for: {', '.join(names) if names else 'none for this game yet'}. "
        "A preview: Tools > Play session turns it on and off."
    )


def overhaul_preview_on(loc: Locations) -> bool:
    """The Settings switch "Install overhauls with the launcher (preview)" is on and the game has an overhaul the
    launcher can install."""
    return bool(load_settings().overhaul_install) and bool(installable_overhauls(loc.game.key))


def preview_overhaul_install(profile, download, *, loc: Locations):
    """What installing the download into the profile does (overhaul_install.InstallPreview: lines, notes,
    refusals). Raises overhaul_install.OverhaulError when the download is not one the launcher installs."""
    from roundtable_souls.mods import overhaul_install

    return overhaul_install.preview_install(Path(profile), Path(download), loc=loc)


def install_overhaul(preview, *, loc: Locations) -> dict:
    """Install as previewed, as one operation, and leave its undo record (Undo install, or Roll back for an
    update)."""
    from roundtable_souls.mods import overhaul_install

    out = overhaul_install.install(preview, loc=loc, log=run_logging.log)
    run_logging.set_undo(
        {
            "type": "overhaul-update" if out["update"] else "overhaul-install",
            "profile": str(preview.profile),
            "name": out["name"],
            "operation": out["operation"],
        }
    )
    run_logging.log(f"done: {'updated' if out['update'] else 'installed'} {preview.label} in {preview.profile.name}")
    return out


def profile_overhaul(profile, *, loc: Locations) -> dict | None:
    """The overhaul the profile has, for the Overhaul menu: {label, short_label, legacy} (legacy: its own installer
    set it up), or None."""
    from roundtable_souls import overhauls
    from roundtable_souls.mods import overhaul_install

    hit = overhaul_install.overhaul_in(Path(profile), overhauls.load(loc.game.key))
    if hit is None:
        return None
    config = hit[0]
    return {
        "label": config.label,
        "short_label": config.short_label,
        "legacy": overhaul_install.installer_setup(Path(profile), config) is not None,
    }


def legacy_overhaul_choices(profile, *, loc: Locations) -> list[tuple[str, object]]:
    """For a setup an overhaul's own installer made: the changes it made that can be put back, each (text, the
    change to pass to preview_overhaul_removal). Empty when there is nothing to compare with."""
    from roundtable_souls.mods import overhaul_install

    return [(overhaul_install.choice_text(e), e) for e in overhaul_install.legacy_effects(Path(profile), loc=loc)]


def preview_overhaul_removal(profile, *, loc: Locations, revert_asked: bool = False, legacy_choices=()):
    """What Remove overhaul does (overhaul_install.RemovePreview: lines, asked, refusals). Raises
    overhaul_install.OverhaulError when the profile has no overhaul the launcher knows."""
    from roundtable_souls.mods import overhaul_install

    return overhaul_install.preview_remove(
        Path(profile), loc=loc, revert_asked=revert_asked, legacy_choices=list(legacy_choices)
    )


def remove_overhaul(preview) -> dict:
    """Remove as previewed, as one operation, and leave its undo record (Restore)."""
    from roundtable_souls.mods import overhaul_install

    out = overhaul_install.remove(preview, log=run_logging.log)
    run_logging.set_undo(
        {
            "type": "overhaul-remove",
            "profile": str(preview.profile),
            "name": out["name"],
            "operation": out["operation"],
            "trash": out["trash"],
        }
    )
    run_logging.log(f"done: removed {out['name']} from {preview.profile.name}")
    return out


def overhaul_leftovers(profile, *, loc: Locations) -> list:
    """What overhauls' own installers left beside the profile that no profile there uses (overhaul_install.Leftover:
    path, size, label, backups), the installers' profile backups last."""
    from roundtable_souls.mods import overhaul_install

    return overhaul_install.leftovers(Path(profile), loc=loc)


def remove_overhaul_leftovers(paths) -> list[dict]:
    """Send the chosen leftovers to the Recycle Bin (run inside a logged job)."""
    from roundtable_souls.mods import overhaul_install

    out = overhaul_install.remove_leftovers([Path(p) for p in paths], log=run_logging.log)
    run_logging.log(f"done: {len(out)} folder(s) moved to the Recycle Bin")
    return out


# ----------------------------------------------------------------------------- the Overhaul setup form (S3g)
def propose_overhaul_setup(folder, name: str, *, loc: Locations, overhaul_id: str | None = None):
    """A setup for the mod in folder (an unpacked download's mod folder, plan["root"], or an installed mod's
    folder), at the basic level with the form's starting values: its id from the name (or overhaul_id: an installed
    mod keeps its package id, so its entries are replaced), loading last, its top-level DLLs with no special
    options, the settings files beside them kept. Returns an overhauls.OverhaulConfig; raises ValueError when the
    folder has nothing to set up."""
    from roundtable_souls.mods import naming
    from roundtable_souls.overhauls import basic

    ident = overhaul_id or naming.mod_id(name)
    game = loc.game.key
    return basic.make(
        id=ident, label=name, game=game, basic=basic.propose(Path(folder), game=game), folder=Path(folder)
    )


def preview_overhaul_setup(profile, folder, config, *, loc: Locations):
    """What installing the mod in folder as an overhaul with config (the form's, basic or advanced) would do
    (overhaul_install.InstallPreview: lines, notes, refusals); writes nothing. Raises overhaul_install.OverhaulError
    when it can't be set up."""
    from roundtable_souls.mods import overhaul_install

    return overhaul_install.preview_setup(Path(profile), Path(folder), config, loc=loc)


def install_overhaul_setup(preview, *, loc: Locations) -> dict:
    """Install as previewed, its config written to the local overhauls folder in the same operation, and leave
    its undo record (Undo install takes the config back too)."""
    from roundtable_souls.mods import overhaul_install

    out = overhaul_install.install_setup(preview, loc=loc, log=run_logging.log)
    run_logging.set_undo(
        {
            "type": "overhaul-update" if out["update"] else "overhaul-install",
            "profile": str(preview.profile),
            "name": out["name"],
            "operation": out["operation"],
        }
    )
    run_logging.log(f"done: set up {preview.label} as an overhaul in {preview.profile.name}")
    return out


def overhaul_setup_of(profile, *, loc: Locations) -> dict | None:
    """The profile's overhaul for the Mod Configs "Overhaul setup" node: {config, path (its file), sha (of the file
    as read, for save_overhaul_setup), verified, level ("basic" or "advanced"), folder (the launcher's copy of its
    download, the files the form lists; None when there is none)}; None without an overhaul."""
    from roundtable_souls import overhauls
    from roundtable_souls.mods import overhaul_install
    from roundtable_souls.overhauls import basic, writer

    hit = overhaul_install.overhaul_in(Path(profile), overhauls.load(loc.game.key))
    if hit is None:
        return None
    config = hit[0]
    path = overhauls.origin(config.id)
    where = overhaul_install.places(Path(profile), config.id, loc)
    folder = where.sources if where is not None and where.sources.is_dir() else None
    return {
        "config": config,
        "path": path,
        "sha": writer.sha256_of(path) if path is not None else None,
        "verified": overhauls.verified(config.id),
        "level": basic.level(config, folder) if folder is not None else "advanced",
        "folder": folder,
    }


def save_overhaul_setup(config, *, expect: str | None, path=None, folder=None) -> Path:
    """Save the form: at the basic level the steps are derived again from the mod's files in folder (the download
    copy) first. A file changed since it was read (expect: its sha256 then) is not overwritten. Every profile using
    it is rebuilt before its next Play. Raises overhauls.writer.WriteRefused or ValueError."""
    from roundtable_souls.mods import overhaul_install
    from roundtable_souls.overhauls import writer

    if folder is not None:
        config = overhaul_install.setup_config(config, Path(folder))
    out = writer.save_local(config, expect=expect, path=Path(path) if path else None)
    run_logging.log(f"saved the overhaul setup {out}")
    return out


def preview_turn_off_overhaul(profile, *, loc: Locations):
    """What Turn off does to the profile's overhaul setup (overhaul_install.TurnOffPreview: lines, refusals).
    Raises overhaul_install.OverhaulError when the profile has no overhaul."""
    from roundtable_souls.mods import overhaul_install

    return overhaul_install.preview_turn_off(Path(profile), loc=loc)


def turn_off_overhaul(preview) -> dict:
    """Turn it off as previewed, as one operation, and leave its undo record (Undo turn off)."""
    from roundtable_souls.mods import overhaul_install

    out = overhaul_install.turn_off(preview, log=run_logging.log)
    run_logging.set_undo(
        {
            "type": "overhaul-turn-off",
            "profile": str(preview.remove.profile),
            "name": out["name"],
            "operation": out["operation"],
            "trash": out["trash"],
        }
    )
    run_logging.log(f"done: {out['name']} is an ordinary mod again in {preview.remove.profile.name}")
    return out


# ----------------------------------------------------------------------------- a profile a download ships (S3g)
def preview_profile_import(unpacked, me3: str, current, *, loc: Locations, new_name: str | None = None):
    """What importing the .me3 a download ships (me3: its path in plan["unpacked"], one of plan["profiles_inside"])
    would do: into current, or into a new profile named new_name beside it (profile_import.ImportPreview: lines,
    renamed, skipped, refusals). Raises ModError when it can't be read."""
    from roundtable_souls.mods import profile_import

    return profile_import.preview_import(Path(unpacked), me3, Path(current), loc=loc, new_name=new_name)


def import_profile(preview) -> dict:
    """Import as previewed, as one operation, and leave its undo record (Undo import)."""
    from roundtable_souls.mods import profile_import

    out = profile_import.apply_import(preview, log=run_logging.log)
    run_logging.set_undo(
        {
            "type": "profile-import",
            "profile": out["profile"],
            "name": preview.profile.name,
            "operation": out["operation"],
        }
    )
    run_logging.log(f"done: imported into {preview.profile.name}")
    return out
