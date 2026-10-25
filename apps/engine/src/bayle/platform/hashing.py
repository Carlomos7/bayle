"""File hashing remembered by path, size and modification time (merged archives are large)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Protocol


class HashStore(Protocol):
    """The persistent hash cache (storage.cache.HashCache): used once active; get() returns None on a miss or any
    failure, put() never raises."""

    active: bool

    def get(self, key: str, size: int, mtime_ns: int) -> str | None: ...

    def put(self, key: str, size: int, mtime_ns: int, sha256: str) -> None: ...


_HASHES: dict[str, tuple[int, int, str]] = {}  # this process's own memory of hashes, same rule
_HASHES_LOADED = False
# Bound by bayle.runtime.bootstrap only: the database's cache (used once its import is verified; until then the old
# file), or None with _HASH_FILE_IN_USE False when storage is off for the run (memory only: files are hashed again,
# and cache/hashes.json is left as it is).
_HASH_STORE: HashStore | None = None
_HASH_FILE_IN_USE = True


def _hash_file() -> Path:
    from bayle.platform import data_folder

    return data_folder.data_root() / "cache" / "hashes.json"


def sha256(path: Path) -> str | None:
    """sha256 of a file, remembered by path, size and modification time (merged archives are large). A remembered
    hash is used only while the file's size and modification time (ns) are exactly the same; a cache that fails is
    a miss, so the file is hashed (never a reason to call a build current). None when the file can't be read."""
    global _HASHES_LOADED
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    key = os.path.normcase(str(path.resolve()))
    store = _HASH_STORE if _HASH_STORE is not None and _HASH_STORE.active else None
    legacy = store is None and _HASH_FILE_IN_USE
    if legacy and not _HASHES_LOADED:
        _HASHES_LOADED = True
        try:
            _HASHES.update({k: tuple(v) for k, v in json.loads(_hash_file().read_text(encoding="utf-8")).items()})
        except OSError, ValueError:
            pass
    hit = _HASHES.get(key)
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    if store is not None:
        remembered = store.get(key, st.st_size, st.st_mtime_ns)  # its own short unit of work, closed again
        if remembered:
            _HASHES[key] = (st.st_size, st.st_mtime_ns, remembered)
            return remembered
    h = hashlib.sha256()  # no database transaction is open while the file is read
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    _HASHES[key] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    if store is not None:
        store.put(key, st.st_size, st.st_mtime_ns, h.hexdigest())
    elif legacy:
        try:
            out = _hash_file()
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_suffix(".tmp")
            tmp.write_text(json.dumps(_HASHES), encoding="utf-8")
            tmp.replace(out)
        except OSError:
            pass
    return _HASHES[key][2]
