"""Repairing a live Nightreign save: re-sign every section and, when entry 12 (the in-save regulation) no longer looks
like RSLT, restore it from a healthy sibling. The codec it works with (decrypt, checksums, rewrite) is
adapters.saves.nightreign; this is the writer, so it takes its backup through saves.fix."""

from __future__ import annotations

from pathlib import Path

from bayle.adapters.filesystem.files import durable_write
from bayle.adapters.saves import container
from bayle.adapters.saves.nightreign import (
    EXPECTED_SECTIONS,
    REGULATION_INDEX,
    NightreignSaveError,
    decrypt_entry,
    inspect,
    regulation_ok,
    rewrite,
)
from bayle.modules.saves import fix as save_fix


def _encrypted_section(data: bytes, index: int) -> bytes:
    found = container.check(data, EXPECTED_SECTIONS)
    if index >= len(found):
        raise NightreignSaveError(f"save has no section {index}")
    sec = found[index]
    return data[sec.offset : sec.offset + sec.size]


def sibling_regulation_source(save: Path) -> Path | None:
    """A healthy Nightreign save next to this one whose entry 12 still looks like RSLT."""
    save = Path(save)
    cands = [
        save.with_name(save.name + ".bak"),
        save.with_suffix(".bak"),
        save.with_suffix(".sl2" if save.suffix.lower() == ".co2" else ".co2"),
    ]
    for cand in cands:
        if not cand.is_file() or cand.resolve() == save.resolve():
            continue
        try:
            if inspect(cand.read_bytes())["regulation_ok"]:
                return cand
        except OSError, NightreignSaveError, container.ContainerError:
            continue
    return None


def repair(
    save: Path, *, force: bool = False, dry_run: bool = False, log=None, regulation_source: Path | None = None
) -> bool:
    """Re-sign the save and restore entry 12 from a healthy sibling when needed. True if rewritten."""
    say = log or (lambda *_a, **_k: None)
    save = Path(save)
    data = save.read_bytes()
    try:
        status = inspect(data)
    except container.ContainerError as e:
        say(f"  skip: not a whole Nightreign save ({e})")
        return False

    restore_blob = None
    if not status["rslt"]:
        src = Path(regulation_source) if regulation_source else sibling_regulation_source(save)
        if src is not None:
            try:
                restore_blob = _encrypted_section(src.read_bytes(), REGULATION_INDEX)
                if not regulation_ok(decrypt_entry(restore_blob)[1]):
                    restore_blob = None
                else:
                    say(f"  regulation source: {src}")
            except (OSError, NightreignSaveError, container.ContainerError) as e:
                say(f"  regulation source unusable ({e})")
                restore_blob = None
        else:
            say("  regulation section unreadable; no healthy copy next to this file to restore from")

    if status["healthy"] and restore_blob is None and not force:
        say("  nothing to do")
        return False
    if not status["checksum_all_ok"]:
        bad = [str(i) for i, ok in enumerate(status["checksum_ok"]) if not ok]
        say(f"  checksum mismatch in section(s) {', '.join(bad)}")
    if dry_run:
        say("  would repair (dry run)")
        return True

    new = rewrite(data, restore_regulation=restore_blob)
    if new == data:
        say("  nothing to do")
        return False
    manifest = {
        "action": "Before repairing the Nightreign save",
        "changes": (
            (["regulation section restored from a healthy copy"] if restore_blob is not None else [])
            + (["section checksums recomputed"] if not status["checksum_all_ok"] or restore_blob else [])
        )
        or ["sections re-signed"],
    }

    def verify(tmp: Path) -> None:
        check = inspect(tmp.read_bytes())
        if not check["checksum_all_ok"]:
            raise NightreignSaveError("checksums did not verify after the write")
        if restore_blob is not None and not check["regulation_ok"]:
            raise NightreignSaveError("regulation section did not verify after the write")

    # the backup is taken once the written copy has verified, just before it replaces the save
    bak = durable_write(save, new, verify=verify, before_replace=lambda: save_fix.backup(save, manifest))
    say(f"  backup: {bak}")
    say(f"  wrote:  {save}")
    return True
