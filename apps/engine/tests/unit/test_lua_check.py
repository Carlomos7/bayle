"""overhauls.lua_check: a composed character script is compiled as Lua 5.1 (never run) before a build is used; a
broken one is refused naming the file, the line and the part that introduced it. Texts only."""

from bayle.adapters.overhauls import lua_check
from bayle.adapters.overhauls.hooks import Hook, compose

ENTRY = "action/script/c0000.hks"
BASE = "-- the game's script\nfunction Update()\n    Move()\nend\n"
GOOD = "local FirstOriginalUpdate = Update\nfunction Update()\n    FirstOriginalUpdate()\nend\n"
BROKEN = "local SecondOriginalUpdate = Update\nfunction Update()\n    if ready then\n        Second()\nend\n"


def checked(base, hooks):
    return lua_check.check(ENTRY, base, "c0000.hks from anims", hooks, compose(base, "c0000.hks from anims", hooks))


def test_a_good_composition_compiles():
    assert checked(BASE, [Hook("First", GOOD)]) is None


def test_the_script_is_only_compiled_never_run():
    assert lua_check.syntax_error('error("this would stop if it ran")\nos.exit(1)\n') is None


def test_a_broken_fragment_is_named_with_its_own_line():
    said = checked(BASE, [Hook("First", GOOD), Hook("Second", BROKEN)])
    assert said is not None
    assert said.startswith(
        "action/script/c0000.hks would not load in game: Second's script has a syntax error at its line 5 ("
    )
    assert "'end' expected" in said


def test_a_broken_base_is_named():
    said = checked("function Update()\n", [Hook("First", GOOD)])
    assert said is not None and said.startswith(
        "action/script/c0000.hks would not load in game: c0000.hks from anims has a syntax error at line 1 ("
    )


def test_parts_that_compile_alone_but_not_together_are_traced_to_the_part():
    # Lua 5.1 allows return only as a block's last statement: each part compiles, the two joined do not
    base, fragment = "x = 1\nreturn x\n", "y = 2\n"
    assert lua_check.syntax_error(base) is None and lua_check.syntax_error(fragment) is None
    said = checked(base, [Hook("First", fragment)])
    assert said is not None
    assert said.startswith(
        "action/script/c0000.hks would not load in game: a syntax error at line 4, in what First added ("
    )
    assert said.endswith("Each part reads on its own, so it comes from putting them together.")


def test_an_error_line_maps_to_the_part_it_came_from():
    composed = compose(BASE, "c0000.hks from anims", [Hook("First", GOOD), Hook("Second", BROKEN)])
    found = lua_check.syntax_error(composed.text)
    assert found is not None
    part = composed.part_at(found.line)
    assert part is not None and part.who == "Second"


def test_syntax_errors_carry_the_line():
    for text, line in [
        ("local a = 1\nlocal b = = 2\n", 2),
        ('local s = "abc\nprint(s)\n', 1),
        ("x = (1 + 2))\n", 1),
        ("function f()\n  if x then\n    y = 1\n", 3),  # at the end: the last real line
    ]:
        found = lua_check.syntax_error(text)
        assert found is not None and found.line == line, (text, found)


def test_havok_integer_literals_are_read_as_numbers_and_the_rest_is_still_checked():
    hooks = [Hook("First", "local mask = 0x10hi\nlocal big = 0x100HI -- not 0x100hl\n")]
    composed = compose(BASE, "c0000.hks from anims", hooks)
    assert checked(BASE, hooks) is None
    assert lua_check.havok_syntax(ENTRY, composed) == [
        "action/script/c0000.hks line 6 (in what First added) uses Havok Script syntax (hi numbers) that this "
        "check can't read; the rest of the script was checked.",
        "action/script/c0000.hks line 7 (in what First added) uses Havok Script syntax (hi numbers) that this "
        "check can't read; the rest of the script was checked.",
    ]
    broken = [Hook("First", "local mask = 0x10hi\nlocal = 2\n")]  # a real error after a literal is still refused
    said = checked(BASE, broken)
    assert said is not None and "First's script has a syntax error at its line 2" in said


def test_hl_numbers_are_refused_since_the_game_never_compiles_them():
    said = checked(BASE, [Hook("First", "local ok = 1\nlocal big = 0x100HL\n")])
    assert said == (
        "action/script/c0000.hks would not load in game: First's script uses a 0x...hl number, which the game never "
        "compiles (60-bit numbers aren't supported in this game) at its line 2."
    )
    said = checked("local big = 0x10hl\n" + BASE, [])
    assert said is not None and "c0000.hks from anims uses a 0x...hl number" in said and "at line 1." in said


def test_hstructure_and_hmake_are_warned_about_not_refused():
    text = "hstructure Point\n  x : number\nend\nlocal p = hmake Point { x = 1 }\n"
    hooks = [Hook("First", text)]
    assert checked(BASE, hooks) is None
    (warning,) = lua_check.havok_syntax(ENTRY, compose(BASE, "c0000.hks from anims", hooks))
    assert warning == (
        "action/script/c0000.hks line 6 (in what First added) uses Havok Script syntax (hstructure) that this check "
        "can't read; the lines before it were checked."
    )


def test_a_real_error_before_any_havok_form_is_still_refused():
    said = checked("local = 1\nhstructure Point\nend\n", [])
    assert said is not None and "has a syntax error at line 1" in said


def test_a_plain_script_has_no_havok_warning():
    assert lua_check.havok_syntax(ENTRY, compose(BASE, "c0000.hks from anims", [Hook("First", GOOD)])) == []
