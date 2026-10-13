"""The game's executable: its file version (from the version resource every Windows program carries) and its
SHA-256, which pick the lists the launcher knows about that build (game.knowledge)."""

from __future__ import annotations

import hashlib
import struct
from functools import cache
from pathlib import Path

_FIXED_FILE_INFO = b"\xbd\x04\xef\xfe"  # VS_FIXEDFILEINFO's signature, 0xFEEF04BD little-endian


def file_version(exe: Path | str) -> str | None:
    """The exe's FileVersion ("2.7.1.0"), or None when the file is missing or has no version resource. Only the
    headers and the resource section are read."""
    try:
        with Path(exe).open("rb") as f:
            head = f.read(0x1000)
            if head[:2] != b"MZ":
                return None
            pe = struct.unpack_from("<I", head, 0x3C)[0]
            f.seek(pe)
            coff = f.read(24)
            if coff[:4] != b"PE\0\0":
                return None
            sections, optional = struct.unpack_from("<H", coff, 6)[0], struct.unpack_from("<H", coff, 20)[0]
            f.seek(pe + 24 + optional)
            table = f.read(40 * sections)
            for i in range(sections):
                name, size, at = table[i * 40 : i * 40 + 8], *struct.unpack_from("<II", table, i * 40 + 16)
                if name.rstrip(b"\0") == b".rsrc":
                    f.seek(at)
                    return _version(f.read(size))
    except OSError, struct.error:
        return None
    return None


def _version(rsrc: bytes) -> str | None:
    at = rsrc.find(_FIXED_FILE_INFO)
    if at < 0 or at + 16 > len(rsrc):
        return None
    ms, ls = struct.unpack_from("<II", rsrc, at + 8)
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


@cache
def _sha256(path: str, size: int, mtime_ns: int) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256(exe: Path | str) -> str | None:
    """The exe's SHA-256 (remembered for this run by path, size and modification time), or None when unreadable."""
    try:
        st = Path(exe).stat()
        return _sha256(str(exe), st.st_size, st.st_mtime_ns)
    except OSError:
        return None
