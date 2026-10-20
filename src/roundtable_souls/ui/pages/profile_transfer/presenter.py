"""The Export / Import profile page's presenter (technical specification, "Export / Import profile"): every word the
page shows and the plain-text form of the facts services/profile_transfer.py reads. Plain Python, every string
through tr()."""

from __future__ import annotations

from pathlib import Path

from roundtable_souls.services import profile_transfer as pt
from roundtable_souls.ui.text import plural, tr


def size_text(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{max(1, n // 1024)} KB" if n else "0 KB"


class ProfileTransferPresenter:
    """Pure: everything the page shows comes from the arguments."""

    open_window_text = property(lambda self: tr("Export / Import profile (new window)"))
    open_window_tip = property(
        lambda self: tr(
            "The new Export / Import profile page, in a window of its own: share a profile with a friend, or bring "
            "one in."
        )
    )

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
            "version": tr("Version"),
            "author": tr("Author"),
            "mods": tr("Mods in the export"),
            "outside": tr("Outside your library: tick it to include it anyway."),
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
            "chooseFolder": tr("Choose..."),
            "export": tr("Export"),
            "exporting": tr("Exporting..."),
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
                "Nothing in the download runs. Only the mods the profile points at are copied into your library."
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

    def seconds(self, s: float) -> str:
        s = int(round(s))
        if s < 60:
            return tr("{n} s").format(n=max(1, s))
        m, s = divmod(s, 60)
        return tr("{m} min {s} s").format(m=m, s=s) if m < 60 else tr("{h} h {m} min").format(h=m // 60, m=m % 60)

    def summary(self, full: bool, n: int, size: int, configs: bool, save: bool, password: bool) -> str:
        yes, no = tr("yes"), tr("no")
        pw = yes if password and configs else no
        if not full:
            return tr("One small file: {mods}, settings files {c}, password {p}.").format(
                mods=plural("{n} mod", "{n} mods", n).format(n=n), c=yes if configs else no, p=pw
            )
        return tr("The zip will hold {mods}, about {size}. Settings files: {c}. Save: {s}. Password: {p}.").format(
            mods=plural("{n} mod", "{n} mods", n).format(n=n),
            size=size_text(size),
            c=yes if configs else no,
            s=yes if save else no,
            p=pw,
        )

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
        return tr(
            "This export is about {size}. The biggest: {names}. Untick mods your friend already has to make it smaller."
        ).format(size=size_text(total), names=names)

    def confirm_big(self, total: int) -> tuple[str, list[str]]:
        t = self.seconds(total / (pt.EXPORT_MBPS * 1024**2))
        return tr("Export a big file?"), [
            tr("The zip will be about {size}. This may take around {t}.").format(size=size_text(total), t=t)
        ]

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

    def mod_note(self, item: pt.Item) -> str:
        return "" if item.inside else tr("Outside your library")

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
    def file_line(self, incoming: pt.Incoming) -> str:
        s = incoming.share
        bits = [s.name or incoming.path.stem]
        if s.profile_version:
            bits.append(tr("version {v}").format(v=s.profile_version))
        if s.author:
            bits.append(tr("by {a}").format(a=s.author))
        kind = tr("full export") if incoming.kind == "zip" else tr("share list")
        return " · ".join(bits) + "  (" + kind + ")"

    def cards(self, prev: pt.Preview) -> list[dict]:
        return [
            {
                "key": c.key,
                "title": tr("The profile ({name})").format(name=c.title) if c.key == pt.PROFILE_CARD else c.title,
                "path": str(c.path),
                "lines": c.lines,
                "leftOut": c.left_out,
                "isNew": c.new,
            }
            for c in prev.cards
        ]

    def clashes(self, prev, new_profile: bool) -> list[dict]:
        """The cards for mods that differ from an installed one (profile_import.ImportPreview.clashes). Versions are
        labels only; nothing here says which copy is newer."""
        out = []
        for c in prev.clashes:
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
                    "usedBy": tr("Used by {names}").format(names=", ".join(c.users)) if c.users else "",
                    "choice": c.choice or "",
                    "suggested": c.default == "incoming",
                    "sharedNote": tr(
                        "Other profiles use your copy, so it is not replaced: this profile gets its own copy beside it."
                    )
                    if c.shared and c.choice == "incoming"
                    else "",
                    "canBoth": not new_profile,
                }
            )
        return out

    def unreadable(self, why: str) -> str:
        return tr("Can't use that file. {why}").format(why=why)

    def imported(self, name: str) -> str:
        return tr("Imported into {name}. Undo is on the Activity page.").format(name=name)

    def import_failed(self, why: str) -> str:
        return tr("Not imported. {why}").format(why=why)

    def lines_of(self, prev) -> list[str]:
        """The S3g preview lines of a bundled profile."""
        return list(prev.lines)
