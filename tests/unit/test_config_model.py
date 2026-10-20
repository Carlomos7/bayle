"""formats.config_model: a file read as a form and written back changes only the edited value's characters (the one
test the owner allowed for it, 2026-10-15: INI and flat TOML)."""

from roundtable_souls.formats import config_model

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
    "\n"
    "[window]\n"
    "on = true\n"
    "scale = 1.5\n"
    "list = [1, 2,\n"
    "  3]\n"
    "inline = { a = 1 }\n"
    "a.b = 2\n"
    "[[mods]]\n"
    "id = 'x'\n"
)


def test_only_the_edited_value_changes_in_ini_and_flat_toml():
    for text, lang, edits in (
        (
            INI,
            config_model.INI,
            [("allow_invaders", "0", None), ("overhead_player_display", "2", None), ("cooppassword", "pw2", None)],
        ),
        (
            TOML,
            config_model.TOML,
            [("fps", 144, None), ("name", "new", None), ("title", 'a "b"', None), ("on", False, "window")],
        ),
    ):
        assert config_model.parse(text, lang).text() == text  # read and written back untouched: identical
        for key, value, section in edits:
            doc = config_model.parse(text, lang)
            item = doc.find(key, section)
            assert item is not None and not item.readonly
            line, start, end = doc.lines[item.line], item.start, item.end
            assert doc.set(key, value, section)
            new = doc.text()
            before, after = text.splitlines(keepends=True), new.splitlines(keepends=True)
            changed = [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
            assert changed == [item.line]  # one line, and only the value's characters in it
            assert after[item.line][:start] == line[:start] and after[item.line][item.end :] == line[end:]
            reread = config_model.parse(new, lang).find(key, section)
            assert reread is not None and reread.value == (
                str(value).lower() if isinstance(value, bool) else str(value)
            )
    ini = config_model.parse(INI, config_model.INI)
    assert ini.find("allow_invaders").kind == "bool" and ini.find("overhead_player_display").kind == "choice"
    assert ini.find("dup").readonly  # set twice: text only
    toml = config_model.parse(TOML, config_model.TOML)
    assert toml.find("fps").default == "60" and toml.find("fps").value == "60"
    assert toml.find("title").value == 'say "hi"' and toml.find("scale", "window").kind == "float"
    for key in ("list", "inline", "a.b", "id"):
        assert toml.find(key).readonly, key
    assert toml.text() == TOML
