"""Mod Configs (technical specification §8.10): which of a profile's mods have settings files, reading and saving them
as a form or as text, attaching a file to a mod, and Seamless Co-op's own panel (password, difficulty, language, and
sharing the settings with a friend). Facts and actions only: the words are the Mod Configs presenter's.

Every write goes through mods.configs.write with the fingerprint read with the file, so a file changed on disk in
the meantime (the Co-op page, the mod itself, an editor) is never overwritten; only the edited values' characters
change (formats.config_model). Saving while the game runs is allowed: the mods read their files at launch (owner,
E1 A)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from roundtable_souls.coop import ini as coop_ini
from roundtable_souls.coop import scaling as coop_scaling
from roundtable_souls.coop import share as coop_share
from roundtable_souls.formats import config_model
from roundtable_souls.mods import configs, profile_edit
from roundtable_souls.services.mods import profile_entries

if TYPE_CHECKING:
    from roundtable_souls.config.settings import LauncherSettings
    from roundtable_souls.game.locate import Locations

SEAMLESS = "seamless"


@dataclass(frozen=True)
class ConfigFile:
    path: Path
    how: str  # found (beside the mod) | attached | seamless
    exists: bool
    kind: str  # seamless | form | markdown | text


@dataclass(frozen=True)
class ModNode:
    """One mod with settings files. key: stable across reads (seamless, or kind:path); target: what a file is attached
    to (a DLL, or a package's folder); loaded: Seamless only: the profile loads it."""

    key: str
    name: str
    kind: str  # seamless | native | package
    enabled: bool
    loaded: bool
    target: Path | None
    files: tuple[ConfigFile, ...] = ()


def _kind(path: Path, seamless_ini: str | None) -> str:
    if seamless_ini and path.name.lower() == seamless_ini.lower():
        return SEAMLESS
    if config_model.lang_of(path.name):
        return "form"
    return "markdown" if path.suffix.lower() == ".md" else "text"


def tree(profile, *, loc: Locations, settings: LauncherSettings) -> list[ModNode]:
    """The profile's mods with settings files, Seamless Co-op first (also when the profile doesn't load it, so the
    page can say how to), then DLLs and packages in the profile's order."""
    prof = Path(profile)
    game = loc.game
    entries = profile_entries(prof)
    out: list[ModNode] = []
    ini = coop_ini.coop_ini_for(str(prof), game) if game.coop_ini else None
    skip = {configs.key_for(ini)} if ini else set()
    if game.coop_dll and game.coop_ini:
        entry = next(
            (e for e in entries if e["kind"] == "native" and Path(e["path"]).name.lower() == game.coop_dll), None
        )
        files = (ConfigFile(ini, SEAMLESS, True, SEAMLESS),) if ini else ()
        out.append(
            ModNode(SEAMLESS, game.coop_dll, SEAMLESS, bool(entry and entry["enabled"]), ini is not None, None, files)
        )
    for e in entries:
        if not e.get("path") or (
            e["kind"] == "native" and game.coop_dll and Path(e["path"]).name.lower() == game.coop_dll
        ):
            continue
        where = profile_edit.resolve(prof, e["path"])
        if e["kind"] == "native":
            found = configs.files_for(settings, where, skip=skip)
        else:
            found = _package_files(settings, where)
        if not found:
            continue
        files = tuple(
            ConfigFile(
                Path(f["path"]),
                "attached" if f["how"] == "tied" else "found",
                f["exists"],
                _kind(Path(f["path"]), game.coop_ini),
            )
            for f in found
        )
        out.append(ModNode(f"{e['kind']}:{where}", e["name"], e["kind"], bool(e["enabled"]), True, where, files))
    return out


def _package_files(settings: LauncherSettings, folder: Path) -> list[dict]:
    """A package's settings files: attached ones, and settings-looking files at the top of its folder."""
    out, seen = [], set()
    attached = configs.tied(settings, folder)
    top = sorted(k for k in folder.iterdir() if configs.looks_like_settings(k)) if folder.is_dir() else []
    for how, paths in (("tied", attached), ("found", top)):
        for p in paths:
            if configs.key_for(p) not in seen:
                seen.add(configs.key_for(p))
                out.append({"path": p, "how": how, "exists": p.is_file()})
    return out


def attach(settings: LauncherSettings, target: Path, file: Path) -> dict:
    """Attach file to the mod (settings.native_configs, never the .me3); returns the new value, saved."""
    from roundtable_souls.config.settings import save_settings

    ties = configs.with_tie(settings, target, file)
    save_settings(native_configs=ties)
    settings.native_configs = ties
    return ties


def detach(settings: LauncherSettings, target: Path, file: Path) -> dict:
    from roundtable_souls.config.settings import save_settings

    ties = configs.without_tie(settings, target, file)
    save_settings(native_configs=ties)
    settings.native_configs = ties
    return ties


# ----------------------------------------------------------------------------- one file
@dataclass
class Opened:
    """A file as read: its text (line breaks as \\n), how to write it back, its fingerprint, and the form when the
    file is one the form reads (doc is None for text and Markdown)."""

    path: Path
    text: str
    encoding: str
    crlf: bool
    sha: str
    doc: config_model.Document | None = None


def open_file(path: Path) -> Opened:
    """Raises configs.ConfigError for a file too big or not text, OSError when it can't be read."""
    got = configs.read(Path(path))
    lang = config_model.lang_of(Path(path).name)
    doc = config_model.parse(got["text"], lang) if lang else None
    return Opened(Path(path), got["text"], got["encoding"], got["crlf"], got["sha"], doc)


def save_values(opened: Opened, changes: dict[tuple[str, str], str]) -> Path:
    """Write the changed values ((section, key) -> value), nothing else; returns the .bak. Raises ConfigError when the
    file changed on disk since it was read, ValueError for a setting only text can change."""
    doc = config_model.parse(opened.text, config_model.lang_of(opened.path.name) or config_model.INI)
    for (section, key), value in changes.items():
        if not doc.set(key, value, section):
            raise ValueError(f"{key} is no longer in {opened.path.name}")
    return configs.write(opened.path, doc.text(), opened.encoding, opened.crlf, expect=opened.sha)


def save_text(opened: Opened, text: str) -> Path:
    return configs.write(opened.path, text, opened.encoding, opened.crlf, expect=opened.sha)


def reset_value(setting: config_model.Setting) -> tuple[str, str]:
    """(value, where it comes from: default | disk) for one setting's Reset."""
    if setting.default is not None:
        return setting.default, "default"
    return setting.value, "disk"


# ----------------------------------------------------------------------------- Seamless Co-op
@dataclass(frozen=True)
class Seamless:
    ini: Path
    password: str | None  # None: the file has no password (Nightreign's)
    spec: coop_scaling.ScalingSpec | None
    scaling: tuple[int, ...] | None
    preset: str
    languages: tuple[str, ...]  # "" (the game's language) and each translation in its locale folder
    language: str
    settings: list = field(default_factory=list)  # the other sections, as coop_ini.read_settings_meta gives them


LANGUAGE_KEY = "mod_language_override"


def seamless(ini: Path) -> Seamless:
    ini = Path(ini)
    spec = coop_scaling.scaling_spec(ini)
    values = coop_scaling.read_scaling(ini, spec) if spec else None
    locale = ini.parent / "locale"
    langs = sorted(p.stem for p in locale.glob("*.json")) if locale.is_dir() else []
    current = coop_ini.read_keys(ini, [LANGUAGE_KEY]).get(LANGUAGE_KEY, "").strip()
    if current and current not in langs:
        langs.append(current)  # a value the folder doesn't have stays choosable as it is
    return Seamless(
        ini,
        coop_ini.read_password(ini) if coop_ini.has_password(ini) else None,
        spec,
        values,
        coop_scaling.preset_of(values, spec) if values else coop_scaling.CUSTOM,
        ("", *langs),
        current,
        [s for s in coop_ini.read_settings_meta(ini) if s["section"].upper() not in ("PASSWORD", "SCALING")],
    )


def save_seamless(ini: Path, values: dict[str, str]) -> list[str]:
    """Write these keys (the password, the difficulty values, any setting) in place; returns the keys the file does
    not have (nothing is appended). An empty password is refused (ValueError)."""
    if "cooppassword" in values and not str(values["cooppassword"]).strip():
        raise ValueError("The Seamless Co-op password cannot be empty.")
    return coop_ini.write_keys(Path(ini), values)


def share_text(ini: Path) -> str:
    """Every setting as ini lines, comments left out, the password included (a friend needs it to join; owner,
    E3 A): what Copy settings and Save settings give."""
    out = []
    for section, values in coop_share.read_all_settings(Path(ini)).items():
        if section:
            out.append(f"[{section}]")
        out.extend(f"{k} = {v}" for k, v in values.items())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


_LINE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def parse_share(text: str) -> dict[str, str]:
    """{key: value} from shared settings: ini lines, or the JSON export older launchers wrote (read for one release,
    coordinator 2026-10-14). Raises ValueError when the text holds no settings."""
    if text.lstrip().startswith(("{", "//")):
        return coop_share.parse_settings_json(text)
    out = {}
    for line in text.splitlines():
        if line.strip().startswith((";", "#", "[")):
            continue
        m = _LINE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    if not out:
        raise ValueError("no settings in that text")
    return out


def plan_paste(ini: Path, text: str) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """(changes {key: (yours, theirs)}, keys your file doesn't have) for shared settings; nothing written."""
    return coop_share.plan_import(Path(ini), parse_share(text))
