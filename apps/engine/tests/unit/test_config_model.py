"""formats.config_model: a file read as a form and written back changes only the edited value's characters (INI by
its own lines, TOML through tomlkit: nested tables, dotted keys, inline tables, arrays, arrays of tables)."""

import pytest

from bayle.formats import config_model

INI = (
    "﻿; top note\r\n"
    "[GAMEPLAY]\r\n"
    "; Invaders join.  0 = FALSE 1 = TRUE\r\n"
    "allow_invaders = 1   \r\n"
    "\r\n"
    "; Nameplates. 0 = Normal | 1 = None | 2 = Ping\r\n"
    "overhead_player_display=0\r\n"
    "[PASSWORD]\r\n"
    "cooppassword = secret ; not a comment in an ini value\r\n"
    "dup = 1\r\n"
    "dup = 2\r\n"
)

TOML = (
    "# settings  (default: 60)\n"
    "fps =   60   # frames\n"
    "name = 'literal'\n"
    'title = "say \\"hi\\""\n'
    "tags = ['a', 'b']\n"
    "\n"
    "[window]  # the window\n"
    "# Show it.\n"
    "on = true\n"
    "scale = 1.5\n"
    "sizes = [1, 2,\n"
    "  3]\n"
    "inline = { a = 1, b = 'x' }\n"
    "a.b = 2\n"
    "[window.deep]\n"
    "level = 3  # keep me\n"
    "\n"
    "[[builds]]\n"
    "id = 'x'\n"
    "\n"
    "# the second\n"
    "[[builds]]\n"
    "id = 'y'\n"
    "when = 1979-05-27\n"
    'note = """a\n'
    'b"""\n'
)


def test_only_the_edited_value_changes_in_ini():
    assert config_model.parse(INI, config_model.INI).text() == INI  # read and written back untouched: identical
    for key, value in (("allow_invaders", "0"), ("overhead_player_display", "2"), ("cooppassword", "pw2")):
        doc = config_model.parse(INI, config_model.INI)
        item = doc.find(key)
        assert item is not None and not item.readonly
        line, start, end = doc.lines[item.line], item.start, item.end
        assert doc.set(key, value)
        new = doc.text()
        before, after = INI.splitlines(keepends=True), new.splitlines(keepends=True)
        changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        assert changed == [item.line]  # one line, and only the value's characters in it
        assert after[item.line][:start] == line[:start] and after[item.line][item.end :] == line[end:]
        assert config_model.parse(new, config_model.INI).find(key).value == value
    ini = config_model.parse(INI, config_model.INI)
    assert ini.find("allow_invaders").kind == "bool" and ini.find("overhead_player_display").kind == "choice"
    assert ini.find("dup").readonly  # set twice: text only


def test_nested_toml_round_trip_keeps_every_byte_but_the_edited_value():
    doc = config_model.parse(TOML, config_model.TOML)
    assert doc.text() == TOML
    assert [s.name for s in doc.sections] == [
        "",
        "window",
        "window.inline",
        "window.a",
        "window.deep",
        "[[builds]] #1",
        "[[builds]] #2",
    ]
    assert doc.find("fps").default == "60" and doc.find("title").value == 'say "hi"'
    assert doc.find("on", "window").desc == "Show it." and doc.find("scale", "window").kind == "float"
    assert doc.find("sizes", "window").value == "1, 2, 3" and doc.find("tags").value == "a, b"
    assert doc.find("b", "window.a").value == "2" and doc.find("a", "window.inline").kind == "int"
    assert doc.find("id", "[[builds]] #2").value == "y"
    for key in ("when", "note"):
        assert doc.find(key, "[[builds]] #2").readonly, key
    edits = [
        ("fps", 144, ""),
        ("name", "new", ""),
        ("on", False, "window"),
        ("level", 4, "window.deep"),
        ("b", 9, "window.a"),
        ("a", 5, "window.inline"),
        ("id", "z", "[[builds]] #2"),
        ("tags", "c, d, e", ""),
    ]
    for key, value, section in edits:
        fresh = config_model.parse(TOML, config_model.TOML)
        assert fresh.set(key, value, section)
        new = fresh.text()
        before, after = TOML.splitlines(keepends=True), new.splitlines(keepends=True)
        changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
        assert len(changed) == 1, (key, changed)  # one line differs; the rest is byte for byte the same
        assert config_model.parse(new, config_model.TOML).find(key, section).value == (
            str(value).lower() if isinstance(value, bool) else str(value)
        )
    doc.set("level", 4, "window.deep")
    assert "level = 4  # keep me\n" in doc.text()
    with pytest.raises(ValueError, match="only be changed as text"):
        doc.set("when", "2000-01-01", "[[builds]] #2")
    with pytest.raises(ValueError, match="line break"):
        doc.set("name", "a\nb")
    assert config_model.parse("a = [", config_model.TOML).sections == []  # not TOML: the text editor only


def test_a_value_with_a_line_break_is_refused_and_the_text_is_unchanged():
    doc = config_model.parse(INI, config_model.INI)
    for bad in ("pw\nx = 1", "pw\rx = 1"):
        with pytest.raises(ValueError, match="line break"):
            doc.set("cooppassword", bad)
        assert doc.text() == INI
