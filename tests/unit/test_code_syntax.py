"""The code editor's syntax: token ranges per language, multi-line carry-over, parse errors in plain words, and speed."""

import time

import pytest

from roundtable_souls.ui.code_syntax import first_error, highlight_line, language_for


def roles(language: str, text: str) -> list[tuple[str, str]]:
    out, state = [], 0
    for line in text.split("\n"):
        spans, state = highlight_line(language, line, state)
        out += [(line[a : a + n], r) for a, n, r in spans]
    return out


def test_language_by_extension():
    assert [language_for(n) for n in ("a.me3", "b.INI", "c.json", "c0000.hks", "README.md", "x.txt")] == [
        "toml", "ini", "json", "lua", "markdown", "",
    ]  # fmt: skip


def test_toml():
    got = roles("toml", '[[mods]]\nname = "a#b" # c\nn = 12\nok = true\ns = """x\ny"""')
    assert ("[[mods]]", "header") in got and ("name", "key") in got and ('"a#b"', "string") in got
    assert ("# c", "comment") in got and ("12", "number") in got and ("true", "keyword") in got
    assert ('"""x', "string") in got and ('y"""', "string") in got  # a multi-line string carries over


def test_lua_hks():
    got = roles("lua", "local function Foo.bar(x) --[[ c\nmore ]] return 0x1F end -- done")
    assert ("local", "keyword") in got and ("Foo.bar", "header") in got and ("--[[ c", "comment") in got
    assert ("more ]]", "comment") in got and ("0x1F", "number") in got and ("-- done", "comment") in got


def test_ini_json_markdown():
    assert roles("ini", "[S]\nk = 1\n; c") == [("[S]", "header"), ("k", "key"), ("1", "number"), ("; c", "comment")]
    assert ('"a"', "key") in roles("json", '{"a": null, "b": "x"}') and ("null", "keyword") in roles("json", "[null]")
    md = roles("markdown", "# T\n```\nx # y\n```\n`c`")
    assert ("# T", "header") in md and ("x # y", "string") in md and ("`c`", "string") in md


@pytest.mark.parametrize(
    ("language", "text", "line", "words"),
    [
        ("toml", "x = 1\ny = \n", 2, "a key is missing its value"),
        ("toml", "x = 1\nx = 2", 2, "already set"),
        ("json", '{\n"a" 1}', 2, "colon"),
        ("ini", "[a]\nb=1\n[a]\n", 3, "listed twice"),
    ],
)
def test_first_error_in_plain_words(language, text, line, words):
    found = first_error(language, text)
    assert found is not None and found[0] == line and words in found[1] and found[1].startswith(f"Line {line}:")


def test_valid_text_has_no_error():
    assert first_error("toml", "a = 1") is None and first_error("json", "{}") is None
    assert first_error("ini", "loose = 1\n") is None and first_error("lua", "x = (") is None


def test_25k_lines_highlight_quickly():
    text = "\n".join(
        f'function Act{i}() env(1, {i}) -- note\n    if x == "a" then return {i}.5 end end' for i in range(12500)
    )
    t = time.perf_counter()
    state = 0
    for line in text.split("\n"):
        _, state = highlight_line("lua", line, state)
    assert time.perf_counter() - t < 3.0
