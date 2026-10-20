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
        }

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

    def unreadable(self, why: str) -> str:
        return tr("Can't use that file. {why}").format(why=why)

    def imported(self, name: str) -> str:
        return tr("Imported into {name}. Undo is on the Activity page.").format(name=name)

    def import_failed(self, why: str) -> str:
        return tr("Not imported. {why}").format(why=why)

    def lines_of(self, prev) -> list[str]:
        """The S3g preview lines of a bundled profile."""
        return list(prev.lines)
