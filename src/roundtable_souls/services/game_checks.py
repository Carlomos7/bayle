"""What the game will make of a profile, said to the player around Play (3.22-B, from the game model).

- online_warning (backlog P3): a profile set to go online with parameters (regulation.bin) other than the game's. The
  game sends a hash of its regulation to FromSoftware's servers online, and can download and apply one from them.
- regulation_fingerprint (P6): a short fingerprint of the regulation the game will use with a profile, so co-op
  partners can compare (the game compares partners' regulation sizes; identical files are inferred to be needed).
- me3_mount_failures (M1): after Play, me3's log lines saying its fast loading of an archive failed (boot_boost:
  `mount_ebl ... trampoline returned null key=<the archive's key>`). me3 then mounts once more without logging the
  result, so one line means the DLC may have been missing; two or more for one archive make it the likely cause.

The Mods page's wiring (Qt Quick) is not here: it calls these.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from roundtable_souls.formats import me3_profile
from roundtable_souls.game import config as game_config
from roundtable_souls.game.locate import Locations
from roundtable_souls.mods import profile as profile_tools
from roundtable_souls.mods import rebuild as mod_merge

FINGERPRINT_HEX = 8  # shown characters of the SHA-256


@dataclass(frozen=True)
class Regulation:
    path: Path
    source: str  # the package whose copy the game uses, or "" for the game's own


def active_regulation(profile: Path, loc: Locations) -> Regulation | None:
    """The regulation.bin the game will use with this profile: the last enabled package (in me3's order) that ships
    one, else the game's own; None when neither is there."""
    name = loc.game.regulation
    try:
        layers = mod_merge.layers(Path(profile))
    except Exception:  # noqa: BLE001 - a profile that does not read: only the game's own is known
        layers = []
    for layer in reversed(layers):
        p = Path(layer["folder"]) / name
        if p.is_file():
            return Regulation(p, layer["name"])
    game_dir = loc.game_dir()
    own = Path(game_dir) / name if game_dir else None
    return Regulation(own, "") if own is not None and own.is_file() else None


def online_risk(profile: Path, loc: Locations) -> Regulation | None:
    """The package's regulation the profile goes online with (start_online on and a package's parameters in effect),
    or None. The rule without the words: the log line is online_warning's, the Mods page words its presenter's."""
    try:
        settings = profile_tools.read_settings(me3_profile.read_text(Path(profile)))
    except OSError:
        return None
    if settings.get("start_online") is not True:
        return None
    active = active_regulation(profile, loc)
    return active if active is not None and active.source else None


def online_warning(profile: Path, loc: Locations) -> str | None:
    """A warning when the profile goes online (start_online) with a package's parameters; None otherwise."""
    active = online_risk(profile, loc)
    if active is None:
        return None
    return (
        f"this profile goes online with changed parameters ({active.source}'s {loc.game.regulation}). Online, the "
        "game sends a fingerprint of its parameters to FromSoftware's servers, which can see the change and can send "
        "the game their own parameters. Turn Online matchmaking off in Profile settings to play offline."
    )


@dataclass(frozen=True)
class Fingerprint:
    short: str  # "1A2B3C4D"
    size: int
    source: str  # the package whose copy it is, or "" for the game's own

    def text(self, regulation: str = "regulation.bin") -> str:
        whose = f"{self.source}'s" if self.source else "the game's own"
        return f"Parameters: {self.short}, {self.size:,} bytes ({whose} {regulation}); co-op partners need the same"


def regulation_fingerprint(profile: Path, loc: Locations) -> Fingerprint | None:
    """The fingerprint of the regulation the game will use with this profile, or None when there is none."""
    active = active_regulation(profile, loc)
    if active is None:
        return None
    try:
        st = active.path.stat()
        key = (str(active.path), st.st_size, st.st_mtime_ns)
        if key not in _HASHES:
            data = active.path.read_bytes()
            _HASHES[key] = (hashlib.sha256(data).hexdigest()[:FINGERPRINT_HEX].upper(), len(data))
    except OSError:
        return None
    short, size = _HASHES[key]
    return Fingerprint(short, size, active.source)


_HASHES: dict[tuple[str, int, int], tuple[str, int]] = {}  # the Mods page reads it on every refresh: hash once


_ANSI = re.compile(r"\x1b\[[0-9;]*m|\x1b\][^\x07]*\x07")
_FAILED = re.compile(
    r"trampoline returned null\s+key=(-----BEGIN RSA PUBLIC KEY-----.*?-----END RSA PUBLIC KEY-----)", re.S
)


def _key(pem: str) -> str:
    return "".join(pem.split())


def me3_mount_failures(log_text: str, archives: dict[str, str] | None = None) -> list[str]:
    """What to tell the player about me3's failed fast loading in one launch's log (none: [])."""
    keys = {_key(pem): name for name, pem in (archives or dict(game_config.load().archives)).items()}
    counts: dict[str, int] = {}
    for m in _FAILED.finditer(_ANSI.sub("", log_text)):
        name = keys.get(_key(m.group(1)), "")
        counts[name] = counts.get(name, 0) + 1
    out = []
    for name, n in counts.items():
        if name.upper().startswith("DLC"):
            if n == 1:
                out.append(
                    "me3's fast DLC loading failed this launch; if your DLC was missing, that's why; Play again."
                )
            else:
                out.append(
                    f"me3's fast DLC loading failed {n} times this launch: that is the likely reason if your DLC was "
                    "missing; Play again."
                )
        else:
            what = f"the game's {name} archive" if name else "one of the game's archives"
            likely = "that's why" if n == 1 else "that is the likely reason"
            out.append(
                f"me3's fast loading of {what} failed this launch ({n} time{'s' if n != 1 else ''}); if parts of the "
                f"game were missing, {likely}; Play again."
            )
    return out
