"""The Saves page's presenter (technical specification §8.10, Saves): the header line, the two live save cards, the
saved copies (the Library and the Backups), what each of the five operations says before it writes, Check & repair
and the read-only character sheet. Plain Python, every string through tr(); it turns the services' facts into what the
page shows, and the page's choices back into the calls the services take.

The five operations: copy a character into a live slot (or duplicate it in the same file), replace a live save with a
file, save a copy (Library), back up now (Backups), import a file (Library). Every write is confirmed in words from
here, backs up first and offers Undo afterwards; nothing is written while the game runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.platform.text import plural, tr
from bayle.services import saves as saves_service
from bayle.services.saves_page import ReplaceCheck, repair_calls
from bayle.work.prompts import Confirm, Refusal

ATTRIBUTES = (
    ("vig", "Vigor"),
    ("mind", "Mind"),
    ("end", "Endurance"),
    ("str", "Strength"),
    ("dex", "Dexterity"),
    ("int", "Intelligence"),
    ("fai", "Faith"),
    ("arc", "Arcane"),
)
STARTING_SUM = 79  # level = the eight attributes added up, minus this
WRITE_SAFETY = "The file is backed up first. Undo appears afterwards, and Backups can put any backup back."

# The wording of a backup's trigger (its note's action), shortest first.
_TRIGGERS = (
    ("before playing", "before Play"),
    ("before copying", "before copy"),
    ("manual", "manual"),
    ("before swapping", "before replace"),
    ("before restoring", "before restore"),
    ("before fixing", "before repair"),
    ("before removing", "before repair"),
    ("before repairing", "before repair"),
)


def key_text(key: tuple) -> str:
    """A Check & repair choice as a string QML can hold: ('loading', 2, 'torrent') -> 'loading:2:torrent'."""
    return ":".join(str(k) for k in key)


def trigger(action: str) -> str:
    low = action.lower()
    return next((words for start, words in _TRIGGERS if low.startswith(start)), action[:1].lower() + action[1:])


@dataclass(frozen=True)
class Drop:
    """What a drop does: the adapter slot its menu twin calls, and that slot's arguments. The slot asks, confirms and
    writes exactly as the menu does; a drop never writes by itself."""

    call: str
    args: tuple


class SavesPresenter:
    # ---- the static words
    def words(self) -> dict[str, str]:
        return {
            "title": tr("Saves"),
            "standard": tr("Standard"),
            "seamless": tr("Seamless Co-op"),
            "copies": tr("Saved copies"),
            "library": tr("Library"),
            "backups": tr("Backups"),
            "checkRepair": tr("Check & repair"),
            "back": tr("Back"),
            "empty": tr("Empty slot"),
            "noSaves": tr("No saves in this Windows account yet. Play once so the game creates its save folder."),
            "noLibraryTitle": tr("No saved copies yet"),
            "noLibrary": tr("Save a copy of a live save from its menu, or import a save file, and it appears here."),
            "noBackups": tr("No backups yet. One is taken before the first change to a save."),
            "backUpNow": tr("Back up now"),
            "saveCopy": tr("Save a copy to the Library"),
            "importAction": tr("Import a save file..."),
            "replaceWith": tr("Replace with a file..."),
            "copyReport": tr("Copy report"),
            "openFolder": tr("Open the folder"),
            "postSession": tr("Run post-session repair"),
            "postSessionTip": tr(
                "Checks every save of this game and tidies the game-rules section. Only save editors need that part."
            ),
            "dropImport": tr("Drop to import into the Library"),
            "undo": tr("Undo"),
            "cancel": tr("Cancel"),
            "keep": tr("Keep as a Library copy..."),
            "rename": tr("Rename..."),
            "remove": tr("Remove"),
            "deleteAction": tr("Remove"),
            "putBack": tr("Put back"),
            "finish": tr("Finish removing"),
            "name": tr("Name"),
            "sheetReadOnly": tr("This is a read-only view of the character as last saved."),
            "overview": tr("Overview"),
            "stats": tr("Stats"),
            "atLastSave": tr("at last save (with equipment)"),
            "nothingToFix": tr("Nothing to fix here."),
            "operations": tr("Operations on this save"),
            "copyTo": tr("Copy to..."),
            "copyActions": tr("More"),
            "emptySlots": tr("Empty slots:"),
            "slot": tr("Slot"),
            "replaceLibrary": tr("Restore from a Library copy"),
            "replaceKind": tr("Restore over {kind}..."),
            "restoreKind": tr("Restore over {kind}..."),
            "kept": tr("Kept"),
            "letAgeOut": tr("Let it age out"),
            "saveCopyHint": tr(
                "Keeps a copy of the whole file in the Library under this name. The save does not change."
            ),
            "importHint": tr("Copies the file into the Library under this name. Live saves do not change."),
            "keepHint": tr("Copies the backup into the Library under this name. The backup stays."),
            "importButton": tr("Import"),
            "save": tr("Save"),
            "level": tr("Level"),
            "body": tr("Body"),
            "where": tr("Where"),
            "torrent": tr("Torrent"),
            "runesHeld": tr("Runes held"),
            "runesMemory": tr("Runes memory"),
            "modItems": tr("Mod items"),
            "none": tr("None"),
            "all": tr("All"),
            "levelFrom": tr("Level {n} (the attributes added up, minus 79)"),
            "wholeFile": tr("The whole file"),
            "damagedHint": tr("Nothing is written to a damaged file. Restore a backup from before the crash."),
            "reading": tr("Reading saves..."),
            "nightreign": tr(
                "Nightreign's character data is not documented, so this page works on whole files: check, back up, copy and restore."
            ),
        }

    def header(self, names: dict[str, Any] | None) -> str:
        names = names or {}
        active = names.get("active")
        if not active:
            return ""
        return ""  # the cards say which save each launch uses; said twice before

    def running_bar(self, game: str) -> str:
        return tr("{game} is running. Saves are read-only until it closes, then checked again.").format(game=game)

    # ---- the two live cards
    def health(self, info: dict, running: bool) -> tuple[str, str]:
        """(the pill's words, its level: success | warning | danger)."""
        if info.get("error") and not info.get("characters") and not info.get("findings"):
            return tr("Unreadable"), "danger"
        if any(f.get("code") in ("layout", "read") and f.get("level") == "error" for f in info.get("findings") or []):
            return tr("Damaged"), "danger"
        if saves_service.repair_available(info):
            return (tr("Repair after you quit") if running else tr("Repair available")), "warning"
        return tr("Healthy"), "success"

    @staticmethod
    def kind_of(path: Path) -> str:
        return tr("Seamless Co-op") if Path(path).suffix.lower() == ".co2" else tr("Standard")

    def card(self, info: dict, role: str, running: bool) -> dict:
        text, level = self.health(info, running)
        plans = self._slot_marks(info)
        characters = [
            {
                "slot": c["slot"],
                "name": c["name"] or tr("Slot {n}").format(n=c["slot"]),
                "level": c["level"],
                "levelText": tr("Level {n}").format(n=c["level"]),
                "runes": tr("{n} runes").format(n=f"{c['runes']:,}"),
                "mark": plans.get(c["slot"], "") or ("" if c.get("ok", True) else tr("May not load")),
                "body": c.get("body", ""),
            }
            for c in info.get("characters") or []
        ]
        taken = {c["slot"] for c in characters} | {u["slot"] for u in info.get("unreadable") or []}
        unreadable = [
            {
                "slot": u["slot"],
                "name": u.get("name") or tr("Slot {n}").format(n=u["slot"]),
                "levelText": tr("Level {n}").format(n=u.get("level", 0)),
                "runes": "",
                "mark": tr("Older layout. Load it once in the game."),
                "level": u.get("level", 0),
                "body": "",
            }
            for u in info.get("unreadable") or []
        ]
        readable = bool(info.get("characters")) or bool(info.get("unreadable"))
        free = [n for n in range(1, 11) if n not in taken] if readable or not info.get("error") else []
        empty = [
            {"slot": n, "name": tr("Empty slot"), "level": 0, "levelText": "", "runes": "", "mark": "", "body": ""}
            for n in free
        ]
        by_slot = {c["slot"]: {**c, "empty": False} for c in characters + unreadable}
        by_slot.update({e["slot"]: {**e, "empty": True} for e in empty})
        return {
            "path": str(info["path"]),
            "kind": info["kind"],
            "file": info["name"],
            "modified": info["modified"],
            "role": role,
            "health": text,
            "healthLevel": level,
            "findings": [f for f in info.get("findings") or [] if f.get("level") in ("warn", "error")],
            "characters": sorted(characters + unreadable, key=lambda c: c["slot"]),
            "freeSlots": free,
            "slots": [by_slot[k] for k in sorted(by_slot)],  # all ten when the file reads: the empty ones are targets
            "canRepair": saves_service.repair_available(info) and not running,
            "canCopyCharacters": bool(info.get("characters")) and not running,
            "contents": next(
                (f["detail"] for f in info.get("findings") or [] if f.get("code") == "contents"),
                tr("This game's character data is not documented, so characters are not listed.")
                if info.get("block") == "n/a" and not info.get("characters")
                else "",
            ),
            "error": info.get("error") or "",
        }

    def _slot_marks(self, info: dict) -> dict[int, str]:
        """A mark only for a slot with a finding (1-based slot -> words)."""
        marks: dict[int, str] = {}
        for p in info.get("vanilla_plan") or []:
            if p.get("strip") or p.get("blocked"):
                marks[p["slot"] + 1] = tr("Mod items")
        cs = info.get("checksum_fixes") or {}
        for p in info.get("loading_plan") or []:
            marks[p["slot"] + 1] = tr("May not load")
        for slot in cs.get("slots") or []:
            marks[slot + 1] = tr("May not load")
        return marks

    # ---- saved copies
    def library_rows(self, libs: dict[str, dict]) -> tuple[list[dict], list[str]]:
        """(the Library's rows newest first, the problems to say). Each row: id, folder, name, when, tag, who, note."""
        rows, problems = [], []
        for folder, doc in libs.items():
            if doc.get("unreadable"):
                problems.append(
                    tr(
                        "{problem}. Its copies are not listed and the Library does not change until the file is fixed or moved aside."
                    ).format(problem=doc["unreadable"])
                )
            for e in doc.get("entries") or []:
                chars = e.get("characters") or []
                who = ", ".join(f"{c['name']} {c['level']}" for c in chars[:3]) + (
                    f" +{len(chars) - 3}" if len(chars) > 3 else ""
                )
                rows.append(
                    {
                        "id": e["id"],
                        "folder": str(folder),
                        "name": e["name"],
                        "when": (e.get("added") or "")[:16].replace("T", " "),
                        "tag": tr("Seamless Co-op") if e.get("format") != "sl2" else tr("Standard"),
                        "who": who or tr("no characters read"),
                        "from": e.get("from", ""),
                        "missing": bool(e.get("missing")),
                        "stranded": bool(e.get("in_removed")),
                        "characters": [
                            {"slot": c["slot"], "name": c["name"], "levelText": tr("Level {n}").format(n=c["level"])}
                            for c in chars
                        ],
                        "note": tr("File missing. Only Remove works.")
                        if e.get("missing") and not e.get("in_removed")
                        else tr("A removal stopped halfway: the file is in the removed folder.")
                        if e.get("in_removed")
                        else "",
                    }
                )
        rows.sort(key=lambda r: r["when"], reverse=True)
        return rows, problems

    def backup_days(self, backups: list[dict]) -> list[dict]:
        """The backups grouped by day, newest first: {day, rows: [{path, name, time, trigger, changes, kept, ...}]}."""
        days: dict[str, list[dict]] = {}
        for b in backups:
            days.setdefault(b["when"][:10], []).append(
                {
                    "path": str(b["path"]),
                    "name": b["save_name"],
                    "time": b["when"][11:16],
                    "trigger": trigger(b["action"]),
                    "action": b["action"],
                    "changes": list(b["changes"][:12]),
                    "kept": bool(b["keep"]),
                    "unreadable": bool(b.get("metadata_unreadable")),
                    "size": f"{b['size'] / 1_000_000:,.0f} MB",
                }
            )
        return [{"day": day, "rows": rows} for day, rows in days.items()]

    def retention(self, keep_newest: int, days: int) -> str:
        return tr("Keeping the newest {n} of each save and everything from the last {days} days.").format(
            n=keep_newest, days=days
        )

    # ---- the operations' words
    def refusal_busy(self, game: str, running: bool) -> Refusal:
        if running:
            return Refusal(tr("Close {game} first").format(game=game), tr("Saves cannot change while it runs."))
        return Refusal(tr("A job is running"), tr("Wait for it to finish."))

    # ---- what the three service jobs (Back up, Save a copy, Import) end with: facts in, words out
    def back_up_done(self, result: dict, everything: bool) -> str:
        made = [Path(b).name for b in result.get("backups", ())]
        if everything or len(made) != 1:
            return tr("Backed up {n} save file(s).").format(n=len(made))
        return tr("Backed up {name} ({file})").format(name=Path(result["saves"][0]).name, file=made[0])

    def save_copy_done(self, result: dict) -> str:
        return tr("Saved a copy of {file} as '{name}'").format(file=Path(result["source"]).name, name=result["name"])

    def import_done(self, result: dict) -> str:
        done, failed = result.get("imported", []), result.get("failed", [])
        if len(done) == 1 and not failed:
            return tr("Imported '{name}' into the Library").format(name=done[0]["name"])
        text = tr("Imported {n} files into the Library").format(n=len(done))
        if failed:
            text += tr(". Not imported: {names}").format(names=self._files(failed))
        return text

    @staticmethod
    def _files(items: list[dict]) -> str:
        return ", ".join(Path(i["file"]).name for i in items)

    def job_failed(self, code: str, message: str, details: dict | None = None) -> str | None:
        """A sentence for the failure code of Back up, Save a copy or Import; None for a code this page has no words for."""
        details = details or {}
        if code == "source_changed":
            return tr("The save changed while it was read. Try again when the game is not saving.")
        if code == "source_locked":
            return tr("Another program holds the file. Close it and try again.")
        if code == "not_a_save":
            return tr("That file is not a save file for this game.")
        if code == "library_unreadable":
            return tr("The Library cannot be read, so nothing was added.")
        if code == "library_busy":
            return tr("The Library is in use by another change. Try again in a moment.")
        if code == "not_imported":
            return tr("None of these files could be imported: {names}").format(
                names=self._files(details.get("failed", []))
            )
        if code == "failed" and details.get("backed_up"):
            names = ", ".join(Path(b).name for b in details["backed_up"])
            return tr("{message} Backed up before it stopped: {names}").format(message=message, names=names)
        return None

    # ---- what a write ends with: the job result's facts in, the toast's words out
    def copy_done(self, result: dict) -> str:
        return tr("{who} is in slot {n} of {file}").format(
            who=result["character"], n=result["slot"], file=result["file"]
        )

    def replace_done(self, result: dict) -> str:
        return tr("{target} now holds {source}").format(target=result["file"], source=result["source"])

    def restore_done(self, result: dict) -> str:
        return tr("{name} is back as it was in the backup").format(name=result["file"])

    def repair_done(self, result: dict) -> str:
        return tr("Repaired {name}").format(name=result["file"])

    def post_session_repair_done(self, result: dict) -> str:
        return tr("Post-session repair finished")

    def character_copy(self, plan: dict, source: str, target: str, target_slot: int, same_file: bool) -> Confirm:
        who = plan["character"] or {"name": "?", "level": 0}
        old = plan["replaces"]
        verb = tr("Duplicate") if same_file else tr("Replace") if old else tr("Copy")
        changes = [
            tr("{name} (level {level}) goes into slot {slot} of {file}.").format(
                name=who["name"], level=who["level"], slot=target_slot, file=target
            )
        ]
        if old:
            changes.append(
                tr("{name} (level {level}) in slot {slot} is replaced; it is in the backup taken first.").format(
                    name=old["name"] or tr("The character"), level=old["level"], slot=target_slot
                )
            )
        if plan["steam_id_changes"]:
            changes.append(tr("Signed for this account on copy."))
        return Confirm(
            title=tr("{verb} {name}").format(verb=verb, name=who["name"]),
            changes=tuple(changes),
            apply=verb,
            warning=tr("Elden Ring must stay closed until it finishes."),
            safety=tr("{file} is backed up first. Undo appears afterwards.").format(file=target),
        )

    def compare_lines(self, rows: list[dict]) -> list[str]:
        def who(c: dict | None) -> str:
            return tr("{name} (level {level})").format(name=c["name"], level=c["level"]) if c else tr("empty")

        words = {
            "same": tr("same"),
            "a only": tr("only in the new file"),
            "b only": tr("only in the old one"),
            "ahead in a": tr("the new file is further"),
            "ahead in b": tr("the old one is further"),
            "different": tr("a different character"),
        }
        return [
            tr("Slot {n}: {old} becomes {new}  ({change})").format(
                n=r["slot"], old=who(r["b"]), new=who(r["a"]), change=words.get(r["change"], r["change"])
            )
            for r in rows
        ]

    def replace(
        self,
        source: str,
        target: str,
        rows: list[dict],
        signed: bool,
        mod_holders: int,
        standard: bool,
        *,
        restore: bool = False,
        kinds: tuple[str, str] | None = None,
    ) -> Confirm:
        """restore: the source is a Library copy (Restore, not Replace). kinds: (source's, target's) file kinds when
        they differ (a Seamless .co2 over a Standard .sl2): the bytes are copied and the target keeps its name."""
        changes = [tr("{target} becomes a copy of {source}.").format(target=target, source=source)]
        if kinds:
            changes.append(
                tr(
                    "{source} is a {a} save and {target} is a {b} save. It is copied as it is; {target} keeps its name."
                ).format(source=source, target=target, a=kinds[0], b=kinds[1])
            )
        changes += self.compare_lines(rows)
        if signed:
            changes.append(tr("Signed for this account on copy."))
        warning = tr("Elden Ring must stay closed until it finishes.")
        if mod_holders and standard:
            warning = tr(
                "{n} characters hold items the game does not define. Check & repair can take them off afterwards."
            ).format(n=mod_holders)
        return Confirm(
            title=(tr("Restore {target}") if restore else tr("Replace {target}")).format(target=target),
            changes=tuple(changes),
            apply=tr("Restore") if restore else tr("Replace"),
            warning=warning,
            safety=tr("{target} is kept in the Library first, and backed up. Undo appears afterwards.").format(
                target=target
            ),
        )

    def replace_check(self, c: ReplaceCheck) -> Confirm:
        """Replace (a picked file) or Restore (a Library copy), from the service's check."""
        source, target = Path(c.source), Path(c.target)
        kinds = None
        if source.suffix.lower() != target.suffix.lower():
            kinds = (self.kind_of(source), self.kind_of(target))
        return self.replace(
            c.label,
            target.name,
            c.rows,
            c.signed,
            c.holders,
            target.suffix.lower() == ".sl2",
            restore=c.from_library,
            kinds=kinds,
        )

    def restore(self, bak: dict, target: str) -> Confirm:
        return Confirm(
            title=tr("Restore {target} from {when}").format(target=target, when=bak["when"][:16]),
            changes=(
                tr("{target} goes back to the backup taken {trigger}.").format(
                    target=target, trigger=trigger(bak["action"])
                ),
                *[tr("Undone with it: {c}").format(c=c) for c in bak["changes"][:6]],
            ),
            apply=tr("Restore"),
            warning=tr("Elden Ring must stay closed until it finishes."),
            safety=tr("{target} as it is now is backed up first, so this can be undone.").format(target=target),
        )

    def remove_copy(self, name: str) -> Confirm:
        return Confirm(
            title=tr("Remove '{name}' from the Library").format(name=name),
            changes=(
                tr("It no longer shows here."),
                tr("Its file moves to the Library's removed folder, with a note of what it was."),
            ),
            apply=tr("Remove"),
            safety=tr("No live save changes."),
        )

    def delete_backup(self, row: dict) -> Confirm:
        return Confirm(
            title=tr("Remove this backup"),
            changes=(
                Path(row["path"]).name,
                tr("Taken {when} before: {action}").format(when=row["time"], action=row["action"]),
            ),
            apply=tr("Remove"),
            warning=tr("Removing a backup cannot be undone. The live save is not touched."),
        )

    def changed_outside(self, name: str) -> Confirm:
        return Confirm(
            title=tr("'{name}' changed outside the launcher").format(name=name),
            changes=(tr("Its file no longer matches what the Library recorded when it was added."),),
            apply=tr("Replace anyway"),
            safety=tr("The save it replaces still goes into the Library first."),
        )

    # ---- Check & repair
    def repair_groups(self, info: dict, slot: int | None = None) -> list[dict]:
        """The finding cards: May not load, Remove mod items, Cleanup, For save editors. Each {id, title, hint,
        items: [{key, label, sub, checked, enabled, note, source}]}. slot (0-based) limits it to one character."""
        want = lambda s: slot is None or s == slot  # noqa: E731
        names = {c["slot"] - 1: c["name"] or tr("Slot {n}").format(n=c["slot"]) for c in info.get("characters") or []}
        who = lambda s: names.get(s, tr("Slot {n}").format(n=s + 1))  # noqa: E731
        prefix = lambda s: (who(s) + ": ") if slot is None else ""  # noqa: E731
        groups = []

        items = []
        for p in info.get("loading_plan") or []:
            if want(p["slot"]):
                for k, label, action in zip(p["issues"], p["labels"], p["actions"], strict=False):
                    items.append(self._item(("loading", p["slot"], k), prefix(p["slot"]) + label, action, True))
        cs = info.get("checksum_fixes") or {}
        for s in cs.get("slots") or []:
            if want(s):
                items.append(
                    self._item(
                        ("checksum", s),
                        prefix(s) + tr("Character data is out of step"),
                        tr("The game may refuse this character."),
                        True,
                    )
                )
        if cs.get("ud10") and slot is None:
            items.append(
                self._item(
                    ("checksum", "ud10"),
                    tr("Profile summary is out of step"),
                    tr("The game may refuse the save."),
                    True,
                )
            )
        if items:
            groups.append(
                {
                    "id": "load",
                    "title": tr("May not load"),
                    "hint": tr(
                        "These can hang the loading screen or make the game refuse the save. Ticked by default; untick one to leave it as it is. Repair makes the integrity data match again."
                    ),
                    "items": items,
                }
            )

        items = []
        for p in info.get("vanilla_plan") or []:
            if not want(p["slot"]):
                continue
            for e in p.get("strip") or []:
                where = tr("chest") if e["box"] == "storage" else tr("held")
                if e.get("pouch"):
                    where += tr(", in the pouch")
                elif e.get("quick"):
                    where += tr(", in a quick slot")
                items.append(
                    self._item(
                        ("item", p["slot"], e["handle"]),
                        prefix(p["slot"]) + e["name"] + (f"  x{e['qty']}" if e["qty"] > 1 else ""),
                        where,
                        False,
                        source=e.get("source") or tr("Other mod"),
                    )
                )
            for b in p.get("blocked") or []:
                items.append(
                    {
                        **self._item(
                            ("blocked", p["slot"], b.get("handle")),
                            prefix(p["slot"]) + b["name"],
                            "",
                            False,
                            source=b.get("source") or tr("Other mod"),
                        ),
                        "enabled": False,
                        "note": tr("Take it off in the game first.")
                        if b.get("why") == "worn"
                        else tr("Remove the ash in the game first."),
                    }
                )
        if items:
            groups.append(
                {
                    "id": "items",
                    "title": tr("Remove mod items"),
                    "hint": tr(
                        "Items only a mod knows about, named after that mod where possible. A standard save should not "
                        "carry them. Nothing is removed unless you tick it."
                    ),
                    "items": items,
                }
            )

        items = []
        for p in info.get("vanilla_plan") or []:
            if want(p["slot"]) and p.get("orphans"):
                n = len(p["orphans"])
                names_ = ", ".join(o["name"] for o in p["orphans"][:6]) + (
                    tr(", +{n} more").format(n=n - 6) if n > 6 else ""
                )
                items.append(
                    self._item(
                        ("orphans", p["slot"]),
                        prefix(p["slot"])
                        + plural("Clear {n} leftover entry", "Clear {n} leftover entries", n).format(n=n),
                        names_,
                        False,
                    )
                )
        if items:
            groups.append(
                {
                    "id": "cleanup",
                    "title": tr("Leftover entries"),
                    "hint": tr(
                        "Old item entries that nothing holds or wears, usually from a co-op partner's gear. Nothing is cleared unless you tick it."
                    ),
                    "items": items,
                }
            )

        if slot is None and info.get("needs_repair"):
            groups.append(
                {
                    "id": "editors",
                    "title": tr("Only for save editors"),
                    "hint": tr("The game does not read this part, so leaving it unticked changes nothing in play."),
                    "items": [
                        self._item(
                            ("regulation",),
                            tr("Tidy the save's game-rules section"),
                            tr(
                                "The launcher marks this section as changed after each session. Ticking puts it back as the game wrote it."
                            ),
                            False,
                        )
                    ],
                }
            )
        return groups

    @staticmethod
    def _item(key: tuple, label: str, sub: str, checked: bool, source: str = "") -> dict:
        return {
            "key": key_text(key),
            "tuple": key,
            "label": label,
            "sub": sub,
            "checked": checked,
            "enabled": True,
            "note": "",
            "source": source,
        }

    def default_ticks(self, groups: list[dict]) -> list[str]:
        return [i["key"] for g in groups for i in g["items"] if i["checked"] and i["enabled"]]

    def damaged(self, info: dict) -> list[dict]:
        return [
            f for f in info.get("findings") or [] if f.get("code") in ("layout", "read") and f.get("level") == "error"
        ]

    def summary(self, keys: list[tuple]) -> str:
        """The chip above the Repair button: what the ticked boxes do."""
        if not keys:
            return tr("Nothing selected.")
        kinds: dict[str, int] = {}
        for k in keys:
            kinds[k[0]] = kinds.get(k[0], 0) + 1
        bits = []
        if kinds.get("loading"):
            bits.append(plural("{n} loading fix", "{n} loading fixes", kinds["loading"]).format(n=kinds["loading"]))
        if kinds.get("item"):
            bits.append(plural("remove {n} item", "remove {n} items", kinds["item"]).format(n=kinds["item"]))
        if kinds.get("orphans"):
            bits.append(tr("clear leftover entries"))
        if kinds.get("checksum"):
            bits.append(
                plural("{n} integrity repair", "{n} integrity repairs", kinds["checksum"]).format(n=kinds["checksum"])
            )
        if kinds.get("regulation"):
            bits.append(tr("tidy game-rules section"))
        return ", ".join(bits) + ". " + tr("A backup is made first.")

    def repair_button(self, n: int) -> str:
        return plural("Repair {n} item", "Repair {n} items", n).format(n=n) if n else tr("Repair")

    def repair_confirm(self, info: dict, keys: list[tuple]) -> Confirm:
        calls = repair_calls(keys)
        names = {c["slot"] - 1: c["name"] or tr("Slot {n}").format(n=c["slot"]) for c in info.get("characters") or []}
        lines = []
        for sl, issues in calls["loading"].items():
            lines.append(
                plural("{who}: {n} loading fix", "{who}: {n} loading fixes", len(issues)).format(
                    who=names.get(sl, sl), n=len(issues)
                )
            )
        n_items = 0
        for sl, v in calls["vanilla"].items():
            bits = []
            if v["items"]:
                n_items += len(v["items"])
                bits.append(plural("remove {n} item", "remove {n} items", len(v["items"])).format(n=len(v["items"])))
            if v["orphans"]:
                bits.append(tr("clear leftover entries"))
            lines.append(f"{names.get(sl, sl)}: " + ", ".join(bits))
        if calls["checksums"]:
            lines.append(tr("Make the integrity data match again"))
        if calls["regulation"]:
            lines.append(tr("Tidy the save's game-rules section"))
        return Confirm(
            title=plural("Repair {n} item in {file}", "Repair {n} items in {file}", len(keys)).format(
                n=len(keys), file=info["name"]
            ),
            changes=tuple(lines),
            apply=self.repair_button(len(keys)),
            warning=tr("Elden Ring must stay closed until it finishes."),
            safety=tr("The file is backed up first. Undo appears afterwards."),
            detail=plural(
                "{n} item will be gone from this file. The mods give them back in co-op.",
                "{n} items will be gone from this file. The mods give them back in co-op.",
                n_items,
            ).format(n=n_items)
            if n_items
            else "",
        )

    # ---- the character sheet (read-only)
    def sheet(self, info: dict, slot: int) -> dict:
        """Overview and Stats for one character (1-based slot). No Journey (the NG+ count is not read), no
        playtime or last played (not verified): see the S9-Saves report."""
        ch = next((c for c in info.get("characters") or [] if c["slot"] == slot), None)
        if ch is None:
            return {}
        detail = saves_service.character_detail(info, slot - 1)
        st = ch.get("stats") or {}
        total = sum(int(st.get(k, 0)) for k, _ in ATTRIBUTES)
        marks = [g for g in self.repair_groups(info, slot - 1)]
        return {
            "slot": slot,
            "name": ch["name"] or tr("Slot {n}").format(n=slot),
            "level": ch["level"],
            "body": ch.get("body", ""),
            "where": ch.get("where", "?"),
            "torrent": ch.get("torrent", "?"),
            "runes": f"{ch['runes']:,}",
            "memory": f"{ch.get('memory', 0):,}",
            "attributes": [{"label": tr(label), "value": int(st.get(k, 0))} for k, label in ATTRIBUTES],
            "levelFromAttributes": max(total - STARTING_SUM, 0) if st else ch["level"],
            "derived": [
                {"label": tr("Max HP"), "value": f"{ch['hp']:,}"},
                {"label": tr("Max FP"), "value": f"{ch.get('fp', 0):,}"},
                {"label": tr("Max stamina"), "value": f"{ch.get('stamina', 0):,}"},
            ],
            "mods": ", ".join(f"{k} {v}" for k, v in (detail.get("mods") or {}).items()),
            "findings": [{"title": g["title"], "count": len(g["items"])} for g in marks],
            "checksumOk": bool(ch.get("ok", True)),
        }

    # ---- drag and drop: ONE rule set shared with the menu twins
    def drop(
        self, source: dict, target: dict, *, game: str, running: bool, busy: bool, encrypted: bool
    ) -> Drop | Refusal:
        """What dropping `source` on `target` means: a Drop (the twin's slot and arguments) or a Refusal in words.
        Pure: reads only what the drag carries, so it can judge every spot while the pointer moves.
        source: {type: character|live|copy|backup, path, slot, folder, id, missing}
        target: {type: slot|card|library|backups, path, slot, free, kind}."""
        kind, where = source.get("type"), target.get("type")
        read_only = kind == "live" and where == "library"  # Save a copy only reads the live save: allowed while it runs
        if busy or (running and not read_only):
            return self.refusal_busy(game, running and not busy)
        on_save = where in ("slot", "card")
        if kind in ("character", "copychar"):
            if not on_save:
                return Refusal(tr("Not here"), tr("A character goes into a slot of a live save."))
            if encrypted:
                return Refusal(
                    tr("Characters are not listed"), tr("Nightreign saves can only be copied as whole files.")
                )
            slot = target.get("slot")
            if where == "card":
                free = list(target.get("free") or [])
                if not free:
                    return Refusal(
                        tr("No free slot"), tr("Every slot of this save holds a character. Drop on one to replace it.")
                    )
                slot = free[0]
            if kind == "character":
                if target["path"] == source["path"] and slot == source["slot"]:
                    return Refusal(tr("Already there"), tr("That is the same slot."))
                return Drop("copyCharacter", (source["path"], source["slot"], target["path"], slot))
            if source.get("missing"):
                return Refusal(tr("This copy cannot be used"), tr("Its file is missing from the Library."))
            src_slot = int(source["slot"])
            return Drop("copyFromLibrary", (source["folder"], source["id"], src_slot, target["path"], slot))
        if kind == "copy" and where == "card":
            if source.get("missing"):
                return Refusal(tr("This copy cannot be used"), tr("Its file is missing from the Library."))
            return Drop("replaceFromLibrary", (source["folder"], source["id"], target["path"]))
        if kind == "backup" and where == "card":
            return Drop("restoreBackup", (source["path"], target["path"]))
        if kind in ("copy", "backup") and where == "slot":  # a file row acts on the whole save, never on one slot
            return Refusal(
                tr("This is a whole save"),
                tr("Drop it on a live save to restore it, or expand a Library copy and drag one character out."),
            )
        if kind == "copy" and where == "backups":
            return Refusal(tr("Not here"), tr("Backups are made by the launcher. Use Back up now on a live save."))
        if kind == "backup" and where == "library":
            return Refusal(tr("Not here"), tr("Keep it from the backup's menu (Keep as a Library copy...)."))
        if kind == "live" and where == "library":
            return Drop("askName", ("copy", source["path"]))
        if kind == "live" and where == "backups":
            return Drop("backUpNow", (source["path"],))
        if kind == "live" and on_save:
            return Refusal(tr("Not here"), tr("Drop a copy or a backup on a live save to replace it."))
        if kind == "copy" and where == "library":
            return Refusal(tr("Already there"), tr("This copy is already in the Library."))
        if kind == "backup" and where == "backups":
            return Refusal(tr("Already there"), tr("This backup is already in the Backups."))
        return Refusal(tr("Not here"), tr("Drop a character on a slot, or a copy or a backup on a live save."))


def transfer_error(e: Exception) -> Refusal:
    """Why a copy cannot go ahead, from the backend's own words."""
    return Refusal(tr("This copy cannot be made"), str(e))
