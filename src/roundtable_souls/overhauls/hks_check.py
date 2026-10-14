"""Game-level checks of a composed character script (backlog H2): calls the game can't resolve, and env/act command
IDs the game doesn't handle. Warnings only: nothing here refuses a build.

A character script's calls resolve to (game-model/havok-script.md): the functions the game's exe gives it (shipped as
data by the exe's version, game.knowledge), the four shared scripts the game always loads with it (read from the
installed game's own bytecode, or a package's text copy when one ships it), the script itself, and functions a mod's
DLL registers. The launcher cannot see the last kind: a hook step may name them (`natives`, from the mod's own
config); otherwise the warning says a mod's DLL may provide them. A function the script tests before calling it
(`type(F) == "function"`, `F == nil`, `F ~= nil`) is one it knows may be missing (another mod's, used when that mod is
there): its calls are not reported.

The composed text is compiled with Lua 5.1 (never run) and its bytecode read (formats.hks): which globals it calls and
sets, and the constant first argument of env, isenv and act calls. A script Lua 5.1 can't compile (Havok-only syntax,
see lua_check) is not checked here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from roundtable_souls import formats
from roundtable_souls.formats import hks
from roundtable_souls.game import archives as gamearchive
from roundtable_souls.game import knowledge
from roundtable_souls.overhauls import lua_check
from roundtable_souls.overhauls.hooks import Composed

SHARED = ("c9997", "common_define", "modifier", "c0000_talk")  # loaded with every character script
EXAMPLES = 5  # names given in a warning; the rest are counted
_ENV = frozenset({"env", "isenv"})
_WATCHED = frozenset({"env", "isenv", "act"})
_TESTED = (
    re.compile(r"\btype\s*\(\s*([A-Za-z_]\w*)\s*\)"),
    re.compile(r"\b([A-Za-z_]\w*)\s*[~=]=\s*nil\b"),
    re.compile(r"\bnil\s*[~=]=\s*([A-Za-z_]\w*)\b"),
)


@dataclass
class Shared:
    """The functions the shared scripts define, and the scripts that could not be read (calls are then not checked:
    a function from one of them would look undefined)."""

    functions: set[str] = field(default_factory=set)
    unread: list[str] = field(default_factory=list)


def shared_functions(game_dir: Path | None, folder: str, built: Path | None = None) -> Shared:
    """The shared scripts' functions: a package's copy in the built script folder (`built`) when there is one, text or
    bytecode, else the installed game's own (`folder` in its archives: "action/script")."""
    out = Shared()
    for name in SHARED:
        rel = f"{folder}/{name}.hks"
        try:
            local = built / f"{name}.hks" if built is not None else None
            data = local.read_bytes() if local is not None and local.is_file() else gamearchive.read(game_dir, rel)
            if data is None:
                out.unread.append(rel)
                continue
            if hks.is_hks_bytecode(data):
                out.functions.update(hks.function_names(data))
            else:
                facts = _facts(data.decode("utf-8-sig", errors="replace"))
                if facts is None:
                    out.unread.append(rel)
                else:
                    out.functions.update(facts.defined)
        except OSError, formats.FormatError, gamearchive.ArchiveError:
            out.unread.append(rel)
    return out


def _facts(text: str) -> hks.Lua51Facts | None:
    """The bytecode facts of a text script, or None when Lua 5.1 can't compile it (Havok's integer literals are read
    as 0 first, as lua_check does)."""
    from lupa import lua51

    plain = lua_check.plain_lua(text)
    runtime_type: Any = lua51.LuaRuntime  # its stubs lack `encoding`: None gives bytes, as string.dump needs
    runtime = runtime_type(encoding=None, unpack_returned_tuples=False)  # compiled and dumped, never run
    try:
        chunk = runtime.compile(plain.encode("utf-8"))
    except lua51.LuaSyntaxError:
        return None
    dump = runtime.globals().string.dump(chunk)
    return hks.lua51_facts(bytes(dump), _WATCHED)


def _tested(text: str) -> set[str]:
    """The names the script tests for being there before using them (type(F), F == nil, F ~= nil)."""
    return {m.group(1) for line in text.split("\n") for r in _TESTED for m in r.finditer(line.split("--")[0])}


def _native(name: str, declared: Sequence[str]) -> bool:
    return any(name.startswith(d[:-1]) if d.endswith("*") else name == d for d in declared)


def check(
    entry: str, composed: Composed, lists: knowledge.Lists, shared: Shared, natives: Sequence[str] = ()
) -> list[str]:
    """Warnings for the composed script `entry` ("action/script/c0000.hks"): calls of functions defined nowhere the
    game looks, and env/act IDs the game doesn't handle. natives: functions a mod's DLL gives the script, declared in
    its config (a trailing * matches a prefix)."""
    facts = _facts(composed.text)
    if facts is None:
        return []  # lua_check already said what it could not read
    caveat = f" ({lists.caveat})" if lists.caveat else ""
    out: list[str] = []

    def where(line: int) -> str:
        part = composed.part_at(line)
        return f", in what {part.who} added" if part is not None and len(composed.parts) > 1 else ""

    if shared.unread:
        out.append(
            f"{entry}: calls were not checked: the game's {', '.join(shared.unread)} could not be read, so what "
            "it defines is not known"
        )
    else:
        known = facts.defined | shared.functions | set(lists.lists.hks_natives) | _tested(composed.text)
        first: dict[str, int] = {}
        for name, line in facts.calls:
            if name not in known and not _native(name, natives):
                first.setdefault(name, line)
        if first:
            names = [f"{n} (line {line}{where(line)})" for n, line in first.items()]
            shown = ", ".join(names[:EXAMPLES]) + (
                f" and {len(names) - EXAMPLES} more" if len(names) > EXAMPLES else ""
            )
            fn = "a function" if len(names) == 1 else f"{len(names)} functions"
            out.append(
                f"{entry} calls {fn} defined nowhere the game looks (this script, the game's shared scripts, the "
                f"game's own functions): {shown}. In game such a call is an error each time it runs, unless a mod's "
                f"DLL provides the function{caveat}"
            )
    env, act = set(lists.lists.hks_env_ids), set(lists.lists.hks_act_ids) | set(lists.lists.hks_act_ids_tolerated)
    odd: dict[tuple[str, float], int] = {}
    for name, value, line in facts.first_args:
        handled = env if name in _ENV else act
        if not (value.is_integer() and int(value) in handled):
            odd.setdefault((name, value), line)
    for (name, value), line in odd.items():
        shown = int(value) if value.is_integer() else value
        out.append(
            f"{entry} line {line}{where(line)}: {name}({shown}, ...) uses an ID the game doesn't handle; what the "
            f"game does with it isn't known{caveat}"
        )
    return out
