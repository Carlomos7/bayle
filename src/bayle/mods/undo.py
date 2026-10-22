"""Taking a job back, from what it recorded (run_logging.set_undo) in the jobs index.

    remove   an entry removed from a profile: its text and where it was, and the folder when it went to the
             Recycle Bin (see system.trash). Restore puts both back.
    install  a fresh install, update an update, rollback a rollback (see mods.operations): the operation's own
             folder (.roundtable/ops/<id>, older ones .roundtable-ops/<id>) says what to take back. An install is
             undone (the profile's exact previous bytes, the files it created that nobody changed); an update or a
             rollback is rolled back as a set, with a rebuild when the install asked for one.
    rebuild  a rebuild of combined parameters: the profile as it was before (mods.history), the combined output it
             replaced (kept in the data folder), and the rebuild tool's own backup (its restore.json). Undo swaps each
             back by renaming, so it takes no time or space, and doing it again redoes the rebuild.

available() says whether it still can be done (the profile is still there, the folder is still in the bin, the
entry is not back already), so the Activity page only offers what works; run() does it and says what it did.
Which module does each type is in mods/kinds.py: a module registers the types it owns (this one: remove and multi).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bayle.game.locate import Locations

from pathlib import Path

from bayle.mods import kinds, profile_writer
from bayle.mods import profile_edit as mod_manage
from bayle.mods.models import UndoError

LABEL = {
    "remove": "Restore",
    "rebuild": "Undo rebuild",
    "install": "Undo install",
    "update": "Roll back",
    "rollback": "Roll back again",
    "overhaul-install": "Undo install",
    "overhaul-update": "Roll back",
    "overhaul-reapply": "Roll back",
    "overhaul-remove": "Restore",
    "overhaul-turn-off": "Undo turn off",
    "profile-import": "Undo import",
    "rename": "Undo rename",
    "profile-rename": "Undo rename",
    "profile-duplicate": "Undo copy",
    "profile-folders": "Undo move",
    "layout-relocate": "Undo move",
    "layout-rename": "Undo rename",
    "profile-move-in": "Undo move",
    "folder-rename": "Undo rename",
    "folder-split": "Undo split",
    "dll-folders": "Undo move",
    "save-restore": "Undo",
    "library-share": "Undo share",
    "library-use": "Undo",
    "library-separate": "Undo",
    "library-update": "Undo update",
    "library-clean": "Undo",
    "multi": "Undo",
}


def label(undo: dict | None) -> str:
    undo = undo or {}
    if undo.get("type") == "rebuild" and undo.get("redo"):
        return "Redo rebuild"
    return LABEL.get(undo.get("type", ""), "Undo")


def _listed(profile: Path, path: str) -> bool:
    if not path:
        return False
    try:
        want = mod_manage.resolve(profile, path)
        return any(
            e.get("path") and mod_manage.resolve(profile, e["path"]) == want for e in mod_manage.entries(profile)
        )
    except OSError:
        return False


def _in_bin(undo: dict) -> bool:
    from bayle.platform import trash

    return trash.exists(undo.get("trash"))


def _remove_available(undo: dict) -> bool:
    profile = Path(undo.get("profile") or "")
    if not undo.get("profile") or not profile.is_file() or not undo.get("entry_text"):
        return False
    return not _listed(profile, undo.get("path") or "") or _in_bin(undo)


def available(undo: dict | None) -> bool:
    if not undo:
        return False
    kinds.ensure_loaded()
    kind = kinds.UNDO.get(undo.get("type") or "")
    return kind.available(undo) if kind else False


def run(undo: dict, log, *, loc: Locations) -> str:
    """Do it. Returns a line saying what was done. Raises UndoError when it cannot be done any more, and
    FileExistsError when a folder is back at the old place already (nothing is overwritten)."""
    kinds.ensure_loaded()
    kind = kinds.UNDO.get(undo.get("type") or "")
    if kind is None:
        raise UndoError(f"Nothing to undo for {undo.get('type')!r}.")
    if kind.gone and not kind.available(undo):
        raise UndoError(kind.gone(undo))
    return kind.run(undo, log, loc)


def _run_multi(undo: dict, log, loc: Locations) -> str:
    return "; ".join(run(u, log, loc=loc) for u in undo["undos"])  # the last change first


def check_removed(undo: dict) -> None:
    """Whether a removal can be taken back exactly, for the toast's Undo: raises UndoError saying why not, before
    anything is touched. (Activity is lenient: it also brings back only the entry when the folder is gone.)"""
    from bayle.platform import trash

    profile = Path(undo.get("profile") or "")
    name = undo.get("name") or "the mod"
    if not undo.get("profile") or not profile.is_file() or not undo.get("entry_text"):
        raise UndoError(f"{profile.name or 'The profile'} is no longer there.")
    if _listed(profile, undo.get("path") or ""):
        raise UndoError(f"{name} is already back in {profile.name}.")
    rec = undo.get("trash")
    if rec and not trash.exists(rec):
        raise UndoError(f"{name}'s folder is no longer in the Recycle Bin.")
    if rec and Path(str(rec.get("original") or "")).exists():
        raise UndoError(f"A folder is already at {rec['original']}.")


def _restore_removed(undo: dict, log, loc: Locations) -> str:
    from bayle.platform import trash

    profile = Path(undo.get("profile") or "")
    name = undo.get("name") or "the mod"
    if not undo.get("profile") or not profile.is_file():
        raise UndoError(f"{profile.name or 'The profile'} is no longer there.")
    said = []
    record = undo.get("trash")
    if record:
        if trash.exists(record):
            back = trash.restore(record)
            log(f"restore: {name}'s folder is back at {back}")
            said.append("its folder")
        elif not Path(str(record.get("original") or "")).exists():
            log(f"warning: {name}'s folder is no longer in the Recycle Bin; only the entry comes back")
    if _listed(profile, undo.get("path") or ""):
        log(f"restore: {name} is already in {profile.name}")
    else:
        w = profile_writer.ProfileWriter(profile, loc)  # loc: the mod that must stay last is kept last
        w.restore_entry(undo["entry_text"], undo.get("where") or {})
        w.write(f"before restoring {name}")
        log(f"restore: {name}'s entry is back in {profile.name}, where it was")
        said.insert(0, "its entry")
    return f"restored {name}" + (f" ({' and '.join(said)})" if said else "")


kinds.register_undo(("remove",), _remove_available, _restore_removed)
# several changes made by one job: all of them still can be taken back
kinds.register_undo(
    ("multi",),
    lambda undo: bool(undo.get("undos")) and all(available(u) for u in undo["undos"]),
    _run_multi,
    kinds.named("This"),
)
