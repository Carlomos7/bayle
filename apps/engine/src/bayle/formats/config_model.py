"""A settings file as a form (technical specification §8.10, Mod Configs): its sections and settings, each with the
comment above it as its description, read from the text and written back by changing only that value's characters.
Comments, blank lines, order, spacing and line endings are never rewritten, so a file the form saves differs from
the one on disk only where a value changed.

Two languages: INI (.ini, .cfg, .conf: `key = value`, `;` or `#` comments, `[section]`), edited by the characters of
its value lines; and TOML, read and written by tomlkit (comments, spacing and order survive a write; only the edited
value changes). A TOML table is a section named by its path ("a.b"; dotted keys and inline tables are tables too), an
`[[array of tables]]` gives one section per table ("[[builds]] #1"), and an array of plain values is one setting shown
as a comma list. What the form can't change is listed read-only (multi-line strings, dates, arrays of mixed values),
and a TOML file that does not parse gives no sections (it is edited as text). The kind of an INI setting is worked out
from its comment (on/off, a list of choices, a range); a TOML setting's from its value.

Plain Python, no Qt; the text comes from mods.configs.read and goes back through mods.configs.write (formats: below mods and coop,
which both use it)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import tomlkit
import tomlkit.items
from tomlkit.exceptions import TOMLKitError

INI, TOML = "ini", "toml"

_SECTION = re.compile(r"^[ \t]*\[([^\[\]]+)\][ \t]*(?:[;#].*)?$")
_INI_LINE = re.compile(r"^([ \t]*)([A-Za-z0-9_][A-Za-z0-9_ .\-]*?)([ \t]*[=:][ \t]*)(.*?)[ \t]*$")
_CHOICE = re.compile(r"(\d+)\s*=\s*([^|]+?)\s*(?=\||$)")
_DEFAULT = re.compile(r"\bdefault(?:\s+is|\s*[:=])\s*([^\s,;)]+)", re.I)
_YES = ("1", "true", "on", "yes")


@dataclass
class Setting:
    """One `key = value`. section: the INI section, or the TOML table's path ("a.b", "[[builds]] #2"); value: the text
    shown and edited (a TOML string without its quotes, an array as "1, 2"); raw: the characters in the file; kind:
    bool | choice | int | float | text | password; extra: the choices [(n, label)] or the range (lo, hi); readonly:
    the form can't change it (edit as text). line/start/end: INI only, the value's span in Document.lines."""

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
    lines: list[str]  # with their own line endings (INI: the text edited; TOML: as read)
    sections: list[Section]
    toml: Any = None  # TOML only: the tomlkit document, and the table each section's settings live in
    tables: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        return tomlkit.dumps(self.toml) if self.toml is not None else "".join(self.lines)

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
        raw = str(value)
        if "\n" in raw or "\r" in raw:  # a line break would add lines to the player's file
            raise ValueError("a value can't contain a line break")
        if self.lang == TOML:
            self._set_toml(item, value)
            return True
        line = self.lines[item.line]
        self.lines[item.line] = line[: item.start] + raw + line[item.end :]
        shift = len(raw) - (item.end - item.start)
        for other in self._on_line(item.line):
            if other is not item and other.start >= item.end:
                other.start += shift
                other.end += shift
        item.raw, item.end = raw, item.start + len(raw)
        item.value = raw
        return True

    def _set_toml(self, item: Setting, value) -> None:
        table = self.tables[item.section]
        old = table[item.key]
        new = _toml_item(item, old, value)
        table[item.key] = new  # tomlkit keeps the key's spacing and its comment
        expect = _toml_view(new)[1]
        again = parse(self.text(), TOML).find(item.key, item.section)  # read back what was written
        if again is None or again.value != expect:
            table[item.key] = old
            raise ValueError(f"{item.key} could not be written as {value!r}")
        item.raw, item.value = new.as_string().strip(), expect

    def _on_line(self, n: int) -> list[Setting]:
        return [i for s in self.sections for i in s.settings if i.line == n]


def lang_of(name: str) -> str | None:
    """The language a file is read as by its suffix, or None when the form doesn't read it."""
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"ini": INI, "cfg": INI, "conf": INI, "toml": TOML}.get(suffix)


def parse(text: str, lang: str) -> Document:
    """The document for this text (its line endings kept)."""
    if lang == TOML:
        return _parse_toml(text)
    lines = text.splitlines(keepends=True)
    current = Section("")
    sections = [current]
    pending: list[str] = []
    seen: set[tuple[str, str]] = set()
    for n, full in enumerate(lines):
        line = full.rstrip("\r\n")
        stripped = line.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith((";", "#")):
            pending.append(stripped.lstrip(";# ").strip())
            continue
        m = _SECTION.match(line)
        if m:
            current = Section(m.group(1).strip())
            sections.append(current)
            pending = []
            continue
        desc = " ".join(pending)
        pending = []
        item = _ini_setting(current.name, line, desc)
        if item is None:
            continue
        item.line = n
        twice = (current.name.lower(), item.key.lower()) in seen
        seen.add((current.name.lower(), item.key.lower()))
        if twice:
            item.readonly = True
            next(i for i in current.settings if i.key.lower() == item.key.lower()).readonly = True
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


# ----------------------------------------------------------------------------- TOML (tomlkit)
def _parse_toml(text: str) -> Document:
    lines = text.splitlines(keepends=True)
    try:
        toml = tomlkit.parse(text)
    except TOMLKitError:
        return Document(TOML, lines, [])  # not TOML: no form, only the text editor
    doc = Document(TOML, lines, [], toml)
    _walk(doc, toml, "")
    doc.sections = [s for s in doc.sections if s.settings]
    return doc


def _walk(doc: Document, table, path: str) -> None:
    """The settings of this table, then its sub-tables, in file order; the comment lines right above a key are its
    description (a blank line ends them)."""
    section = Section(path)
    doc.sections.append(section)
    doc.tables[path] = table
    pending: list[str] = []
    for key, item in table.body if hasattr(table, "body") else table.value.body:
        if key is None:  # a comment line, or blank space
            if isinstance(item, tomlkit.items.Comment):
                pending.append(item.as_string().strip().lstrip("#").strip())
            else:
                pending = []
            continue
        name, desc, pending = key.key, " ".join(pending), []
        sub = f"{path}.{name}" if path else name
        if isinstance(item, tomlkit.items.AoT):
            for i, t in enumerate(item.body, 1):
                _walk(doc, t, f"[[{sub}]] #{i}")
        elif isinstance(item, (tomlkit.items.Table, tomlkit.items.InlineTable)):
            _walk(doc, item, sub)
        else:
            kind, shown, readonly, extra = _toml_view(item)
            raw = item.as_string().strip()
            section.settings.append(Setting(path, name, shown, raw, desc, kind, extra, _default(desc), readonly))


def _toml_view(item) -> tuple[str, str, bool, Any]:
    """(kind, the text shown, read-only, range) for a TOML value."""
    value = item.unwrap()
    if isinstance(value, bool):
        return "bool", "true" if value else "false", False, None
    if isinstance(value, int):
        return "int", str(value), False, (-(2**31), 2**31 - 1)
    if isinstance(value, float):
        return "float", str(value), False, None
    if isinstance(value, str):
        return "text", value, item.as_string().strip().startswith(('"""', "'''")), None
    if isinstance(value, list):  # one kind of plain value, none holding a comma or a line break
        kinds = {type(v) for v in value}
        plain = len(kinds) == 1 and kinds <= {bool, int, float, str}
        plain = plain and not any(isinstance(v, str) and re.search(r"[,\r\n]", v) for v in value)
        return "text", ", ".join(str(v).lower() if isinstance(v, bool) else str(v) for v in value), not plain, None
    return "text", item.as_string().strip(), True, None  # dates, times


def _toml_item(setting: Setting, old, value):
    """value as a tomlkit item of the setting's kind (an array keeps its element type, a literal string stays one)."""
    current = old.unwrap() if hasattr(old, "unwrap") else old  # tomlkit hands a bool back as a plain one
    if isinstance(current, list):
        kind = type(current[0])
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
        try:
            return tomlkit.item([p.lower() in _YES if kind is bool else kind(p) for p in parts])
        except ValueError as e:
            raise ValueError(f"{setting.key} takes a list of {kind.__name__} values") from e
    if setting.kind == "bool":
        return tomlkit.item(value if isinstance(value, bool) else str(value).strip().lower() in _YES)
    if setting.kind == "int":
        return tomlkit.item(int(value))
    if setting.kind == "float":
        return tomlkit.item(float(value))
    return tomlkit.string(str(value), literal=setting.raw.startswith("'") and "'" not in str(value))
