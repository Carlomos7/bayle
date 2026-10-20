"""A settings file as a form (technical specification §8.10, Mod Configs): its sections and settings, each with the
comment above it as its description, read from the text and written back by changing only that value's characters.
Comments, blank lines, order, spacing and line endings are never rewritten, so a file the form saves differs from
the one on disk only where a value changed.

Two languages: INI (.ini, .cfg, .conf: `key = value`, `;` or `#` comments, `[section]`) and flat TOML (`key = value`
with TOML values, `#` comments, `[table]`). What the form can't represent is listed read-only and left to the text
editor: TOML arrays, inline tables, multi-line strings, `[[array tables]]`, dotted or quoted keys, and a key set twice
in one section. The kind of an INI setting is worked out from its comment (on/off, a list of choices, a range); a TOML
setting's from its value.

Plain Python, no Qt; the text comes from mods.configs.read and goes back through mods.configs.write (formats: below mods and coop,
which both use it)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from typing import Any

INI, TOML = "ini", "toml"

_SECTION = re.compile(r"^[ \t]*\[([^\[\]]+)\][ \t]*(?:[;#].*)?$")
_ARRAY_TABLE = re.compile(r"^[ \t]*\[\[")
_INI_LINE = re.compile(r"^([ \t]*)([A-Za-z0-9_][A-Za-z0-9_ .\-]*?)([ \t]*[=:][ \t]*)(.*?)[ \t]*$")
_TOML_LINE = re.compile(r"^([ \t]*)([A-Za-z0-9_\-]+)([ \t]*=[ \t]*)(.*)$")
_TOML_OTHER_KEY = re.compile(r"^[ \t]*[\"'A-Za-z0-9_\-.]+[ \t]*=")  # a dotted or quoted key: read-only
_CHOICE = re.compile(r"(\d+)\s*=\s*([^|]+?)\s*(?=\||$)")
_DEFAULT = re.compile(r"\bdefault(?:\s+is|\s*[:=])\s*([^\s,;)]+)", re.I)


@dataclass
class Setting:
    """One `key = value` line. value: the text shown and edited (a TOML string without its quotes); raw: the
    characters in the file; kind: bool | choice | int | float | text | password; extra: the choices [(n, label)] or
    the range (lo, hi); readonly: the form can't change it (edit as text)."""

    section: str
    key: str
    value: str
    raw: str
    desc: str
    kind: str
    extra: Any = None
    default: str | None = None
    readonly: bool = False
    line: int = 0  # index into Document.lines
    start: int = 0  # the value's span in that line
    end: int = 0


@dataclass
class Section:
    name: str  # "" for settings before the first [section]
    settings: list[Setting] = field(default_factory=list)


@dataclass
class Document:
    lang: str
    lines: list[str]  # with their own line endings
    sections: list[Section]

    def text(self) -> str:
        return "".join(self.lines)

    def find(self, key: str, section: str | None = None) -> Setting | None:
        """The setting called key (case aside) in section, or the first one anywhere when section is None."""
        low = key.lower()
        for s in self.sections:
            if section is not None and s.name.lower() != section.lower():
                continue
            for item in s.settings:
                if item.key.lower() == low:
                    return item
        return None

    def set(self, key: str, value, section: str | None = None) -> bool:
        """Write value in place of the setting's value; only those characters change. False when there is no such
        setting; ValueError when the form can't change it."""
        item = self.find(key, section)
        if item is None:
            return False
        if item.readonly:
            raise ValueError(f"{item.key} can only be changed as text")
        raw = _toml_literal(item, value) if self.lang == TOML else str(value)
        line = self.lines[item.line]
        self.lines[item.line] = line[: item.start] + raw + line[item.end :]
        shift = len(raw) - (item.end - item.start)
        for other in self._on_line(item.line):
            if other is not item and other.start >= item.end:
                other.start += shift
                other.end += shift
        item.raw, item.end = raw, item.start + len(raw)
        item.value = _shown(self.lang, raw)
        return True

    def _on_line(self, n: int) -> list[Setting]:
        return [i for s in self.sections for i in s.settings if i.line == n]


def lang_of(name: str) -> str | None:
    """The language a file is read as by its suffix, or None when the form doesn't read it."""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"ini": INI, "cfg": INI, "conf": INI, "toml": TOML}.get(suffix)


def parse(text: str, lang: str) -> Document:
    """The document for this text (its line endings kept)."""
    lines = text.splitlines(keepends=True)
    current = Section("")
    sections = [current]
    pending: list[str] = []
    seen: set[tuple[str, str]] = set()
    skip_to = -1
    for n, full in enumerate(lines):
        if n <= skip_to:
            continue
        line = full.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith(("#", ";") if lang == INI else ("#",)):
            pending.append(stripped.lstrip(";# ").strip())
            continue
        if _ARRAY_TABLE.match(line):
            current = Section(stripped)  # [[...]]: its settings are listed read-only
            sections.append(current)
            pending = []
            continue
        m = _SECTION.match(line)
        if m:
            current = Section(m.group(1).strip())
            sections.append(current)
            pending = []
            continue
        desc = " ".join(pending)
        pending = []
        item = _ini_setting(current.name, line, desc) if lang == INI else None
        if lang == TOML:
            item, skip_to = _toml_setting(current.name, lines, n, desc)
        if item is None:
            continue
        item.line = n
        twice = (current.name.lower(), item.key.lower()) in seen
        seen.add((current.name.lower(), item.key.lower()))
        if twice or current.name.startswith("[["):
            item.readonly = True
            if twice:
                prev = next(i for i in current.settings if i.key.lower() == item.key.lower())
                prev.readonly = True
        current.settings.append(item)
    if not sections[0].settings:
        sections.pop(0)
    return Document(lang, lines, sections)


# ----------------------------------------------------------------------------- INI
def _ini_setting(section: str, line: str, desc: str) -> Setting | None:
    m = _INI_LINE.match(line)
    if not m:
        return None
    key, value = m.group(2), m.group(4)
    start = len(m.group(1)) + len(key) + len(m.group(3))
    kind, extra = ini_kind(key, value, desc)
    return Setting(section, key, value, value, desc, kind, extra, _default(desc), start=start, end=start + len(value))


def ini_kind(key: str, value: str, desc: str):
    """(kind, extra) from the comment: bool | choice [(n, label)] | int (lo, hi) | text | password."""
    d = desc.replace(" ", "").upper()
    if key.lower() == "cooppassword":
        return "password", None
    if "0=FALSE" in d and "1=TRUE" in d:
        return "bool", None
    choices = [(int(n), lab.strip().rstrip(".")) for n, lab in _CHOICE.findall(desc)] if "|" in desc else []
    if len(choices) >= 2:
        return "choice", choices  # "0 = Normal | 1 = None | 2 = ..."
    nums = re.findall(r"(-?\d+)\s*=", desc)
    if "MAX" in desc.upper() and len(nums) >= 2:
        return "int", (int(nums[0]), int(nums[-1]))  # "0 = MUTE 10 = MAX"
    if value.strip().lstrip("-").isdigit():
        return "int", (0, 500)
    return "text", None


def _default(desc: str) -> str | None:
    m = _DEFAULT.search(desc)
    return m.group(1).strip("\"'.") if m else None


# ----------------------------------------------------------------------------- TOML
def _toml_value(text: str):
    """The TOML value text parses to, or raises."""
    return tomllib.loads("v = " + text)["v"]


def _toml_setting(section: str, lines: list[str], n: int, desc: str) -> tuple[Setting | None, int]:
    """The setting starting at line n, and the last line it takes (a multi-line value takes several)."""
    line = lines[n].rstrip("\r\n")
    m = _TOML_LINE.match(line)
    if not m:
        if _TOML_OTHER_KEY.match(line):
            key = line.split("=", 1)[0].strip()
            return Setting(section, key, "", "", desc, "text", readonly=True), n
        return None, n
    key, rest = m.group(2), m.group(4)
    start = len(m.group(1)) + len(key) + len(m.group(3))
    raw = _value_part(rest)
    if raw is None:  # the value goes on below (a multi-line string or array): read-only, find where it ends
        body = rest
        for last in range(n + 1, len(lines)):
            body += "\n" + lines[last].rstrip("\r\n")
            try:
                tomllib.loads("v = " + body)
                return Setting(section, key, "", rest, desc, "text", readonly=True), last
            except tomllib.TOMLDecodeError:
                continue
        return Setting(section, key, "", rest, desc, "text", readonly=True), n
    value = _toml_value(raw)
    if isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, int):
        kind = "int"
    elif isinstance(value, float):
        kind = "float"
    elif isinstance(value, str):
        kind = "text"
    else:  # arrays, inline tables, dates
        return Setting(section, key, raw, raw, desc, "text", readonly=True, start=start, end=start + len(raw)), n
    readonly = isinstance(value, str) and raw.startswith(('"""', "'''"))
    extra = (-(2**31), 2**31 - 1) if kind == "int" else None
    return (
        Setting(
            section,
            key,
            _shown(TOML, raw),
            raw,
            desc,
            kind,
            extra,
            _default(desc),
            readonly,
            start=start,
            end=start + len(raw),
        ),
        n,
    )


def _value_part(rest: str) -> str | None:
    """The value's characters in what follows `key =` (an inline comment and trailing blanks left out), or None when
    it does not end on this line."""
    cut = len(rest)
    while True:
        candidate = rest[:cut].rstrip()
        try:
            _toml_value(candidate)
            return candidate
        except tomllib.TOMLDecodeError:
            pass
        cut = rest.rfind("#", 0, cut)
        if cut <= 0:
            return None


def _shown(lang: str, raw: str) -> str:
    if lang != TOML:
        return raw
    value = _toml_value(raw)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _toml_literal(item: Setting, value) -> str:
    """value written the way TOML reads it as the setting's kind."""
    if item.kind == "bool":
        on = value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "on", "yes")
        return "true" if on else "false"
    if item.kind == "int":
        return str(int(value))
    if item.kind == "float":
        f = float(value)
        return repr(f) if f != int(f) or "e" in repr(f) else f"{int(f)}.0"
    s = str(value)
    if item.raw.startswith("'") and "'" not in s and "\n" not in s:
        return f"'{s}'"  # keep a literal string literal
    escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    return f'"{escaped}"'
