"""Durable file writes, moving a folder's contents into another (each file's .json note moves with it), and hiding a
file or folder."""

from __future__ import annotations

import os
import shutil
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

# Windows refuses a rename while another process has the target open: access denied, sharing or lock violation.
_SHARING_VIOLATIONS = {5, 32, 33}


def durable_write[T](
    path: Path,
    data: str | bytes,
    *,
    verify: Callable[[Path], object] | None = None,
    before_replace: Callable[[], T] | None = None,
    after: Callable[[Path], object] | None = None,
    retry_for: float = 2.0,
) -> T | None:
    """Replace path with data so that a crash, a power cut or a failed check never leaves it half written.

    1. data goes to a temp file of its own next to the target (<name>.<pid>.<random>.tmp; str as UTF-8, newlines as
       given), flushed and fsynced;
    2. verify(tmp), the caller's format check: raising aborts with the target untouched;
    3. before_replace(), e.g. the caller's backup: raising aborts with the target untouched; what it returns (say
       the backup's path) is what this returns;
    4. os.replace, retried for up to retry_for seconds while Windows refuses it with a sharing violation; any other
       error raises at once;
    5. on POSIX the folder is fsynced so the rename itself survives a power cut (Windows can't open a folder);
    6. after(path), an optional re-check of the result: raising propagates, and the new file stays in place. There is
       no roll-back here on purpose: putting the old bytes back is a second replace that can fail the same way, and
       the caller's backup from step 3 is the recovery it already owns and reports.

    Up to the replace, any failure removes the temp file and leaves the target and every .bak as they were. Only a
    process killed outright can leave a stray .tmp, which is never the target."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
        if verify is not None:
            verify(tmp)
        result = before_replace() if before_replace is not None else None
        _replace(tmp, path, retry_for)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    if sys.platform != "win32":
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    if after is not None:
        after(path)
    return result


def _replace(tmp: Path, path: Path, retry_for: float) -> None:
    deadline = time.monotonic() + retry_for
    pause = 0.02
    while True:
        try:
            os.replace(tmp, path)
            return
        except PermissionError as e:
            if getattr(e, "winerror", None) not in _SHARING_VIOLATIONS or time.monotonic() >= deadline:
                raise
        time.sleep(min(pause, max(0.0, deadline - time.monotonic())))
        pause = min(pause * 2, 0.25)


class Unsettled(OSError):
    """No consistent copy of a file could be read: it kept changing (another program writing it), or it stayed
    locked (locked=True: a sharing violation that outlasted the wait)."""

    def __init__(self, message: str, *, locked: bool = False) -> None:
        super().__init__(message)
        self.locked = locked


def read_settled(
    path: Path, *, tries: int = 3, pause: float = 0.2, retry_for: float = 2.0
) -> tuple[bytes, os.stat_result]:
    """The file's bytes as one consistent snapshot, and its stat: it is stat'ed, read twice and stat'ed again, and
    taken only when the two reads match and size and mtime held (a game writing it in place shows as a difference).
    Read again up to tries times; a sharing violation (the file held open) is waited out for retry_for seconds.
    Raises Unsettled when no consistent read came; other errors (the file is gone, access denied) as they are."""
    path = Path(path)
    deadline = time.monotonic() + retry_for
    changed = 0
    while True:
        try:
            before = os.stat(path)
            with open(path, "rb") as f:
                first = f.read()
                f.seek(0)
                second = f.read()
            after = os.stat(path)
        except PermissionError as e:
            # 32/33 only: 5 is also a real access denial, which waiting does not fix
            if getattr(e, "winerror", None) not in (32, 33):
                raise
            if time.monotonic() >= deadline:
                raise Unsettled(f"{path.name} is in use by another program.", locked=True) from e
            time.sleep(pause)
            continue
        held = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
        if held and first == second and len(first) == after.st_size:
            return first, after
        changed += 1
        if changed >= tries:
            raise Unsettled(f"{path.name} kept changing while it was read.")
        time.sleep(pause)


def atomic_write(path: Path, data, backup=False):
    """durable_write, keeping one .bak of the previous file when backup is set. A write that fails leaves the target
    as it was and removes the temp file; two writers of the same file (threads or processes) never share a temp
    file."""
    path = Path(path)

    def keep_bak():
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))

    durable_write(path, data, before_replace=keep_bak if backup else None)


def move_into(src_dir: Path, dest_dir: Path) -> None:
    """Move everything in src_dir into dest_dir (a rename on the same drive), renaming on a clash; drop src_dir
    when it ends up empty. A file in use stays for the next time."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(src_dir.iterdir()):
        if item.name.endswith((".bak.json", ".src.json")):
            continue  # moves with its backup, below
        target = dest_dir / item.name
        n = 2
        while target.exists():  # a clash keeps the extension, so the file still lists: x.20260924-140632-2.bak
            target = dest_dir / f"{item.stem}-{n}{item.suffix}"
            n += 1
        try:
            shutil.move(str(item), str(target))
        except OSError:
            continue
        note = Path(str(item) + ".json")
        if note.is_file():
            try:
                shutil.move(str(note), str(target) + ".json")
            except OSError:
                pass
    for stray in list(src_dir.iterdir()):  # a note whose backup is gone
        if stray.name.endswith(".json"):
            target = dest_dir / stray.name
            if not target.exists():
                try:
                    shutil.move(str(stray), str(target))
                except OSError:
                    pass
    try:
        src_dir.rmdir()
    except OSError:
        pass


def hide(path: Path) -> bool:
    """Give a file or folder Windows' hidden attribute (elsewhere a leading dot already hides it). Returns whether it
    is hidden now; a failure to set it is not an error."""
    if os.name != "nt":
        return Path(path).name.startswith(".")
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    attrs = kernel32.GetFileAttributesW(str(path))
    if attrs == 0xFFFFFFFF:  # INVALID_FILE_ATTRIBUTES: not there
        return False
    hidden = 0x2  # FILE_ATTRIBUTE_HIDDEN
    return bool(attrs & hidden) or bool(kernel32.SetFileAttributesW(str(path), attrs | hidden))


def is_hidden(path: Path) -> bool:
    """Whether Windows' hidden attribute is set (elsewhere: whether the name starts with a dot)."""
    if os.name != "nt":
        return Path(path).name.startswith(".")
    return bool(getattr(os.stat(path), "st_file_attributes", 0) & 0x2)
