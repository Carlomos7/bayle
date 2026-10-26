"""Character scripts as bytecode: Havok Script 2018.1 (how the game ships its scripts) and Lua 5.1 (what a text script
compiles to with the reference compiler, for checking it).

Havok Script 2018.1 (layout from the game's own loader; tools/roundtable-dev/rea-eldenring/game-model/havok-script.md):
big-endian, size_t 8 bytes, numbers 4-byte floats. A header ("\\x1bLua", 0x51, format 0x0E, ..., byte 12 = 3), a type
table, then one function prototype, recursively: counts, instructions, constants, debug info (with the function's
name) and the child prototypes. function_names() reads every prototype's name; the header check catches a future
format change.

Lua 5.1 (lupa's string.dump on this machine: little-endian, size_t 8, numbers doubles): lua51_facts() reads which
globals a chunk calls and sets, and the constant first argument of calls of chosen functions, with their lines.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from bayle.adapters.formats import FormatError

HKS_SIGNATURE = b"\x1bLua\x51\x0e"
_HKS_FEATURE = 3  # byte 12 of the shipped scripts' header
_MAX_DEPTH = 128  # the game's own limit ("code too deep")


def is_hks_bytecode(data: bytes) -> bool:
    return data[:6] == HKS_SIGNATURE


class _Reader:
    def __init__(self, data: bytes, big: bool) -> None:
        self.b, self.i, self.e = data, 0, ">" if big else "<"

    def take(self, fmt: str):
        v = struct.unpack_from(self.e + fmt, self.b, self.i)
        self.i += struct.calcsize(fmt)
        return v[0]

    def string(self) -> str:
        n = self.take("Q")
        s = self.b[self.i : self.i + n]
        if len(s) != n:
            raise FormatError("a string runs past the end of the script")
        self.i += n
        return s[:-1].decode("utf-8", "replace") if n else ""


def function_names(data: bytes) -> list[str]:
    """The name of every function a Havok Script 2018.1 script defines, from its debug info ("(main chunk)" and
    unnamed ones left out). FormatError when the file is not that format or ends early."""
    if not is_hks_bytecode(data) or len(data) < 14 or data[12] != _HKS_FEATURE:
        raise FormatError("not Havok Script 2018.1 bytecode as the game ships it (the format may have changed)")
    r = _Reader(data, big=True)
    r.i = 14
    try:
        for _ in range(r.take("I")):  # the type table
            r.take("I")
            size = r.take("I")  # read before moving on: `r.i += r.take(...)` would add to the old position
            r.i += size
        names: list[str] = []
        _hks_function(r, names, 0)
    except struct.error as e:
        raise FormatError(f"the script ends early ({e})") from e
    return names


def _hks_function(r: _Reader, names: list[str], depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise FormatError("functions nested deeper than the game allows")
    r.take("I")  # upvalues
    r.take("I")  # parameters
    r.take("B")  # vararg flags
    r.take("I")  # max stack
    count = r.take("Q")
    r.i = (r.i + 3) & ~3
    r.i += 4 * count
    for _ in range(r.take("I")):
        kind = r.take("B")
        if kind == 1:
            r.take("B")
        elif kind == 2:
            r.take("Q")
        elif kind == 3:
            r.take("f")
        elif kind == 4:
            r.string()
        elif kind != 0:
            raise FormatError(f"a constant of unknown type {kind}")
    if r.take("I"):  # debug info
        lines, locals_, upvalues = r.take("I"), r.take("I"), r.take("I")
        r.take("I")
        r.take("I")
        r.string()  # source
        name = r.string()
        if name and name != "(main chunk)":
            names.append(name)
        r.i += 4 * lines
        for _ in range(locals_):
            r.string()
            r.take("I")
            r.take("I")
        for _ in range(upvalues):
            r.string()
    for _ in range(r.take("I")):
        _hks_function(r, names, depth + 1)


# ----------------------------------------------------------------------------- Lua 5.1
_LOADK, _GETGLOBAL, _SETGLOBAL, _CALL, _TAILCALL = 1, 5, 7, 28, 29
# opcodes that do not write register A: SETGLOBAL, SETUPVAL, SETTABLE, JMP, EQ, LT, LE, TEST, RETURN, SETLIST, CLOSE
_KEEPS_A = {7, 8, 9, 22, 23, 24, 25, 26, 30, 34, 35}


@dataclass
class Lua51Facts:
    calls: list[tuple[str, int]] = field(default_factory=list)  # (global called, line)
    defined: set[str] = field(default_factory=set)  # globals the chunk sets
    first_args: list[tuple[str, float, int]] = field(default_factory=list)  # (function, constant first arg, line)


def lua51_facts(dump: bytes, watched: frozenset[str] = frozenset()) -> Lua51Facts:
    """What a Lua 5.1 chunk (string.dump's output, with its line info) does with globals. watched: functions whose
    constant numeric first argument is collected (env, act)."""
    if dump[:5] != b"\x1bLuaQ" or len(dump) < 12:
        raise FormatError("not Lua 5.1 bytecode")
    big = dump[6] == 0
    size_t, number = dump[8], dump[10]
    if dump[7] != 4 or dump[9] != 4 or size_t not in (4, 8) or number != 8:
        raise FormatError("Lua 5.1 bytecode with sizes this reader does not know")
    r = _Reader(dump, big)
    r.i = 12
    facts = Lua51Facts()
    try:
        _lua_function(r, "Q" if size_t == 8 else "I", facts, watched, 0)
    except struct.error as e:
        raise FormatError(f"the bytecode ends early ({e})") from e
    return facts


def _lua_function(r: _Reader, st: str, facts: Lua51Facts, watched: frozenset[str], depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise FormatError("functions nested too deep")

    def string() -> str:
        n = r.take(st)
        s = r.b[r.i : r.i + n]
        r.i += n
        return s[:-1].decode("utf-8", "replace") if n else ""

    string()  # source
    r.take("i")
    r.take("i")  # lines defined
    r.i += 4  # upvalues, parameters, vararg, max stack
    code = [r.take("I") for _ in range(r.take("i"))]
    constants: list = []
    for _ in range(r.take("i")):
        kind = r.take("B")
        if kind == 0:
            constants.append(None)
        elif kind == 1:
            constants.append(bool(r.take("B")))
        elif kind == 3:
            constants.append(r.take("d"))
        elif kind == 4:
            constants.append(string())
        else:
            raise FormatError(f"a constant of unknown type {kind}")
    for _ in range(r.take("i")):
        _lua_function(r, st, facts, watched, depth + 1)
    lines = [r.take("i") for _ in range(r.take("i"))]
    for _ in range(r.take("i")):  # locals
        string()
        r.take("i")
        r.take("i")
    for _ in range(r.take("i")):  # upvalue names
        string()
    _read_code(code, constants, lines, facts, watched)


def _read_code(code: list[int], constants: list, lines: list[int], facts: Lua51Facts, watched: frozenset[str]):
    def line(pc: int) -> int:
        return lines[pc] if pc < len(lines) else 0

    for pc, ins in enumerate(code):
        op, a, bx = ins & 0x3F, (ins >> 6) & 0xFF, ins >> 14
        if op == _SETGLOBAL and isinstance(constants[bx], str):
            facts.defined.add(constants[bx])
        if op != _GETGLOBAL or not isinstance(constants[bx], str):
            continue
        name = constants[bx]
        first: float | None = None
        argued = False  # whether the first argument's register was written yet
        for later in code[pc + 1 :]:
            lop, la = later & 0x3F, (later >> 6) & 0xFF
            if la == a + 1 and not argued and lop not in _KEEPS_A:
                argued = True
                k = constants[later >> 14] if lop == _LOADK else None
                first = k if isinstance(k, float) else None
            if la == a and lop in (_CALL, _TAILCALL):
                facts.calls.append((name, line(pc)))
                if name in watched and first is not None:
                    facts.first_args.append((name, first, line(pc)))
                break
            if la == a and lop not in _KEEPS_A:
                break  # register A gets something else: the global was only read
