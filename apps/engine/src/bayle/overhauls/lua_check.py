"""A syntax check of the scripts a hook composes (overhauls.hooks), so a broken composition is refused when the
build is made instead of failing silently in the game.

The game's character scripts (HKS) are Havok Script: Lua 5.1 with Havok's additions. The check compiles the text with
Lua 5.1 itself (lupa's lua51 module: the reference compiler, loaded only, never run): nothing of the script executes.
Havok's own forms are not Lua 5.1 (docs/decisions/0009, which supersedes 0006): the reserved words `hstructure` and
`hmake`, and the integer literals `0x...hi` and `0x...hl`. The `hi` literals are read as 0 so the rest is still
checked; a failure at or after a line using `hstructure`/`hmake` is not refused (this check can't read past it). Either
way havok_syntax() says which line it could not read, as a warning. A `0x...hl` literal is refused: the game's compiler
never accepts one (it needs a 64-bit option this game was built without; game-model/havok-script.md).

check() parses the base and each hook's fragment on its own first, so a broken fragment is named as the cause even
when the whole would also fail, then the composed text, whose error line is traced back to the part it came from.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from bayle.overhauls.hooks import Composed, Hook

_WHERE = re.compile(r'^\[string "[^"]*"\]:(\d+):\s*(.*)$', re.S)
_HAVOK_LITERAL = re.compile(r"\b0x[0-9A-Fa-f]+[hH][iIlL]\b")  # Havok Script integer literals (60-bit: ...hl)
_HAVOK_WORD = re.compile(r"\b(hstructure|hmake)\b")
_HL_LITERAL = re.compile(r"\b0x[0-9A-Fa-f]+[hH][lL]\b")  # never compiles in the game


@dataclass(frozen=True)
class SyntaxProblem:
    line: int  # 1-based, in the text checked
    message: str  # Lua's own words ("'end' expected (to close 'if' at line 2) near <eof>")


def syntax_error(text: str) -> SyntaxProblem | None:
    """The first syntax error in a Lua 5.1 chunk, or None when it compiles."""
    from lupa import lua51

    runtime = lua51.LuaRuntime(unpack_returned_tuples=False)  # nothing is run: the defaults do not matter
    try:
        runtime.compile(text)
    except lua51.LuaSyntaxError as e:
        said = str(e).strip()
        m = _WHERE.match(said)
        if m is None:
            return SyntaxProblem(0, said)
        # an error at the end of the text is reported on the line after its last newline: the last real line
        last = max(text.count("\n") + (0 if text.endswith("\n") else 1), 1)
        return SyntaxProblem(min(int(m.group(1)), last), m.group(2).strip())
    return None


@dataclass(frozen=True)
class HavokLine:
    line: int  # 1-based
    forms: tuple[str, ...]  # what is there: "hstructure", "hmake", "hi numbers"
    checked_after: bool  # whether the lines after it were checked too


def _havok(text: str) -> tuple[str, list[HavokLine]]:
    """The text with Havok's integer literals read as 0, and each line using a Havok-only form."""
    lines: dict[int, set[str]] = {}
    for n, line in enumerate(text.split("\n"), 1):
        for m in _HAVOK_WORD.finditer(line):
            lines.setdefault(n, set()).add(m.group(1))
        if _HAVOK_LITERAL.search(line):
            lines.setdefault(n, set()).add("hi numbers")
    order = ("hstructure", "hmake", "hi numbers")
    found = [HavokLine(n, tuple(f for f in order if f in forms), True) for n, forms in sorted(lines.items())]
    return _HAVOK_LITERAL.sub("0", text), found


def plain_lua(text: str) -> str:
    """The text with Havok Script's integer literals (0x...hi, 0x...hl) read as 0, so Lua 5.1 can compile the rest."""
    return _havok(text)[0]


def _hl_line(text: str) -> int | None:
    """The first line using a 0x...hl literal outside a comment, or None."""
    for n, line in enumerate(text.split("\n"), 1):
        if _HL_LITERAL.search(line.split("--")[0]):
            return n
    return None


_HL_WHY = "a 0x...hl number, which the game never compiles (60-bit numbers aren't supported in this game)"


def _lua_or_havok(text: str) -> tuple[SyntaxProblem | None, list[HavokLine]]:
    """(a real syntax error, or None; the Havok-only lines). A failure at or after the first line using hstructure or
    hmake is not counted: this check cannot read those; the lines before it compiled."""
    plain, havok = _havok(text)
    found = syntax_error(plain)
    if found is None:
        return None, havok
    words = [h for h in havok if {"hstructure", "hmake"} & set(h.forms)]
    if words and found.line >= words[0].line:
        first = words[0]
        return None, [h for h in havok if h.line < first.line] + [HavokLine(first.line, first.forms, False)]
    return found, havok


def havok_syntax(entry: str, composed: Composed) -> list[str]:
    """Warnings for the lines of the composed script that use Havok Script syntax Lua 5.1 can't read (none when it
    uses none), each naming the line and the part it came from."""
    _found, havok = _lua_or_havok(composed.text)
    out = []
    for h in havok:
        part = composed.part_at(h.line)
        where = f" (in what {part.who} added)" if part is not None and len(composed.parts) > 1 else ""
        rest = "the rest of the script was checked" if h.checked_after else "the lines before it were checked"
        out.append(
            f"{entry} line {h.line}{where} uses Havok Script syntax ({' / '.join(h.forms)}) that this check can't "
            f"read; {rest}."
        )
    return out


def check(entry: str, base: str, base_from: str, hooks: Sequence[Hook], composed: Composed) -> str | None:
    """Why the composed entry script would not load, naming the file, the line and the part that introduced it; None
    when it compiles (Havok-only syntax aside: see havok_syntax). entry: how the file is named
    ("action/script/c0000.hks")."""
    line = _hl_line(base)
    if line is not None:
        return f"{entry} would not load in game: {base_from} uses {_HL_WHY} at line {line}."
    for hook in hooks:
        line = _hl_line(hook.text.removeprefix("\ufeff"))
        if line is not None:
            return f"{entry} would not load in game: {hook.who}'s script uses {_HL_WHY} at its line {line}."
    found = _lua_or_havok(base)[0]
    if found is not None:
        return f"{entry} would not load in game: {base_from} has a syntax error at line {found.line} ({found.message})."
    for hook in hooks:
        found = _lua_or_havok(hook.text.removeprefix("﻿"))[0]
        if found is not None:
            return (
                f"{entry} would not load in game: {hook.who}'s script has a syntax error at its line {found.line} "
                f"({found.message})."
            )
    found = _lua_or_havok(composed.text)[0]
    if found is None:
        return None
    part = composed.part_at(found.line)
    who = part.who if part is not None else "the joins between the scripts"
    return (
        f"{entry} would not load in game: a syntax error at line {found.line}, in what {who} added "
        f"({found.message}). Each part reads on its own, so it comes from putting them together."
    )
