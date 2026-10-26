"""An invented, parseable Elden Ring PC save (BND4, 10 slots, every MD5 valid), built in memory.

Not a real save: slots are zero except the bytes a test writes. Used by the test_writer_* tests that pin how the
live-save writers put bytes on disk."""

import builtins
import errno
import io
import os
from pathlib import Path

from bayle.adapters.saves import layout as L
from bayle.modules.saves import backups as save_backups
from bayle.modules.saves import fix as F
from bayle.modules.saves import regulation as R


def build(marks: dict[int, bytes] | None = None, active: tuple[int, ...] = ()) -> bytes:
    """A signed save; marks {slot: bytes} are written at the start of that slot's body (before signing); active
    lists the slots flagged as holding a character (the checksum repair only looks at those)."""
    d = bytearray(R.FILE_SIZE)
    d[:4] = b"BND4"
    for i, b in (marks or {}).items():
        off = L.HEADER + i * F.SLOT_STRIDE + 0x10
        d[off : off + len(b)] = b
    for i in range(10):
        F._sign_slot(d, i)
    r = L.parse_bytes(bytes(d))
    for i in active:
        d[r["ud10"]["active_pos"] + i] = 1
    F._sign_ud10(d, r["ud10_pos"])
    return bytes(d)


def stale_slot(data: bytes, i: int = 0) -> bytes:
    """The same save with slot i's body changed and its MD5 left as it was (a stale checksum)."""
    d = bytearray(data)
    d[L.HEADER + i * F.SLOT_STRIDE + 0x10 + 5] ^= 0xFF
    return bytes(d)


# ----------------------------------------------------------------------------- helpers for the writer tests
OLD_MTIME_NS = 1_700_000_000_123_456_700  # an old, odd mtime (100 ns steps: NTFS): a backup that keeps it was really copied with it


def put(path: Path, data: bytes, mtime_ns: int = OLD_MTIME_NS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def backups_of(save: Path) -> list[Path]:
    return sorted(save_backups.backups(save.parent).glob("*.bak"))


def strays(root: Path) -> list[str]:
    """Temp and probe files a writer left behind anywhere under root."""
    return sorted(
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and (p.name.endswith((".tmp", ".verify")) or ".roundtable." in p.name)
    )


def _is_tmp_of(save: Path, name) -> bool:
    p = Path(os.fsdecode(name)) if isinstance(name, (str, bytes, os.PathLike)) else None
    return bool(p) and p.parent == save.parent and p.name.startswith(save.name) and p.name.endswith(".tmp")


class _Wrapped:
    """A file object whose write() goes through fn(data) -> data, which may raise."""

    def __init__(self, f, fn):
        self._f, self._fn = f, fn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._f.close()

    def write(self, data):
        return self._f.write(self._fn(bytes(data), self._f))

    def __getattr__(self, name):
        return getattr(self._f, name)


def _patch_open(monkeypatch, save: Path, fn, inplace: bool = False) -> None:
    """Wrap every write-open of the temp file next to save (and of save itself when inplace)."""
    real = io.open

    def opener(file, mode="r", *a, **k):
        f = real(file, mode, *a, **k)
        hit = _is_tmp_of(save, file) or (inplace and isinstance(file, (str, os.PathLike)) and Path(file) == save)
        return _Wrapped(f, fn) if "w" in mode and hit else f

    monkeypatch.setattr(io, "open", opener)
    monkeypatch.setattr(builtins, "open", opener)


def disk_full_on_tmp(monkeypatch, save: Path, inplace: bool = False) -> None:
    """Writing the temp file next to save (or save itself, inplace) puts half of it on disk, then fails with ENOSPC (the half stays)."""

    def full(data, f):
        f.write(data[: len(data) // 2])
        raise OSError(errno.ENOSPC, "No space left on device")

    _patch_open(monkeypatch, save, full, inplace)


def corrupt_tmp(monkeypatch, save: Path, at: int, inplace: bool = False) -> None:
    """The temp file next to save (or save itself, inplace) gets its byte at offset `at` flipped on the way to disk (a silent bad write)."""

    def flip(data, f):
        b = bytearray(data)
        b[at] ^= 0xFF
        return bytes(b)

    _patch_open(monkeypatch, save, flip, inplace)


def _winerror(code: int) -> PermissionError:
    e = PermissionError(13, "The process cannot access the file because it is being used by another process")
    e.winerror = code  # type: ignore[attr-defined]
    return e


def refuse_replace(monkeypatch, onto: Path, times: int | None = None) -> list[int]:
    """os.replace onto `onto` fails with PermissionError winerror 32, `times` times (None: always), then works.
    Path.replace goes through os.replace, so this covers both. Returns a one-item list counting the refusals."""
    real, seen = os.replace, [0]

    def replace(src, dst, *a, **k):
        if Path(dst) == onto and (times is None or seen[0] < times):
            seen[0] += 1
            raise _winerror(32)
        return real(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", replace)
    return seen


def corrupt_after_replace(monkeypatch, onto: Path) -> None:
    """Right after a replace onto `onto`, one byte of the new file is flipped (what the read-back must catch)."""
    real = os.replace

    def replace(src, dst, *a, **k):
        real(src, dst, *a, **k)
        if Path(dst) == onto:
            b = bytearray(Path(dst).read_bytes())
            b[0x400] ^= 0xFF
            Path(dst).write_bytes(bytes(b))

    monkeypatch.setattr(os, "replace", replace)


# ----------------------------------------------------------------------------- an invented Nightreign container
def nightreign_good(reg: bytes = b"RSLT" + bytes(12)) -> bytes:
    """A whole Nightreign-shaped save (14 encrypted sections, every checksum right); reg is section 12's payload."""
    from bayle.adapters.saves import nightreign as nr

    payloads = [(reg if i == 12 else bytes([i]) + bytes(15)) for i in range(14)]
    return nr.pack_save(payloads, ivs=[bytes([i, *range(1, 16)]) for i in range(14)])


def nightreign_stale(data: bytes, section: int = 3) -> bytes:
    """The same save with one section's stored checksum wrong."""
    from bayle.adapters.saves import container
    from bayle.adapters.saves import nightreign as nr

    out = bytearray(data)
    sec = container.sections(data)[section]
    iv, dec = nr.decrypt_entry(data[sec.offset : sec.offset + sec.size])
    dec = bytearray(dec)
    dec[nr.checksum_offset(dec)] ^= 1
    out[sec.offset : sec.offset + sec.size] = nr.encrypt_entry(iv, dec)
    return bytes(out)


def nightreign_section_offset(data: bytes, section: int) -> int:
    from bayle.adapters.saves import container

    return container.sections(data)[section].offset


# ----------------------------------------------------------------------------- an invented regulation block
def made_up_regulation() -> bytes:
    """A plausible regulation blob (0x180000 bytes, no trailing zeros) that passes regulation.plausible_regulation."""
    return bytes((i * 7 + 1) % 255 + 1 for i in range(0x180000))


def with_block(data: bytes, block: bytes) -> bytes:
    out = bytearray(data)
    out[R.UD11_OFF : R.UD11_OFF + R.UD11_SIZE] = block
    return bytes(out)


def healthy_block(reg: bytes) -> bytes:
    return R.rebuild_block(reg, R.HEALTHY_HEADER)


def broken_block() -> bytes:
    """What me3 leaves in the block: not the regulation, a wrong header, an MD5 that no longer fits."""
    return bytes(range(1, 255)) * (R.UD11_SIZE // 254) + bytes(R.UD11_SIZE % 254)
