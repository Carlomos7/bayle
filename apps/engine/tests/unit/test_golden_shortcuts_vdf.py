"""Golden bytes for Steam's shortcuts.vdf: a fixed file parses and dumps back identical, and retargeting it gives
exactly the recorded bytes. A refactor that moves the platform code must not change either hash."""

import hashlib
import struct

from bayle.adapters.integrations.steam import steam_shortcuts as vdf

OLD = r"C:\Users\me\AppData\Local\Programs\Roundtable Souls\RoundtableSouls.exe"


def _s(name: str, value: str) -> bytes:
    return b"\x01" + name.encode() + b"\x00" + value.encode() + b"\x00"


def _i(name: str, value: int) -> bytes:
    return b"\x02" + name.encode() + b"\x00" + struct.pack("<i", value)


def _entry(index: str, name: str, exe: str, opts: str) -> bytes:
    return (
        b"\x00" + index.encode() + b"\x00"
        + _i("appid", -123456789)
        + _s("AppName", name)
        + _s("Exe", f'"{exe}"')
        + _s("StartDir", f'"{exe.rsplit(chr(92), 1)[0]}"')
        + _s("icon", "")
        + _s("LaunchOptions", opts)
        + _i("IsHidden", 0)
        + b"\x07LastPlayTime\x00" + struct.pack("<Q", 1700000000)
        + b"\x00tags\x00" + _s("0", "Favorites") + _s("1", "Elden Ring \u00e9") + b"\x08"
        + b"\x00empty\x00\x08"
        + b"\x08"
    )  # fmt: skip


RAW = (
    b"\x00shortcuts\x00"
    + _entry("0", "Elden Ring (Roundtable)", OLD, "--game er --play")
    + _entry("1", "Nightreign (Roundtable)", OLD, "--game nr --play")
    + _entry("2", "Some other game", r"C:\Games\other.exe", "")
    + b"\x08\x08"
)
RAW_SHA = "c6ecc161ed2e8f7af98fe94715ccb111f0244960a84b2e4b4c0413ebead3d26a"
RETARGETED_SHA = "42be94862008db854d4844376e1353a6e2171d777175cd0c9fc8e39ecb7a6d4d"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_the_fixed_file_round_trips_byte_for_byte():
    assert _sha(RAW) == RAW_SHA
    assert vdf.dump(vdf.parse(RAW)) == RAW


def test_retargeting_the_fixed_file_gives_the_recorded_bytes(tmp_path):
    f = tmp_path / "Steam" / "userdata" / "12345" / "config" / "shortcuts.vdf"
    f.parent.mkdir(parents=True)
    f.write_bytes(RAW)
    changed = vdf.retarget(
        tmp_path / "Steam",
        lambda s: vdf._same_path(s.exe, OLD),
        tmp_path / "new" / "Bayle.exe",
        tmp_path / "backups",
        steam_running=False,
    )
    assert len(changed) == 2
    out = f.read_bytes()
    assert vdf.dump(vdf.parse(out)) == out
    # the new folder is under tmp_path and its separator is the OS's: both are normalised before the hash
    normal = out.replace(str(tmp_path / "new").encode(), b"<NEW>").replace(b"\Bayle.exe", b"/Bayle.exe")
    assert _sha(normal) == RETARGETED_SHA
