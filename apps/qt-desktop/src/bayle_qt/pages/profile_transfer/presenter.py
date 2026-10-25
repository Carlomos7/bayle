"""The Export / Import profile page's presenter (technical specification, "Export / Import profile"): every word the
page shows and the plain-text form of the facts the engine's Profile transfer interface
(services.profile_transfer.ProfileTransferService) returns. Plain Python, every string through tr()."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from bayle.errors import OperationError
from bayle.mods import profile_import
from bayle.services import profile_transfer as pt
from bayle.work.prompts import Confirm

from bayle_qt.text import plural, tr


def size_text(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{max(1, n // 1024)} KB" if n else "0 KB"


class ModLike(Protocol):
    """A mod of the profile as the export checklist lists it."""

    @property
    def key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def size(self) -> int: ...
    @property
    def enabled(self) -> bool: ...


@dataclass
class PageInputs:
    """Everything the page's state is built from: the adapter's form fields and what the session last answered."""

    profile: Path | None
    ex: dict[str, Any]
    mods: list[ModLike]
    picked: set[str]
    busy: bool  # another job runs
    game_running: bool
    working: bool
    run: dict[str, Any]
    incoming_file: str = ""  # the open file's one-line description ("" when none is open)
    incoming_zip: bool = False
    incoming_readme: str = ""
    preview: pt.PreviewFacts | None = None
    bundled: pt.PreviewFacts | None = None
    ticked: set[str] = field(default_factory=set)
    new_profile: bool = True
    new_name: str = ""
    error: str = ""
    import_pct: int = -1
    names: list[str] = field(default_factory=list)
    which: int = 0


class ProfileTransferPresenter:
    """Pure: everything the page shows comes from the arguments."""

    open_window_text = property(lambda self: tr("Export / Import profile (new window)"))
    open_window_tip = property(lambda self: tr("A preview of the new Export / Import profile page, in its own window."))

    def words(self) -> dict[str, str]:
        return {
            "title": tr("Export / Import profile"),
            "noProfile": tr("Pick a profile first."),
            "tabExport": tr("Export"),
            "tabImport": tr("Import"),
            "shareList": tr("Share list"),
            "fullExport": tr("Full export"),
            "shareListAbout": tr(
                "One small file: your mods, their order and options, the profile settings and your mods' settings "
                "files. Your friend needs the mods already."
            ),
            "fullExportAbout": tr("A zip with the mods themselves, so your friend can import it into a new profile."),
            "name": tr("Name"),
            "version": tr("Version (optional)"),
            "author": tr("Author"),
            "mods": tr("Mods in the export"),
            "readme": tr("README"),
            "readmePreview": tr("Preview"),
            "readmeEdit": tr("Edit"),
            "changelog": tr("Changelog"),
            "include": tr("Include"),
            "withProfile": tr("The profile (.me3)"),
            "withConfigs": tr("Your mods' settings files"),
            "withPassword": tr("The Seamless Co-op password"),
            "withPasswordTip": tr("Off by default: anyone with the file could read it."),
            "withSave": tr("My save file"),
            "withSaveWarn": tr("A save holds your characters. Only share it with someone you trust."),
            "noSave": tr("No save was found for this profile."),
            "outFolder": tr("Output folder"),
            "chooseFolder": tr("Choose output folder..."),
            "export": tr("Export"),
            "exporting": tr("Exporting..."),
            "exportingProfile": tr("Exporting {name}"),
            "importingInto": tr("Importing into {name}"),
            "cancel": tr("Cancel"),
            "openFile": tr("Open file..."),
            "importAbout": tr("Open a share list (.json) or a full export (.zip) someone sent you."),
            "willChange": tr("Files this import changes"),
            "left": tr("Left out"),
            "notes": tr("Good to know"),
            "importButton": tr("Import"),
            "importing": tr("Importing..."),
            "nothing": tr("Nothing in this file would change your profile."),
            "readmeFirst": tr("From the author"),
            "newProfile": tr("Create a new profile"),
            "currentProfile": tr("Add to current profile"),
            "newName": tr("Profile name"),
            "whichProfile": tr("Which profile to import"),
            "bundledTitle": tr("This download has a profile"),
            "bundledAbout": tr(
                "Nothing in the download runs. Only the mods the profile points at are copied into this profile's folder."
            ),
            "newFile": tr("New file"),
            "openZipFolder": tr("Open the zip's folder"),
            "cancelExport": tr("Cancel export"),
            "cancelling": tr("Cancelling..."),
            "showInFolder": tr("Show in folder"),
            "required": tr("Required"),
            "tickOne": tr("Tick at least one mod."),
            "reading": tr("Working on it. A big zip can take a minute..."),
            "differsTitle": tr("Already installed, with different files"),
            "differsAbout": tr("Pick which copy each of these mods should use."),
            "useIncoming": tr("Use the incoming copy"),
            "keepMine": tr("Keep mine"),
            "keepBoth": tr("Keep both"),
            "incomingCopy": tr("Incoming copy"),
            "yourCopy": tr("Your copy"),
            "pickOne": tr("Pick one to continue."),
            "suggested": tr("Suggested: the incoming copy has the higher version number."),
        }

    def page_state(self, i: PageInputs) -> dict:
        """The whole page state QML binds to: the export form with why it is off, the import view, the bundled view."""
        words = self.words()
        ex = dict(i.ex)
        ex["mods"] = [
            {
                "key": m.key,
                "name": m.name,
                "size": size_text(m.size),
                "checked": m.key in i.picked,
                "large": m.size >= pt.LARGE_MOD,
            }
            for m in i.mods
        ]
        picked = [m for m in i.mods if m.key in i.picked]
        size = sum(m.size for m in picked)
        full = ex["kind"] == "full"
        ex["total"] = self.total(len(picked), size)
        name_ok, folder_ok, mods_ok = bool(ex["name"].strip()), bool(ex["folder"]), bool(picked) or not full
        busy = (
            tr("Another job is running. Wait for it to finish.")
            if i.busy
            else tr("Close the game first: exports run as launcher jobs.")
            if i.game_running
            else tr("Exporting...")
            if i.working
            else ""
        )
        ex["reason"] = self.reason(name_ok, folder_ok, mods_ok, busy)
        ex["ready"] = ex["reason"] == ""
        ex["nameError"], ex["folderError"], ex["modsError"] = not name_ok, not folder_ok, not mods_ok
        ex["summary"] = self.summary(
            full,
            len(picked),
            size,
            bool(ex["withConfigs"]),
            bool(ex["withSave"] and ex["saveName"]),
            bool(ex["withPassword"]),
        )
        top = sorted(picked, key=lambda m: m.size, reverse=True)[:3]
        ex["warn"] = self.big_warning(size, [(m.name, m.size) for m in top]) if full and size >= pt.LARGE_EXPORT else ""
        ex["run"] = dict(i.run)
        ex["fullLabel"] = f"{words['fullExport']} ({size_text(size)})" if picked else words["fullExport"]
        prev = i.preview
        cards = [{**c, "checked": c["key"] in i.ticked} for c in self.cards(prev.cards)] if prev else []
        imp: dict[str, Any] = {
            "file": i.incoming_file,
            "isZip": i.incoming_zip,
            "readme": i.incoming_readme,
            "cards": cards,
            "skipped": list(prev.skipped) if prev else [],
            "notes": list(prev.notes) if prev else [],
            "refusals": list(prev.refusals) if prev else [],
            "newProfile": i.new_profile,
            "newName": i.new_name,
            "error": i.error,
            "pct": i.import_pct,
            "clashes": self.clashes(prev.clashes, i.new_profile) if prev else [],
        }
        imp["canImport"] = bool(
            prev and not prev.refusals and (i.ticked & {c["key"] for c in cards}) and not prev.undecided
        )
        b = i.bundled
        bun = {
            "names": i.names,
            "which": i.which,
            "lines": list(b.lines) if b else [],
            "skipped": [],
            "refusals": list(b.refusals) if b else [],
            "newProfile": i.new_profile,
            "newName": i.new_name,
            "canImport": bool(b and b.ok and not b.undecided),
            "clashes": self.clashes(b.clashes, i.new_profile) if b else [],
        }
        return {
            "hasProfile": i.profile is not None,
            "profileName": i.profile.stem if i.profile else "",
            "ex": ex,
            "imp": imp,
            "bun": bun,
        }

    def readme(self, name: str, version: str, author: str, picked: list[ModLike]) -> str:
        return pt.readme_text(name, version, author, [(m.name, m.enabled) for m in picked])

    def seconds(self, s: float) -> str:
        s = int(round(s))
        if s < 60:
            return tr("{n} s").format(n=max(1, s))
        m, s = divmod(s, 60)
        return tr("{m} min {s} s").format(m=m, s=s) if m < 60 else tr("{h} h {m} min").format(h=m // 60, m=m % 60)

    def summary(self, full: bool, n: int, size: int, configs: bool, save: bool, password: bool) -> str:
        """Nothing: the Include boxes, the mod total and the Full export label already say what the file holds."""
        return ""

    def reason(self, name_ok: bool, folder_ok: bool, mods_ok: bool, busy: str) -> str:
        """Why Export is off, in one line ("" when it is on)."""
        if busy:
            return busy
        if not name_ok:
            return tr("Give the export a name.")
        if not folder_ok:
            return tr("Choose an output folder.")
        return "" if mods_ok else tr("Tick at least one mod.")

    def big_warning(self, total: int, biggest: list[tuple[str, int]]) -> str:
        names = ", ".join(f"{n} ({size_text(sz)})" for n, sz in biggest)
        return tr("The biggest: {names}. Untick mods your friend already has to make it smaller.").format(names=names)

    def confirm_big(self, total: int, apply: str) -> Confirm:
        t = self.seconds(total / (pt.EXPORT_MBPS * 1024**2))
        return Confirm(
            tr("Export a big file?"),
            (tr("The zip will be about {size}. This may take around {t}.").format(size=size_text(total), t=t),),
            apply,
        )

    def progress(self, done: int, total: int, n: int, count: int, elapsed: float) -> dict:
        pct = int(100 * done / total) if total else 0
        left = elapsed / done * (total - done) if done and elapsed >= 2 else -1
        return {
            "pct": pct,
            "title": tr("{pct}%  ·  file {n} of {count}").format(pct=pct, n=n, count=count),
            "bytes": tr("{done} of {total}").format(done=size_text(done), total=size_text(total)),
            "eta": tr("About {t} left").format(t=self.seconds(left))
            if left >= 0
            else tr("Working out the time left..."),
        }

    def done_text(self, path: Path, size: int, took: float) -> str:
        return tr("Done: {name} ({size}, took {t}).").format(name=path.name, size=size_text(size), t=self.seconds(took))

    def cancelled(self) -> str:
        return tr("Export cancelled. Nothing was written.")

    def failed(self, why: str) -> str:
        return tr("The export did not finish: {why} Nothing was written.").format(why=why.rstrip(".") + ".")

    # ---- export
    def total(self, picked: int, size: int) -> str:
        return plural("{n} mod · {size}", "{n} mods · {size}", picked).format(n=picked, size=size_text(size))

    def exported(self, path: Path) -> str:
        return tr("Exported {name}").format(name=path.name)

    def need_name(self) -> str:
        return tr("Give the export a name first.")

    def need_folder(self) -> str:
        return tr("Choose an output folder first.")

    def need_mod(self) -> str:
        return tr("Tick at least one mod.")

    def open_folder(self) -> str:
        return tr("Open folder")

    # ---- import
    def file_line(self, opened: pt.Opened) -> str:
        bits = [opened.name]
        if opened.version:
            bits.append(tr("version {v}").format(v=opened.version))
        if opened.author:
            bits.append(tr("by {a}").format(a=opened.author))
        kind = tr("full export") if opened.kind == "zip" else tr("share list")
        return " · ".join(bits) + "  (" + kind + ")"

    def cards(self, cards: list[pt.CardFacts]) -> list[dict]:
        return [
            {
                "key": c.key,
                "title": tr("The profile ({name})").format(name=c.title) if c.key == pt.PROFILE_CARD else c.title,
                "path": str(c.path),
                "lines": c.lines,
                "leftOut": c.left_out,
                "isNew": c.new,
            }
            for c in cards
        ]

    def clashes(self, clashes: list[profile_import.Clash], new_profile: bool) -> list[dict]:
        """The cards for mods that differ from an installed one (profile_import.ImportPreview.clashes). Versions are
        labels only; nothing here says which copy is newer."""
        out = []
        for c in clashes:
            parts = []
            if c.changed[0]:
                n = plural("{n} file changed", "{n} files changed", c.changed[0]).format(n=c.changed[0])
                parts.append(f"{n} ({size_text(c.changed[1])})")
            if c.added[0]:
                n = plural("{n} file added", "{n} files added", c.added[0]).format(n=c.added[0])
                parts.append(f"{n} ({size_text(c.added[1])})")
            if c.removed[0]:
                n = plural("{n} file not in the incoming copy", "{n} files not in the incoming copy", c.removed[0])
                parts.append(f"{n.format(n=c.removed[0])} ({size_text(c.removed[1])})")
            date = (tr("installed {date}") if c.recorded else tr("installed about {date}")).format(date=c.installed)
            none = tr("No version found")
            out.append(
                {
                    "key": c.key,
                    "name": c.key,
                    "diff": " · ".join(parts),
                    "incoming": tr("Version {v}").format(v=c.label_in) if c.label_in else none,
                    "mine": " · ".join([tr("Version {v}").format(v=c.label_mine) if c.label_mine else none, date]),
                    "choice": c.choice or "",
                    "suggested": c.default == "incoming",
                    "canBoth": not new_profile,
                }
            )
        return out

    def unreadable(self, why: str) -> str:
        return tr("Can't use that file. {why}").format(why=why)

    def imported(self, name: str) -> str:
        return tr("Imported into {name}. Undo it from Activity.").format(name=name)

    def import_failed(self, why: str) -> str:
        return tr("Not imported. {why}").format(why=why)

    def error_text(self, e: OperationError) -> str:
        """The sentence for an engine refusal; a code without words of its own shows the engine's message."""
        if e.code == "name_needed":
            return tr("Give the new profile a name.")
        if e.code == "no_preview":
            return tr("Preview the file first.")
        if e.code == "not_found" and "resource" in e.details:
            return tr("That file is no longer open. Open it again.")
        if e.code == "stale":
            return tr("That changed since you were asked. Try again.")
        if e.code == "busy":
            return (
                tr("The game is running.")
                if e.details.get("reason") == "game_running"
                else tr("Another operation is running.")
            )
        return e.message
