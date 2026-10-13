"""formats.hks and overhauls.hks_check (backlog H2): the composed character script's calls against what the game
gives it, and its env/act IDs against the game's lists. Synthetic bytecode and lists only."""

import struct

import pytest

from roundtable_souls import formats
from roundtable_souls.formats import hks
from roundtable_souls.game import knowledge
from roundtable_souls.overhauls import hks_check
from roundtable_souls.overhauls.hooks import Hook, compose

ENTRY = "action/script/c0000.hks"


def _string(s: str) -> bytes:
    raw = s.encode() + b"\0"
    return struct.pack(">Q", len(raw)) + raw


def _proto(at: int, name: str, children: tuple[str, ...] = ()) -> bytes:
    """One Havok Script 2018.1 function prototype starting at offset `at`: no code or constants, debug info with its
    name, then its children (named, no children of their own)."""
    out = struct.pack(">IIBI", 0, 0, 0, 2) + struct.pack(">Q", 0)
    out += b"\0" * (-(at + len(out)) % 4)  # the instructions start on a multiple of 4 of the file
    out += struct.pack(">I", 0)  # constants
    out += struct.pack(">I", 1) + struct.pack(">IIIII", 0, 0, 0, 0, 0) + _string("@x.lua") + _string(name)
    out += struct.pack(">I", len(children))
    for child in children:
        out += _proto(at + len(out), child)
    return out


def hks_bytecode(*names: str) -> bytes:
    head = b"\x1bLua\x51\x0e\x00\x04\x08\x04\x04\x00\x03\x00"
    head += struct.pack(">I", 1) + struct.pack(">II", 0, 5) + b"TNIL\0"
    return head + _proto(len(head), "(main chunk)", names) + struct.pack(">III", 1, 0, 0)


def test_function_names_come_from_the_debug_info():
    assert hks.function_names(hks_bytecode("ExecTalk", "ConvergeValue")) == ["ExecTalk", "ConvergeValue"]
    with pytest.raises(formats.FormatError):
        hks.function_names(b"\x1bLuaQ\x00" + b"\0" * 20)  # Lua 5.1, not the game's format
    with pytest.raises(formats.FormatError):
        hks.function_names(hks_bytecode("A")[:40])


def lists(caveat: str = "") -> knowledge.Lists:
    shipped = knowledge._exe_lists("eldenring").versions["2.7.1.0"]
    return knowledge.Lists(
        shipped.model_copy(
            update={
                "hks_env_ids": [105],
                "hks_act_ids": [1],
                "hks_act_ids_tolerated": [118],
                "hks_natives": ["env", "isenv", "act", "print"],
            }
        ),
        "2.7.1.0",
        caveat,
    )


BASE = "function Update()\n  ExecTalk()\n  env(105, 1)\nend\n"


def checked(fragment: str, shared=frozenset({"ExecTalk"}), natives=(), caveat: str = "") -> list[str]:
    composed = compose(BASE, "c0000.hks from anims", [Hook("Revive", fragment)])
    return hks_check.check(ENTRY, composed, lists(caveat), hks_check.Shared(set(shared)), natives)


def test_a_script_whose_calls_all_resolve_has_no_warning():
    assert checked("local function Mine() print(1) end\nfunction Other() Mine() Update() act(118) end\n") == []


def test_calls_of_functions_defined_nowhere_are_one_warning_naming_the_part():
    said = checked("NrrNative(1)\nNrrNative(2)\nMissing()\n")
    assert said == [
        "action/script/c0000.hks calls 2 functions defined nowhere the game looks (this script, the game's shared "
        "scripts, the game's own functions): NrrNative (line 6, in what Revive added), Missing (line 8, in what "
        "Revive added). In game such a call is an error each time it runs, unless a mod's DLL provides the function"
    ]
    assert checked("NrrNative(1)\nNrmStop()\n", natives=["NrrNative", "Nrm*"]) == []


def test_env_and_act_ids_the_game_does_not_handle_are_warned_about():
    said = checked("env(999, 1)\nact(2)\nact(118)\n", caveat="lists of 1.17.1 used, so this may be out of date")
    assert said == [
        "action/script/c0000.hks line 6, in what Revive added: env(999, ...) uses an ID the game doesn't handle; "
        "what the game does with it isn't known (lists of 1.17.1 used, so this may be out of date)",
        "action/script/c0000.hks line 7, in what Revive added: act(2, ...) uses an ID the game doesn't handle; what "
        "the game does with it isn't known (lists of 1.17.1 used, so this may be out of date)",
    ]


def test_unreadable_shared_scripts_mean_calls_are_not_checked():
    composed = compose(BASE, "c0000.hks from anims", [Hook("Revive", "Missing()\n")])
    said = hks_check.check(ENTRY, composed, lists(), hks_check.Shared(set(), ["action/script/c9997.hks"]))
    assert said == [
        "action/script/c0000.hks: calls were not checked: the game's action/script/c9997.hks could not be read, so "
        "what it defines is not known"
    ]


def test_a_script_lua_51_cannot_compile_is_left_to_lua_check():
    assert checked("hstructure Point\nend\nMissing()\n") == []


def test_shared_functions_from_the_game_or_a_packages_copy(tmp_path, monkeypatch):
    games = {f"action/script/{n}.hks": hks_bytecode(f"From_{n}") for n in hks_check.SHARED}
    monkeypatch.setattr(hks_check.gamearchive, "read", lambda _d, rel: games.get(rel))
    built = tmp_path / "script"
    built.mkdir()
    (built / "modifier.hks").write_text("function ModText() end\nGlobalValue = 1\n", encoding="utf-8")
    got = hks_check.shared_functions(tmp_path, "action/script", built)
    assert got.unread == []
    assert got.functions == {"From_c9997", "From_common_define", "From_c0000_talk", "ModText", "GlobalValue"}
    del games["action/script/c0000_talk.hks"]
    assert hks_check.shared_functions(tmp_path, "action/script").unread == ["action/script/c0000_talk.hks"]


def test_lua51_facts_reads_calls_definitions_and_constant_first_arguments():
    facts = hks_check._facts("function Foo() Bar(1) env(105, 2) act(Baz) end\nlocal x = Qux\nprint(Quux(3))")
    assert facts is not None and facts.defined == {"Foo"}
    assert [n for n, _ in facts.calls] == ["Bar", "env", "act", "print", "Quux"]  # Qux and Baz are only read
    assert facts.first_args == [("env", 105.0, 1)]
