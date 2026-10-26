"""Syntax of the code editor without Qt: which spans of a line are a keyword, string, number, comment, key or header
(per language, one line at a time with a small carry-over state for multi-line strings and comments), and the first
parse error of a TOML, JSON or INI text in plain words."""

from __future__ import annotations

import configparser
import json
import re
import tomllib
from pathlib import Path

from bayle_qt.text import tr

Span = tuple[int, int, str]  # start, length, role

ROLES = ("keyword", "string", "number", "comment", "key", "header")
_BY_EXTENSION = {
    ".me3": "toml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".json": "json",
    ".hks": "lua",
    ".lua": "lua",
    ".md": "markdown",
}
_NUMBER = r"(?P<number>(?<![\w.])-?(?:0[xX][0-9a-fA-F]+|\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?)\b)"
_LUA_WORDS = "and break do else elseif end false for goto if in local nil not or repeat return then true until while"


def language_for(name: str) -> str:
    """The editor language for a file name (by extension); "" is plain text."""
    return _BY_EXTENSION.get(Path(name).suffix.lower(), "")


def _words(words: str) -> str:
    return r"(?P<keyword>\b(?:" + "|".join(words.split()) + r")\b)"


# One alternation per language (leftmost wins; a group's role is its name before "__"). Groups ml1 / ml2 open a
# multi-line construct and are handled apart from the others.
_PATTERNS = {
    "toml": re.compile(
        r"(?P<ml1>\"\"\")|(?P<ml2>''')|(?P<string__a>\"(?:[^\"\\]|\\.)*\"?|'[^']*'?)|(?P<comment>#.*)"
        r"|(?P<header>^\s*\[\[?[^\]]*\]?\]?)|(?P<key>^\s*[\w.-]+(?=\s*=))|"
        + _words("true false inf nan")
        + "|"
        + _NUMBER
    ),
    "json": re.compile(
        r"(?P<key>\"(?:[^\"\\]|\\.)*\"(?=\s*:))|(?P<string>\"(?:[^\"\\]|\\.)*\"?)|(?P<comment>//.*)|"
        + _words("true false null")
        + "|"
        + _NUMBER
    ),
    "ini": re.compile(
        r"(?P<comment>^\s*[;#].*)|(?P<header>^\s*\[[^\]]*\]?)|(?P<key>^[ \t]*[^\s=:\[;#][^=:]*?(?=[ \t]*[=:]))"
        r"|(?P<string>\"(?:[^\"\\]|\\.)*\"|'[^']*')|" + _words("true false yes no on off") + "|" + _NUMBER
    ),
    "lua": re.compile(
        r"(?P<ml1>--\[=*\[)|(?P<comment>--.*)|(?P<ml2>\[=*\[)|(?P<string__a>\"(?:[^\"\\]|\\.)*\"?|'(?:[^'\\]|\\.)*'?)"
        r"|(?P<keyword__f>\bfunction\b)(?:\s+(?P<header>[A-Za-z_][\w.:]*))?|" + _words(_LUA_WORDS) + "|" + _NUMBER
    ),
    "markdown": re.compile(
        r"(?P<header>^\s{0,3}#{1,6}\s.*)|(?P<comment>^\s*>.*)|(?P<number>^\s*(?:[-*+]|\d+\.)\s)|(?P<string>`[^`]+`)"
        r"|(?P<keyword>\*\*[^*]+\*\*|__[^_]+__)|(?P<key>\[[^\]]*\]\([^)]*\))"
    ),
}

LANGUAGES = tuple(_PATTERNS)

# Carry-over states: toml 1 = inside """, 2 = inside '''; lua 10 + n = a long comment, 30 + n = a long string, n =
# the number of = signs; markdown 1 = inside a code fence. Each maps to (closing text, role).
_OPEN: dict[str, dict[int, tuple[str, str]]] = {
    "toml": {1: ('"""', "string"), 2: ("'''", "string")},
    "lua": {
        **{10 + n: ("]" + "=" * n + "]", "comment") for n in range(10)},
        **{30 + n: ("]" + "=" * n + "]", "string") for n in range(10)},
    },
}


def _open_state(language: str, opener: str) -> int:
    if language == "toml":
        return 1 if opener == '"""' else 2
    return (10 if opener.startswith("--") else 30) + min(opener.count("="), 9)


def _emit(m: re.Match[str], spans: list[Span]) -> None:
    for name in m.re.groupindex:
        if not name.startswith("ml") and m.end(name) > m.start(name) >= 0:
            spans.append((m.start(name), m.end(name) - m.start(name), name.split("__")[0]))


def highlight_line(language: str, line: str, state: int = 0) -> tuple[list[Span], int]:
    """(spans, state after the line). State is 0 outside a multi-line string, comment or code fence; otherwise the
    carry-over, an int a QTextBlock can store. Spans are in order; only a lua function name overlaps (its keyword)."""
    spans: list[Span] = []
    rx = _PATTERNS.get(language)
    if rx is None:
        return spans, 0
    if language == "markdown":
        if line.lstrip().startswith("```"):
            return [(0, len(line), "string")], 0 if state else 1
        if state:
            return [(0, len(line), "string")], 1
        for m in rx.finditer(line):
            _emit(m, spans)
        return spans, 0
    pos = 0
    if state:  # inside a multi-line construct: look for where it ends
        closing, role = _OPEN[language][state]
        end = line.find(closing)
        if end < 0:
            return [(0, len(line), role)], state
        pos = end + len(closing)
        spans.append((0, pos, role))
    while pos < len(line):
        m = rx.search(line, pos)
        if m is None:
            break
        opener = m.groupdict().get("ml1") or m.groupdict().get("ml2")
        if opener:
            role = "comment" if opener.startswith("--") else "string"
            closing = "]" + "=" * opener.count("=") + "]" if language == "lua" else opener
            end = line.find(closing, m.end())
            if end < 0:
                spans.append((m.start(), len(line) - m.start(), role))
                return spans, _open_state(language, opener)
            spans.append((m.start(), end + len(closing) - m.start(), role))
            pos = end + len(closing)
            continue
        _emit(m, spans)
        pos = max(m.end(), pos + 1)
    return spans, 0


# ------------------------------------------------------------------------------------------------ parse errors
def _mark(text: str) -> str:
    """Marks a string for translation; tr() runs when the message is built (the language is installed by then)."""
    return text


_TOML_WORDS = (
    ("Expected '=' after a key", _mark("a key is missing its value")),
    ("Unterminated string", _mark("a text value is missing its closing quote")),
    ("Invalid statement", _mark("this line is not a setting or a [section]")),
    ("Cannot overwrite a value", _mark("this name is already set above")),
    ("Cannot declare", _mark("this name is already set above")),
    ("Invalid value", _mark("this value is not text in quotes, a number, true or false")),
    ("Expected newline", _mark("there is extra text after the value")),
    ("Unclosed array", _mark("a list is missing its closing bracket")),
    ("Unclosed inline table", _mark("a { } group is missing its closing brace")),
    ("Invalid initial character for a key part", _mark("a name is empty or starts with a wrong character")),
)
_JSON_WORDS = (
    ("Expecting property name", _mark("a name must be in double quotes (or there is a comma too many)")),
    ("Expecting ',' delimiter", _mark("a comma is missing here")),
    ("Expecting ':' delimiter", _mark("a colon is missing after the name")),
    ("Expecting value", _mark("a value is missing here")),
    ("Unterminated string", _mark("a text value is missing its closing quote")),
    ("Illegal trailing comma", _mark("there is a comma before the closing bracket")),
    ("Extra data", _mark("there is extra text after the end")),
    ("Invalid control character", _mark("a text value contains a line break")),
    ("Invalid \\escape", _mark("a backslash in a text value is not a valid escape")),
)


def _why(message: str, table: tuple[tuple[str, str], ...]) -> str:
    for key, words in table:
        if message.startswith(key):
            return tr(words)
    return message.split(" (at ")[0]  # the library's own sentence when there is no plain one


def _line(line: int | None, why: str) -> tuple[int, str]:
    line = line or 1
    return line, tr("Line {line}: {why}").format(line=line, why=why)


def first_error(language: str, text: str) -> tuple[int, str] | None:
    """(line, plain-words message) of the first parse error in a TOML, JSON or INI text, or None when it parses (or
    the language is not checked). The line is 1-based."""
    try:
        if language == "toml":
            tomllib.loads(text)
        elif language == "json":
            json.loads(text)
        elif language == "ini":
            configparser.ConfigParser(interpolation=None, allow_no_value=True).read_string(text)
    except tomllib.TOMLDecodeError as e:
        message = e.args[0] if e.args else ""
        found = re.search(r"line (\d+)", message)
        line = getattr(e, "lineno", None) or (int(found.group(1)) if found else 1)
        lines = text.splitlines()
        if message.startswith("Invalid value") and lines[min(line, len(lines)) - 1].rstrip().endswith("="):
            return _line(line, tr("a key is missing its value"))
        return _line(line, _why(message, _TOML_WORDS))
    except json.JSONDecodeError as e:
        return _line(e.lineno, _why(e.msg, _JSON_WORDS))
    except configparser.MissingSectionHeaderError:
        return None  # many game .ini files keep settings above any [section]: not an error here
    except configparser.DuplicateOptionError as e:
        return _line(e.lineno, tr("this setting is listed twice in the same [section]"))
    except configparser.DuplicateSectionError as e:
        return _line(e.lineno, tr("this [section] is listed twice"))
    except configparser.ParsingError as e:
        return _line(e.errors[0][0] if e.errors else 1, tr("this line is not a setting or a [section]"))
    return None
