"""Backed-up writes for Elden Ring PC saves: checksum repair, and the commit step every repair uses.

Every write:
  1. builds the new bytes in memory,
  2. re-parses them and checks the MD5 of every touched slot,
  3. copies the original into the launcher's backups (save_backups.backups, with a JSON note saying why), then
     replaces it.

Nothing is written when there is nothing to do. Callers refuse while the game runs.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable
from pathlib import Path

from bayle.adapters.filesystem.files import durable_write, read_settled
from bayle.adapters.saves import layout as L
from bayle.modules.saves import backups as save_backups

SLOT_STRIDE = 0x10 + L.SLOT_SIZE


class FixError(Exception):
    pass


def plan_checksum_fixes(parsed: dict) -> dict:
    """Which MD5s are stale: {'slots': [active slot indexes], 'ud10': bool}."""
    active = (parsed.get("ud10") or {}).get("active") or []
    bad = [i for i, ok in enumerate(parsed.get("slot_md5_ok") or []) if not ok and i < len(active) and active[i]]
    return {"slots": bad, "ud10": not parsed.get("ud10_md5_ok", True)}


def backup(save: Path, manifest: dict | None = None) -> Path:
    """Copy the save into its account's backups folder (save_backups.backups). A note (what it was taken before, when,
    which save, what changed) is written beside it as <backup>.json, then older backups of that save are pruned. All
    of it runs under the account's backups lock (save_backups.account_lock); BackupsBusy means no backup was taken,
    so the caller's change must not go ahead; so does Unsettled (the save kept changing or stayed locked while it was
    read). The copy is one consistent read of the save, written whole or not at all (never a partial .bak under its
    final name), checked before it gets that name, and keeps the save's timestamps as copy2 did (prune ages
    backups by mtime)."""
    save = Path(save)
    data, st = read_settled(save)
    folder = save_backups.backups(save.parent)
    folder.mkdir(parents=True, exist_ok=True)

    def same_copy(tmp: Path) -> None:
        if tmp.read_bytes() != data:
            raise OSError(f"The backup of {save.name} did not read back the same; nothing was kept.")
        os.utime(tmp, ns=(st.st_atime_ns, st.st_mtime_ns))

    with save_backups.account_lock(folder):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = folder / f"{save.name}.{stamp}.bak"
        n = 1
        while dest.exists():
            n += 1
            dest = folder / f"{save.name}.{stamp}-{n}.bak"
        durable_write(dest, data, verify=same_copy)
        write_manifest(dest, manifest or {"action": "Before a change"}, save)
        save_backups.prune(folder, save.name)
    return dest


def write_manifest(bak: Path, manifest: dict, save: Path | None = None) -> None:
    doc = {
        "action": manifest.get("action", "Before a change"),
        "when": time.strftime("%Y-%m-%d %H:%M:%S"),
        "save": str(save) if save else "",
        "changes": list(manifest.get("changes") or []),
    }
    with save_backups.account_lock(Path(bak).parent):
        try:
            save_backups.write_note(bak, doc)
        except OSError:
            pass


def read_manifest(bak: Path) -> dict | None:
    try:
        return save_backups.read_note(bak)
    except save_backups.UnreadableNote:
        return None


def _sign_slot(data: bytearray, i: int) -> None:
    off = L.HEADER + i * SLOT_STRIDE
    data[off : off + 0x10] = hashlib.md5(data[off + 0x10 : off + SLOT_STRIDE]).digest()


def _sign_ud10(data: bytearray, ud10_pos: int) -> None:
    data[ud10_pos : ud10_pos + 0x10] = hashlib.md5(data[ud10_pos + 0x10 : ud10_pos + 0x60010]).digest()


def _commit(
    save: Path,
    data: bytes,
    touched_slots: list[int],
    expect_ud10_ok: bool,
    manifest: dict | None = None,
    check: Callable[[dict], None] | None = None,
) -> Path:
    """Write data over save (durable_write): the written temp copy must parse with matching MD5s and pass check
    (the caller's own test of the parsed copy, raising FixError), then the original is backed up and replaced.
    Returns the backup. Any failure before the replace leaves the save untouched and no backup taken."""

    def verify(tmp: Path) -> None:
        r = L.parse(str(tmp))
        for i in touched_slots:
            if not r["slot_md5_ok"][i]:
                raise FixError(f"slot {i + 1} checksum did not verify after the write")
        if expect_ud10_ok and not r["ud10_md5_ok"]:
            raise FixError("profile summary checksum did not verify after the write")
        if check is not None:
            check(r)

    bak = durable_write(save, data, verify=verify, before_replace=lambda: backup(save, manifest))
    assert bak is not None
    return bak


def repair_checksums(save: Path, log=None) -> dict:
    """Recompute stale slot and profile-summary MD5s. Returns {'slots': [...], 'ud10': bool, 'backup': Path | None}."""
    save = Path(save)
    say = log or (lambda *_: None)
    data = bytearray(save.read_bytes())
    r = L.parse(str(save))
    plan = plan_checksum_fixes(r)
    if not plan["slots"] and not plan["ud10"]:
        say("  checksums already match")
        return {"slots": [], "ud10": False, "backup": None}
    for i in plan["slots"]:
        _sign_slot(data, i)
        say(f"  slot {i + 1}: checksum recomputed")
    if plan["ud10"]:
        _sign_ud10(data, r["ud10_pos"])
        say("  profile summary: checksum recomputed")
    changes = [f"slot {i + 1}: checksum recomputed" for i in plan["slots"]] + (
        ["profile summary: checksum recomputed"] if plan["ud10"] else []
    )
    bak = _commit(save, bytes(data), plan["slots"], True, {"action": "Before fixing checksums", "changes": changes})
    say(f"  backup: {bak}")
    return {"slots": plan["slots"], "ud10": plan["ud10"], "backup": bak}
