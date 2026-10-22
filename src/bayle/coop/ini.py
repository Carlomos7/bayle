"""The Seamless Co-op ini: password, difficulty scaling, every setting typed from its comment, and the whole-file share JSON.
The words the window shows for its settings are the Mod Configs presenter's (views/mod_configs.py).

Elden Ring's Seamless Co-op (ersc.dll) and Nightreign's (nrsc.dll) use the same ini format with different keys:
Nightreign's has no password and scales with three values instead of six. ScalingSpec says which keys a file has.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from bayle.formats import config_model, me3_profile
from bayle.game import catalog as games
from bayle.platform.files import atomic_write


def coop_ini_for(profile: str, game: games.Game | None = None) -> Path | None:
    """The settings ini of the Seamless Co-op dll this profile loads (paths in .me3 are relative to it): ersc.dll and
    ersc_settings.ini for Elden Ring, nrsc.dll and nrsc_settings.ini for Nightreign. None for games without one."""
    game = game or games.ELDEN_RING
    if not game.coop_dll or not game.coop_ini:
        return None
    dll = game.coop_dll.lower()
    try:
        text = Path(profile).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        found = me3_profile.entries(text)
    except tomllib.TOMLDecodeError:
        found = []
    paths = [e["path"] for e in found if e["kind"] == "native" and e["enabled"] and Path(e["path"]).name.lower() == dll]
    if not paths:
        paths = re.findall(r"""(?m)^[^#\n]*path\s*=\s*['"]([^'"]*""" + re.escape(dll) + r""")['"]""", text, re.I)
    for raw in paths:
        p = Path(raw)
        p = p if p.is_absolute() else Path(profile).parent / p
        ini = p.parent / game.coop_ini
        if ini.is_file():
            return ini
    return None


def ersc_ini_for(profile: str) -> Path | None:
    """Elden Ring's Seamless Co-op ini for this profile."""
    return coop_ini_for(profile, games.ELDEN_RING)


PW_RE = re.compile(
    r"^([ \t]*cooppassword[ \t]*=[ \t]*)(.*?)([ \t]*)(?=\r?$)", re.M | re.I
)  # [ \t] never \s (\s eats line breaks); group 3 = trailing blanks, kept; the lookahead leaves a CR in place


def _read(ini: Path) -> str:
    with open(ini, encoding="utf-8", errors="replace", newline="") as f:
        return f.read()  # keep CRLF as is


def _write(ini: Path, text: str):
    atomic_write(ini, text, backup=True)  # ersc_settings.ini.bak = the version before this write


def has_password(ini: Path) -> bool:
    """Whether this ini has a cooppassword line at all (Nightreign's Seamless Co-op has none)."""
    return bool(PW_RE.search(_read(ini)))


def read_password(ini: Path) -> str | None:
    m = PW_RE.search(_read(ini))
    return m.group(2) if m else None


def write_password(ini: Path, value: str):
    if "\n" in value or "\r" in value:  # a line break would add lines to the player's file
        raise ValueError("a value can't contain a line break")
    text = _read(ini)
    if not PW_RE.search(text):
        raise ValueError("no cooppassword line in " + str(ini))
    new = PW_RE.sub(lambda m: m.group(1) + value + m.group(3), text, count=1)
    if new != text:
        _write(ini, new)


def _key_re(key):
    return re.compile(r"^([ \t]*" + re.escape(key) + r"[ \t]*=[ \t]*)(.*?)([ \t]*)(?=\r?$)", re.M | re.I)


def read_keys(ini: Path, keys) -> dict:
    """key -> value string for the keys present in the ini (comments and layout untouched)."""
    doc = config_model.parse(_read(ini), config_model.INI)
    return {k: item.value for k in keys if (item := doc.find(k)) is not None}


def write_keys(ini: Path, values: dict):
    """Rewrite only the given keys in place (formats.config_model: nothing else in the file changes); a key that is not
    in the file is reported, never appended."""
    doc = config_model.parse(_read(ini), config_model.INI)
    missing = [k for k, v in values.items() if not doc.set(k, v)]
    _write(ini, doc.text())
    return missing


def read_settings_meta(ini: Path):
    """[{section, title, items: [{key, value, desc, kind, extra}]}] in file order, from formats.config_model: the
    comment line(s) directly above a key are its description, and the kind is inferred from that comment so the
    window can show the right control (toggle, dropdown, number, text) without a hand-written table."""
    doc = config_model.parse(_read(ini), config_model.INI)
    return [
        {
            "section": s.name,
            "title": s.name.title(),  # the page shows its own title for a known section
            "items": [
                {"key": i.key, "value": i.value, "desc": i.desc, "kind": i.kind, "extra": i.extra} for i in s.settings
            ],
        }
        for s in doc.sections
        if s.name  # settings above the first [section] are not Seamless's
    ]


LINE_RE = re.compile(r"^[ \t]*([A-Za-z0-9_]+)[ \t]*=[ \t]*(.*?)[ \t]*$")
SECTION_RE = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*$")
