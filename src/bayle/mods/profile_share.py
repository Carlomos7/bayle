"""The `roundtable-profile` file (technical specification, "Profile export/import format"): a profile's mods, their
options and order, its settings, and the settings files of its mods, as one JSON document (a share list), or as the
manifest of a zip that also holds the mods themselves.

The file comes from someone else, so reading it is a trust boundary. parse() refuses another format, version or game
and anything over MAX_JSON; what is merely not usable (a settings-file key that is a path, a name that is not a
settings file's, a setting me3 does not know, a value of the wrong type) is dropped and said in Share.skipped, never
acted on. Nothing here touches the disk."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from bayle.mods import configs, naming
from bayle.mods.profile import SETTING_KEYS

FORMAT = "roundtable-profile"
VERSION = 1
MAX_JSON = 8 * 1024 * 1024
MAX_ENTRIES = 5000
MAX_TEXT = 200  # a name, a version, an id

_BOOL_SETTINGS = ("start_online", "disable_arxan", "mem_patch")


class ShareError(ValueError):
    """The file can't be used at all; the message is for the player."""


@dataclass
class Share:
    name: str
    profile_version: str
    author: str
    exported: str
    settings: dict[str, Any]
    entries: list[dict]  # kind, folder, file / id, enabled, options: only well-formed ones
    stays_last: str | None
    configs: dict[tuple[str, str], str]  # (mod folder, file name) -> text
    full: dict[str, Any]  # zip only: {"profile": the .me3's name, "mods": [...], "save": a file name or None}
    skipped: list[str] = field(default_factory=list)


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _deps(raw: Any) -> list[dict]:
    out = []
    for d in raw if isinstance(raw, list) else []:
        if isinstance(d, str) and d:
            out.append({"id": d[:MAX_TEXT], "optional": True})
        elif isinstance(d, dict) and isinstance(d.get("id"), str) and d["id"]:
            out.append({"id": d["id"][:MAX_TEXT], "optional": d.get("optional", True) is not False})
    return out


def _initializer(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    if isinstance(raw.get("function"), str) and raw["function"]:
        return {"function": raw["function"][:MAX_TEXT]}
    delay = raw.get("delay")
    ms = delay.get("ms") if isinstance(delay, dict) else None
    if isinstance(ms, int) and not isinstance(ms, bool) and 0 <= ms <= 3_600_000:
        return {"delay": {"ms": ms}}
    return None


def _entry(raw: Any) -> dict | None:
    if not isinstance(raw, dict) or raw.get("kind") not in ("package", "native"):
        return None
    kind = raw["kind"]
    out: dict[str, Any] = {
        "kind": kind,
        "folder": _text(raw.get("folder")),
        "enabled": raw.get("enabled", True) is not False,
        "load_after": _deps(raw.get("load_after")),
        "load_before": _deps(raw.get("load_before")),
    }
    if kind == "package":
        out["id"] = _text(raw.get("id"))
        if not out["id"] and not out["folder"]:
            return None
    else:
        out["file"] = _text(raw.get("file"))
        if not out["file"]:
            return None
        out["optional"] = raw.get("optional") is True
        out["load_early"] = raw.get("load_early") is True
        out["initializer"] = _initializer(raw.get("initializer"))
        out["finalizer"] = _text(raw.get("finalizer"))
    return out


def config_key(key: Any) -> tuple[str, str] | None:
    """('mod folder', 'file name') for a key of the form "folder/name", or None for anything else: a path that
    climbs, is absolute, names a drive or goes deeper than one folder, or a name that is not a settings file's."""
    if not isinstance(key, str) or key.count("/") != 1:
        return None
    folder, name = key.split("/")
    if naming.unsafe(folder) is not None or not configs.settings_name(name):
        return None
    return folder, name


def savefile_ok(name: Any) -> bool:
    """A save file name me3 can use safely: a plain name Windows accepts, ending in .sl2 (the game-model rule)."""
    return isinstance(name, str) and name.lower().endswith(".sl2") and naming.unsafe(name) is None


def usable_settings(settings: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """(the profile settings an import may apply, what it leaves out and why). start_online is only ever turned
    off: going online with mods risks a ban, and that is the player's choice in Profile settings."""
    ok: dict[str, Any] = {}
    left: list[str] = []
    for key, value in settings.items():
        if key == "start_online" and value is True:
            left.append("Online play is left off: going online with mods risks a ban. Turn it on in Profile settings.")
        elif key in _BOOL_SETTINGS and isinstance(value, bool):
            ok[key] = value
        elif key == "mem_patch_heap_size" and isinstance(value, int) and not isinstance(value, bool):
            if 0 <= value <= 1_000_000:
                ok[key] = value
            else:
                left.append(f"{key}: {value} is not a usable size, so it is left out")
        elif key == "savefile" and savefile_ok(value):
            ok[key] = value
        else:
            left.append(f"{key}: {str(value)[:60]!r} is not usable here, so it is left out")
    return ok, left


def parse(raw: bytes | str, game_key: str) -> Share:
    """The share list in raw (JSON). Raises ShareError when it is not a roundtable-profile v1 file for this game."""
    if len(raw) > MAX_JSON:
        raise ShareError("That file is too big to be a profile (over 8 MB).")
    try:
        doc = json.loads(raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise ShareError("That file is not a profile file (it is not valid JSON).") from e
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise ShareError("That file is not a Bayle profile.")
    version = doc.get("version")
    if isinstance(version, bool) or version != VERSION:
        raise ShareError(f"That profile file is version {version!r}; this launcher reads version {VERSION}.")
    if doc.get("game") != game_key:
        raise ShareError(f"That profile is for another game ({_text(doc.get('game'), 40) or 'unknown'}).")
    skipped: list[str] = []
    rows = doc.get("entries") if isinstance(doc.get("entries"), list) else []
    if len(rows) > MAX_ENTRIES:
        raise ShareError("That profile lists far too many mods to be real.")
    entries = []
    for n, row in enumerate(rows, 1):
        got = _entry(row)
        if got is None:
            skipped.append(f"Entry {n} is not readable, so it is left out")
        else:
            entries.append(got)
    texts: dict[tuple[str, str], str] = {}
    raw_configs = doc.get("configs") if isinstance(doc.get("configs"), dict) else {}
    for key, text in raw_configs.items():
        got = config_key(key)
        if got is None:
            skipped.append(f"{str(key)[:80]}: not a settings file of one mod, so it is left out")
        elif not isinstance(text, str) or len(text.encode("utf-8", errors="replace")) > configs.MAX_BYTES:
            skipped.append(f"{key}: too big or not text, so it is left out")
        else:
            texts[got] = text
    settings = doc.get("settings") if isinstance(doc.get("settings"), dict) else {}
    full = doc.get("full") if isinstance(doc.get("full"), dict) else {}
    last = doc.get("stays_last")
    return Share(
        name=_text(doc.get("name")),
        profile_version=_text(doc.get("profile_version")),
        author=_text(doc.get("author")),
        exported=_text(doc.get("exported"), 40),
        settings={k: v for k, v in settings.items() if k in SETTING_KEYS},
        entries=entries,
        stays_last=_text(last) or None,
        configs=texts,
        full={
            "profile": _text(full.get("profile")),
            "mods": [_text(m) for m in full.get("mods", []) if isinstance(m, str)] if full else [],
            "save": _text(full.get("save")) or None,
        }
        if full
        else {},
        skipped=skipped,
    )


def dump(share: dict) -> str:
    return json.dumps(share, indent=2, ensure_ascii=False)


_PASSWORD = re.compile(r"(?im)^[ \t]*cooppassword[ \t]*=.*(\r?\n|$)")


def without_password(text: str) -> str:
    """A Seamless Co-op settings text without its password line (an export leaves it out unless asked)."""
    return _PASSWORD.sub("", text)
