"""The Mods page's presenter (technical specification §8.10, Mods): the header strip, the two groups and their rows
with the closed tag vocabulary, the not-loaded and loads-nothing lines, the Parameters card, the InfoBars, and the
words of every confirmation and refusal the page shows. Plain Python, every string through tr(); it turns the
facts services/profile_mods.py reads (PageFacts, a Load order scan, the rebuild tool's state) into what the page
shows. The adapter hands it to QML; the Widgets Mods page uses its confirmation words too."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls.game import catalog
from roundtable_souls.mods import shared_mods
from roundtable_souls.services import profile_mods
from roundtable_souls.services.profile_mods import PageFacts, Removal
from roundtable_souls.ui.pages.mods import load_order
from roundtable_souls.ui.text import plural, tr

MAX_TAGS = 2  # tags shown on a row; the rest are in its tooltip
MAX_DEPS = 3  # dependencies named in the status line before "N others"


# ----------------------------------------------------------------------------- what the page shows
@dataclass(frozen=True)
class Tag:
    text: str
    level: str  # the QML Pill's level: danger | warning | accent | muted
    icon: str = ""
    tip: str = ""  # the hover sentence


@dataclass(frozen=True)
class Row:
    index: int  # the profile block index
    kind: str
    position: int  # 1-based, in the order the page shows
    name: str
    enabled: bool
    locked: bool  # the mod that must stay last: no drag, no move
    tags: tuple[Tag, ...]  # at most MAX_TAGS
    more: str  # the tags beyond MAX_TAGS and the folder, for the tooltip
    status: str
    status_error: bool
    has_configs: bool
    configs_tip: str
    path: str
    shared: int = 0  # profiles using this Shared mod (0: Separate)
    can_share: bool = False  # a Separate package of the profile's own folder: it can be shared


@dataclass(frozen=True)
class Line:
    """A muted line under a group header: "2 folders ... are not loaded · Add..." or "<entry> loads nothing"."""

    text: str
    action: str  # the link's words ("Add...", "Remove")
    index: int = -1  # the entry the action is about (-1: none)


@dataclass(frozen=True)
class Group:
    kind: str
    title: str
    icon: str
    count: str
    empty: str  # "" when it has rows
    lines: tuple[Line, ...]
    rows: tuple[Row, ...]


@dataclass(frozen=True)
class Health:
    text: str
    level: str  # success | warning | danger


@dataclass(frozen=True)
class Parameters:
    visible: bool
    state: str  # combined | single | stacked | stale | failed | ""
    pill: str
    level: str  # success | muted | warning | danger
    reasons: tuple[str, ...]
    packs: str
    action: str  # the main button's words: "Combine", "Rebuild" or "" (none)
    blocked: str  # why it cannot run now ("" when it can)
    fingerprint: str = ""  # "Parameters fingerprint: 1A2B3C4D (flora's regulation.bin)", "" without one
    fingerprint_note: str = ""  # what co-op partners do with it


@dataclass(frozen=True)
class Notice:
    """One InfoBar: key says what it is (online, stale, allow-tool, recovered), so the adapter knows what its action
    does."""

    key: str
    severity: str  # info | success | warning | error
    text: str
    action: str
    closable: bool


@dataclass(frozen=True)
class ModsState:
    title: str
    counts: str
    health: Health | None
    groups: tuple[Group, ...]
    parameters: Parameters
    notices: tuple[Notice, ...]
    empty: str = ""  # the page's text when there is no profile ("" when there is one)


@dataclass(frozen=True)
class Confirm:
    """A confirmation's words: the title states the action, the changes are what happens, warning and safety the
    risk and the way back; option a check box (with its starting state); apply the button."""

    title: str
    changes: tuple[str, ...]
    apply: str
    warning: str = ""
    safety: str = ""
    detail: str = ""
    option: str = ""
    option_checked: bool = False


@dataclass(frozen=True)
class Refusal:
    title: str
    body: str


@dataclass(frozen=True)
class Pick:
    """A tick list's words: none is the button that goes on with nothing ticked ("" when one must be ticked)."""

    title: str
    body: str
    apply: str
    none: str = ""


@dataclass(frozen=True)
class OverhaulMenu:
    """The header overflow's overhaul entries (an overhaul installed with the launcher, a preview): shown while the
    switch is on and the game has an overhaul the launcher can install (owner, D4 A)."""

    visible: bool
    install: str
    remove: str
    can_remove: bool
    clean: str
    can_clean: bool


# ----------------------------------------------------------------------------- the presenter
@dataclass
class ModsPresenter:
    """Pure: everything the page shows comes from the arguments."""

    notices_shown: int = 2  # InfoBars at once; the rest wait
    _closed: set[tuple[str, str]] = field(default_factory=set)  # (profile, notice kind) closed this session

    # ---- the page's fixed words
    install_text = property(lambda self: tr("Install mod"))
    install_menu = property(lambda self: (tr("From archive or DLL..."), tr("From folder...")))
    profile_folder_text = property(lambda self: tr("Profile folder"))
    edit_as_text_text = property(lambda self: tr("Edit as text"))
    gear_menu = property(lambda self: (tr("Profile settings..."), tr("Versions..."), tr("Delete profile...")))
    more_menu = property(lambda self: (tr("Rescan"),))
    open_window_text = property(lambda self: tr("Open new Mods window"))
    open_window_tip = property(lambda self: tr("A preview of the new Mods page, in its own window."))
    move_menu = property(lambda self: (tr("Move up"), tr("Move down"), tr("Move to top"), tr("Move to bottom")))

    def words(self) -> dict[str, str]:
        """Every fixed label the page shows, by key, for the view (nothing is typed into the QML)."""
        install_file, install_folder = self.install_menu
        settings, versions, delete = self.gear_menu
        up, down, top, bottom = self.move_menu
        return {
            "install": self.install_text,
            "installFile": install_file,
            "installFolder": install_folder,
            "profileFolder": self.profile_folder_text,
            "editAsText": self.edit_as_text_text,
            "profileSettings": settings,
            "versions": versions,
            "deleteProfile": delete,
            "exportProfile": tr("Export profile..."),
            "importProfile": tr("Import profile..."),
            "rescan": tr("Rescan"),
            "addExisting": tr("Add existing..."),
            "more": tr("More"),
            "gearTip": tr("Profile menu"),
            "healthTip": tr("Opens the Parameters card and the Load order panel"),
            "moveUp": up,
            "moveDown": down,
            "moveTop": top,
            "moveBottom": bottom,
            "lockedTip": tr("Its rebuild tool keeps it last, so it cannot be moved."),
            "optionsTip": tr("Mod options"),
            "configsTip": tr("has config files"),
            "attachTip": tr("Attach a config file to this DLL"),
            "removeTip": tr("Remove from the profile"),
            "loadsNothing": tr("Loads nothing"),
            "dropToInstall": tr("Drop to install"),
            "parameters": tr("Parameters"),
            "undoRebuild": tr("Undo rebuild"),
            "redoRebuild": tr("Redo rebuild"),
            "keepNewest": tr("Keep the newest {n} backups").format(n=profile_mods.KEEP_TOOL_BACKUPS),
            "openRebuildLog": tr("Open rebuild log"),
            "allowTool": tr("Allow rebuild tool"),
            "details": tr("Details"),
            "copy": tr("Copy"),
            "loadOrder": tr("Load order"),
            "staysLast": tr("Stays last"),
            "fixOrder": tr("Fix order"),
            "sharedFiles": tr("Files two packages both ship"),
            "showAll": tr("Show all"),
            "showFewer": tr("Show fewer"),
            "refused": tr("Entries me3 would refuse"),
            "nothingRefused": tr("None: me3 starts with this profile."),
            "saved": tr("Saved"),
            "unsaved": tr("Unsaved changes"),
            "save": tr("Save"),
            "discard": tr("Discard"),
            "cancel": tr("Cancel"),
            "close": tr("Close"),
            "createProfile": tr("Create a profile"),
            "unsavedTitle": tr("Unsaved changes"),
            "unsavedBody": tr(
                "The .me3 text has changes that are not saved. Save them, or discard them and go back to the rows?"
            ),
            "undo": tr("Undo"),
            "profileRenameTip": tr("Rename profile"),
            "profileRenameField": tr("Profile name"),
            "profileRenameHelp": tr("Enter renames it. Esc cancels."),
            "rename": tr("Rename..."),
            "share": tr("Share"),
            "useInOthers": tr("Use in other profiles..."),
            "useSeparate": tr("Use a separate copy"),
            "library": tr("Shared mods..."),
            "libraryTitle": tr("Shared mods"),
            "libraryBody": tr(
                "Mods that several profiles use from one copy. Their files are read-only; use a separate copy to edit "
                "them."
            ),
            "libraryEmpty": tr(
                "Nothing is shared yet. Share a package from its row to keep one copy for several profiles."
            ),
            "removeUnused": tr("Remove unused versions..."),
            "notUsed": tr("Not used"),
            "installedOn": tr("Installed {date}"),
            "usedBy": tr("Used by {names}"),
            "renameTitle": tr("Rename {name}"),
            "renameHint": tr("The folder is renamed too, and a package's id with it."),
            "renameNew": tr("New name"),
            "renameButton": tr("Rename"),
            **self.dialog_words(),
        }

    def dialog_words(self) -> dict[str, str]:
        """The dialogs' labels: Mod options, Profile settings, Versions, Add existing."""
        from roundtable_souls.mods.profile import SETTING_TEXT

        words = {
            "optionsTitle": tr("Mod options: {name}"),
            "enabled": tr("Enabled"),
            "packageId": tr("Package id"),
            "loadAfter": tr("Load after"),
            "loadBefore": tr("Load before"),
            "optional": tr("Optional"),
            "optionalDep": tr("optional"),
            "optionalNative": tr("Optional (the game starts without it)"),
            "loadEarly": tr("Load early"),
            "loadEarlyHelp": tr("Starts this DLL before the game sets itself up."),
            "loadEarlyTip": tr("me3 setting: load_early"),
            "initializer": tr("Run a function when it loads"),
            "initializerHelp": tr(
                "Some DLLs need the game to call one of their functions, or to wait, before they work."
            ),
            "initializerTip": tr("me3 setting: initializer"),
            "initNone": tr("None"),
            "initFunction": tr("Call a function"),
            "initDelay": tr("Wait (ms)"),
            "finalizer": tr("Run a function when the game closes"),
            "finalizerTip": tr("me3 setting: finalizer"),
            "staysLastOption": tr("This mod must stay last"),
            "staysLastHelp": tr("Its rebuild tool combines the other packages' parameters into it."),
            "rebuildFile": tr("Rebuild-tool file"),
            "configFiles": tr("Config files"),
            "openOnModConfigs": tr("Open on Mod Configs"),
            "noDeps": tr("No other entry of this kind to depend on."),
            "settingsTitle": tr("Profile settings"),
            "meDefault": tr("me3 default"),
            "on": tr("On"),
            "off": tr("Off"),
            "versionsTitle": tr("Versions"),
            "versionsBody": tr("The copies kept before each change to the profile, newest first."),
            "noVersions": tr("No earlier copies yet."),
            "restore": tr("Restore"),
            "addPackagesTitle": tr("Mod folders that are not loaded"),
            "addNativesTitle": tr("DLLs that are not loaded"),
            "addBody": tr(
                "Tick the ones to add. Each gets its own entry, last in the load order. Nothing is copied or moved. "
                "Skip alternates you keep switched off."
            ),
            "add": tr("Add"),
            "nothingToAdd": tr("Every folder here is loaded already."),
        }
        for key, (label, help_text) in SETTING_TEXT.items():
            words[f"setting_{key}"] = tr(label)
            words[f"setting_{key}_help"] = tr(help_text)
            words[f"setting_{key}_tip"] = tr("me3 setting: {key}").format(key=key)
        return words

    def page(
        self,
        facts: PageFacts | None,
        scan: dict | None = None,
        *,
        game_running: bool = False,
        tool_to_allow=None,
        recovered: tuple[str, ...] = (),
        seamless: str = "",
        no_profiles: bool = False,
        duplicated: tuple[int, int] = (0, 0),
    ) -> ModsState:
        """The page for one profile's facts. scan: the Load order scan for this profile (None until it lands);
        tool_to_allow: a rebuild tool to ask about (services.profile_mods.tool_to_offer); recovered: interrupted
        changes put right as the page opened (one line each);
        no_profiles: this game has no profile at all, so the page says how to start."""
        if facts is None:
            words = (
                tr(
                    "You have no profile yet. A profile is the list of mods the game starts with. "
                    "Create one, then add mods to it here."
                )
                if no_profiles
                else tr("Pick a profile first.")
            )
            return ModsState(tr("Mods"), "", None, (), self.parameters(None, game_running), (), words)
        if facts.error:
            return ModsState(
                facts.profile.stem,
                "",
                None,
                (),
                self.parameters(None, game_running),
                (),
                tr("The profile could not be read: {why}").format(why=facts.error),
            )
        if scan is not None and not load_order.same_profile(scan, facts.profile):
            scan = None
        clashes = load_order.clash_counts(scan)
        groups = tuple(self._group(facts, kind, clashes) for kind in ("package", "native"))
        n_pk, n_nt = len(groups[0].rows), len(groups[1].rows)
        counts = "  ·  ".join(
            (
                plural("{n} package", "{n} packages", n_pk).format(n=n_pk),
                plural("{n} native", "{n} natives", n_nt).format(n=n_nt),
            )
        )
        health = scan.get("health") if scan else None
        return ModsState(
            title=facts.profile.stem,
            counts=counts,
            health=self.health(scan),
            groups=groups,
            parameters=self.parameters(health, game_running, facts.fingerprint, facts.regulation),
            notices=self.notices(
                health,
                tool_to_allow,
                recovered,
                facts.online_with,
                facts.regulation,
                str(facts.profile),
                seamless,
                facts.folder,
                len(facts.loose_dlls),
                duplicated,
                facts.outside,
            ),
        )

    # ---- header
    def health(self, scan: dict | None) -> Health | None:
        """The merge-health pill: red when files clash, amber when a rebuild is needed, green otherwise; None until
        the first scan lands."""
        if not scan:
            return None
        lost = load_order.lost_files(scan)
        if lost:
            return Health(plural("{n} file clashes", "{n} files clash", lost).format(n=lost), "danger")
        state = (scan.get("health") or {}).get("state")
        if state in ("stale", "failed", "stacked"):
            return Health(tr("Rebuild needed"), "warning")
        return Health(tr("All mods apply"), "success")

    # ---- groups and rows
    def _group(self, facts: PageFacts, kind: str, clashes: dict[str, int]) -> Group:
        by_index = {e["index"]: e for e in facts.entries}
        nothing = set(facts.loads_nothing)
        order = [i for i in facts.display.get(kind, ()) if i not in nothing and i in by_index]
        listed = set(order)
        order += [e["index"] for e in facts.entries if e["kind"] == kind and e["index"] not in listed | nothing]
        rows = tuple(self._row(facts, by_index[i], pos, clashes) for pos, i in enumerate(order, start=1))
        lines = []
        unloaded = facts.not_loaded.get(kind, 0)
        if unloaded:
            lines.append(
                Line(
                    (
                        plural(
                            "{n} folder in this profile is not loaded",
                            "{n} folders in this profile are not loaded",
                            unloaded,
                        )
                        if kind == "package"
                        else plural(
                            "{n} DLL in this profile is not loaded", "{n} DLLs in this profile are not loaded", unloaded
                        )
                    ).format(n=unloaded),
                    tr("Add..."),
                )
            )
        for i in facts.loads_nothing:
            e = by_index.get(i)
            if e is not None and e["kind"] == kind:
                lines.append(
                    Line(
                        tr("{name} loads nothing: it points at a folder of mods").format(name=e["name"]),
                        tr("Remove"),
                        i,
                    )
                )
        on = sum(1 for r in rows if r.enabled)
        count = (
            (
                tr("{on} loaded").format(on=on)
                + (tr(", {off} off").format(off=len(rows) - on) if on != len(rows) else "")
            )
            if rows
            else ""
        )
        return Group(
            kind=kind,
            title=tr("Packages") if kind == "package" else tr("DLL mods"),
            icon="ZipFolder" if kind == "package" else "Code",
            count=count,
            empty=""
            if rows
            else (tr("No packages in this profile.") if kind == "package" else tr("No DLL mods in this profile.")),
            lines=tuple(lines),
            rows=rows,
        )

    def _row(self, facts: PageFacts, e: dict, position: int, clashes: dict[str, int]) -> Row:
        i = e["index"]
        tags: list[Tag] = []
        if i in facts.missing:
            tags.append(Tag(tr("Missing"), "danger", "Cancel"))
        if i in facts.stays_last:
            tags.append(Tag(tr("Stays last"), "accent", "Pin"))
        lost = clashes.get(str(e.get("id") or e["name"]), 0)
        if lost:
            tags.append(
                Tag(
                    plural("Clash · {n} file", "Clash · {n} files", lost).format(n=lost),
                    "warning",
                    "Info",
                    plural(
                        "{n} file is also in another mod. The later one in the load order wins.",
                        "{n} files are also in another mod. The later one in the load order wins.",
                        lost,
                    ).format(n=lost),
                )
            )
        if e["kind"] == "native" and e.get("load_early"):
            tags.append(
                Tag(tr("Loads early"), "muted", "Up", tr("load_early: starts this DLL before the game sets itself up."))
            )
        if e.get("optional"):
            tags.append(Tag(tr("Optional"), "muted", "Help"))
        if i in facts.loose_dlls:
            tags.append(Tag(tr("No folder"), "muted", "Info", tr("This DLL isn't in a folder of its own.")))
        shared = facts.shared.get(i, 0)
        if shared:
            tags.insert(
                0,
                Tag(
                    plural("Shared · {n} profile", "Shared · {n} profiles", shared).format(n=shared),
                    "accent",
                    "Link",
                    tr("Its files are read-only here. Use a separate copy to edit them."),
                ),
            )
        elif facts.library_used and i in facts.can_share:
            tags.insert(0, Tag(tr("Separate"), "muted", "", tr("This profile has its own copy of the files.")))
        problems = facts.problems.get(i, ())
        status_error = bool(problems)
        status = "  ·  ".join(problems) if problems else self._status(e, facts.empty.get(i, ""))
        configs = facts.configs.get(i, ())
        hidden = [t.text for t in tags[MAX_TAGS:]]
        more = "\n".join([*hidden, e.get("path") or ""]).strip()
        return Row(
            index=i,
            kind=e["kind"],
            position=position,
            name=e["name"],
            enabled=e.get("enabled", True) is not False,
            locked=i in facts.stays_last,
            tags=tuple(tags[:MAX_TAGS]),
            more=more,
            status=status,
            status_error=status_error,
            has_configs=bool(configs),
            configs_tip=", ".join(configs[:3]) + (f" +{len(configs) - 3}" if len(configs) > 3 else ""),
            path=str(e.get("path") or ""),
            shared=shared,
            can_share=i in facts.can_share,
        )

    @staticmethod
    def _status(e: dict, empty: str) -> str:
        """Dependencies and initializer / finalizer (tags carry the rest), or why a package folder loads nothing."""
        bits = []
        for key, word in (("load_after", tr("after")), ("load_before", tr("before"))):
            deps = [str(d["id"]) for d in e.get(key) or []]
            if deps:
                bits.append(
                    f"{word} {', '.join(deps)}"
                    if len(deps) <= MAX_DEPS
                    else tr("{word} {n} others").format(word=word, n=len(deps))
                )
        init = e.get("initializer") or {}
        if init.get("function"):
            bits.append(tr("calls {function}").format(function=init["function"]))
        elif isinstance(init.get("delay"), dict):
            bits.append(tr("waits {ms} ms").format(ms=init["delay"].get("ms", 0)))
        if e.get("finalizer"):
            bits.append(tr("finishes with {function}").format(function=e["finalizer"]))
        if empty == "empty":
            bits.append(tr("Empty. Game folders you put here (parts, chr, msg, ...) will load."))
        elif empty == "no-game-folders":
            bits.append(tr("No game folders (parts, chr, msg, ...) at its top level, so me3 loads nothing from it."))
        return "  ·  ".join(bits)

    # ---- the Parameters card
    def parameters(
        self, health: dict | None, game_running: bool, fingerprint=None, regulation: str = catalog.REGULATION
    ) -> Parameters:
        """Shown only when a package ships parameters (v2.1 A). fingerprint: game_checks.Fingerprint of the
        parameters the game will use (owner, D3 A: on this card, for co-op partners to compare)."""
        health = health or {}
        state = health.get("state") or ""
        packs = list(health.get("packs") or [])
        files = list(health.get("shared_files") or [])
        visible = bool(packs) or bool(files)
        backend = health.get("backend") or ""
        if state == "current":
            pill, level = (
                tr("Combined, up to date ({tool})").format(tool=backend) if backend else tr("Combined, up to date"),
                "success",
            )
        elif state == "single":
            pill, level = tr("One pack, used as is"), "muted"
        elif state == "stacked":
            pill, level = (
                tr("Stacked: {winner}'s regulation.bin wins, others ignored").format(
                    winner=health.get("winner") or "?"
                ),
                "warning",
            )
        elif state == "stale":
            pill, level = tr("Out of date"), "warning"
        elif state == "failed":
            pill, level = tr("Last rebuild failed"), "danger"
        else:
            pill, level = "", "muted"
        unmerged = bool(files) and not health.get("combine")
        if state == "stacked" or unmerged:
            action = tr("Combine") if health.get("can_combine") or unmerged else ""
        elif backend:
            action = tr("Rebuild")
        else:
            action = ""
        return Parameters(
            visible=visible,
            state="combined" if state == "current" else state,
            pill=pill,
            level=level,
            reasons=tuple(str(r) for r in health.get("reasons") or []),
            packs=", ".join(packs),
            action=action,
            blocked=tr("Blocked while the game runs") if game_running and action else "",
            fingerprint=self.fingerprint(fingerprint, regulation),
            fingerprint_note=tr(
                "Co-op partners need the same parameters. If your fingerprint differs from theirs, expect desyncs or a "
                "failed session."
            )
            if fingerprint is not None
            else "",
        )

    @staticmethod
    def fingerprint(fingerprint, regulation: str = catalog.REGULATION) -> str:
        if fingerprint is None:
            return ""
        whose = (
            tr("{package}'s {file}").format(package=fingerprint.source, file=regulation)
            if fingerprint.source
            else tr("the game's own {file}").format(file=regulation)
        )
        return tr("Parameters fingerprint: {short} ({whose})").format(short=fingerprint.short, whose=whose)

    # ---- InfoBars
    def notices(
        self,
        health: dict | None,
        tool_to_allow,
        recovered: tuple[str, ...],
        online_with: str = "",
        regulation: str = catalog.REGULATION,
        profile: str = "",
        seamless: str = "",
        folder: profile_mods.folder_check.FolderCheck | None = None,
        loose_dlls: int = 0,
        duplicated: tuple[int, int] = (0, 0),
        outside: bool = False,
    ) -> tuple[Notice, ...]:
        """In this order, two at most: online with changed parameters (a ban risk), out of date, the rebuild tool's
        permission, interrupted changes put right."""
        out = []
        if online_with:
            out.append(
                Notice(
                    "online",
                    "warning",
                    tr(
                        "This profile goes online with changed parameters ({package}'s {file}). FromSoftware's "
                        "servers can see the change."
                    ).format(package=online_with, file=regulation),
                    tr("Launch Offline"),
                    True,
                )
            )
        if folder is not None and folder.kind == profile_mods.folder_check.MISNAMED:
            out.append(
                Notice(
                    "folder",
                    "info",
                    tr("This profile's folder is named '{folder}'. Rename it to match the profile?").format(
                        folder=folder.folder
                    ),
                    tr("Rename folder"),
                    False,
                )
            )
        elif folder is not None and folder.kind == profile_mods.folder_check.CROWDED:
            out.append(
                Notice(
                    "folder",
                    "warning",
                    tr("This folder holds {n} profiles. Each profile needs its own folder.").format(n=folder.count),
                    tr("Split into folders"),
                    False,
                )
            )
        if loose_dlls:
            out.append(
                Notice(
                    "dll-folders",
                    "info",
                    plural(
                        "{n} DLL mod isn't in its own folder.", "{n} DLL mods aren't in their own folders.", loose_dlls
                    ).format(n=loose_dlls),
                    tr("Put in folders"),
                    False,
                )
            )
        if (health or {}).get("state") == "stale":
            reasons = list((health or {}).get("reasons") or [])
            out.append(
                Notice(
                    "stale",
                    "warning",
                    tr("Combined parameters are out of date") + (f": {reasons[0]}" if reasons else ""),
                    tr("Rebuild"),
                    False,
                )
            )
        if tool_to_allow is not None:
            out.append(
                Notice(
                    "allow-tool",
                    "warning",
                    tr("Allow {tool} to run? {mod} uses it to rebuild merged mods.").format(
                        tool=tool_to_allow.label, mod=tool_to_allow.package.get("name", "")
                    ),
                    tr("Allow..."),
                    False,
                )
            )
        for line in recovered:
            out.append(
                Notice(
                    "recovered",
                    "success",
                    tr("An interrupted change was put right: {what}").format(what=line),
                    "",
                    True,
                )
            )
        if seamless:
            out.append(
                Notice(
                    "seamless",
                    "info",
                    tr(
                        "Seamless Co-op is also in the game folder. Move it into this profile, or clean up the game "
                        "folder."
                    )
                    if seamless == "move"
                    else tr(
                        "This profile loads its own Seamless Co-op, and the game folder holds one too. Two copies can "
                        "conflict."
                    ),
                    tr("Move into this profile...") if seamless == "move" else tr("Clean up the game folder..."),
                    True,
                )
            )
        if outside:
            out.append(
                Notice(
                    "outside",
                    "info",
                    tr("This profile is outside Bayle's folder, so Bayle can't manage its layout."),
                    tr("Move in..."),
                    False,
                )
            )
        if duplicated[1] > shared_mods.HINT_BYTES:
            out.append(Notice("library-hint", "info", self.hint_text(*duplicated), tr("Shared mods..."), True))
        return tuple(n for n in out if (profile, n.key) not in self._closed)[: self.notices_shown]

    def close_notice(self, key: str, profile: str = "") -> None:
        """A closed InfoBar stays closed for this profile only."""
        self._closed.add((profile, key))

    # ---- the Library
    @staticmethod
    def size_text(n: int) -> str:
        if n >= 1073741824:
            return f"{n / 1073741824:.1f} GB"
        return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"

    def library(self, info) -> list[dict]:
        """The Library dialog's rows (services.shared_mods.listing): each mod with its versions, "Installed <date>" and
        the label when there is one, the size, and who uses it. The version's id is never shown."""
        out = []
        for m in info:
            versions = []
            for v in m.versions:
                when = tr("Installed {date}").format(date=v.version.installed) if v.version.installed else ""
                versions.append(
                    {
                        "title": f"{when}  ·  {v.version.label}"
                        if v.version.label and when
                        else when or v.version.label,
                        "size": self.size_text(v.version.size),
                        "usedBy": tr("Used by {names}").format(names=", ".join(v.used_by))
                        if v.used_by
                        else tr("Not used"),
                        "unused": v.unused,
                    }
                )
            out.append({"name": m.mod.name, "size": self.size_text(m.size), "versions": versions})
        return out

    @staticmethod
    def share_confirm(names: list[str]) -> Confirm:
        return Confirm(
            tr("Share {name}").format(name=", ".join(names)),
            (
                tr("The files become shared mods, and this profile uses them from there."),
                tr("Other profiles can then use the same files without a copy of their own."),
                tr("Shared files are read-only; use a separate copy to edit them."),
            ),
            tr("Share"),
            safety=tr("Undo in Activity puts the copy back."),
        )

    @staticmethod
    def separate_confirm(name: str, size: int) -> Confirm:
        return Confirm(
            tr("Use a separate copy of {name}").format(name=name),
            (
                tr("This profile gets its own editable copy of the files ({size}).").format(
                    size=ModsPresenter.size_text(size)
                ),
            ),
            tr("Use a separate copy"),
            safety=tr("The other profiles keep using the shared files. Undo in Activity takes it back."),
        )

    @staticmethod
    def use_pick(name: str) -> Pick:
        return Pick(
            tr("Use {name} in other profiles").format(name=name),
            tr(
                "Tick the profiles that should use it. A profile with its own copy keeps it unless you tick it; "
                "ticking replaces the copy."
            ),
            tr("Use in these profiles"),
        )

    @staticmethod
    def use_row(name: str, has_copy: bool, uses: bool) -> str:
        if uses:
            return tr("{name} (uses it already; moves to this version)").format(name=name)
        return tr("{name} (has its own copy; ticking replaces it)").format(name=name) if has_copy else name

    @staticmethod
    def clean_confirm(count: int, size: int) -> Confirm:
        return Confirm(
            tr("Remove unused versions"),
            (
                plural(
                    "{n} version that no profile uses is deleted ({size}).",
                    "{n} versions that no profile uses are deleted ({size}).",
                    count,
                ).format(n=count, size=ModsPresenter.size_text(size)),
            ),
            tr("Remove"),
            safety=tr("They go to the Recycle Bin, and Undo in Activity brings them back."),
        )

    @staticmethod
    def duplicate_confirm(name: str) -> Confirm:
        return Confirm(
            tr("Copy {name}").format(name=name),
            (tr("The copy gets its own folder with copies of the mods."),),
            tr("Copy"),
            option=tr("Share the game-file mods with the original instead of copying them"),
            option_checked=False,
        )

    @staticmethod
    def hint_text(mods: int, size: int) -> str:
        return plural(
            "{n} mod is in several profiles ({size}). Save space by sharing",
            "{n} mods are in several profiles ({size}). Save space by sharing",
            mods,
        ).format(n=mods, size=ModsPresenter.size_text(size))

    # ---- confirmations and refusals (the Widgets page uses these words too)
    @staticmethod
    def split_confirm(profiles: int, copied: int, moved: int) -> tuple[str, list[str], str, str]:
        """(title, changes, safety, button) of the Split into folders confirmation."""
        return (
            tr("Split this folder into one folder per profile?"),
            [
                tr("{n} profiles, {m} mods copied, {k} moved.").format(n=profiles, m=copied, k=moved),
            ],
            tr("Undo in Activity."),
            tr("Split"),
        )

    @staticmethod
    def dll_folders_confirm(folders: int, moved: int, copied: int) -> tuple[str, list[str], str, str]:
        """(title, changes, safety, button) of the Put in folders confirmation."""
        changes = [
            plural("{n} DLL gets a folder in natives.", "{n} DLLs get a folder in natives.", folders).format(n=folders),
            plural("{n} file moves with it.", "{n} files move with them.", moved).format(n=moved),
        ]
        if copied:
            changes.append(
                plural(
                    "{n} settings file is copied, so other DLLs can still read it.",
                    "{n} settings files are copied, so other DLLs can still read them.",
                    copied,
                ).format(n=copied)
            )
        return (tr("Put DLL mods in their own folders?"), changes, tr("Undo in Activity."), tr("Put in folders"))

    def removal(self, profile, plan: Removal) -> Confirm:
        prof = Path(profile)
        changes = [
            tr("{name} is taken out of the profile {profile}, with its own comments").format(
                name=plan.name, profile=prof.name
            )
        ]
        if plan.merged:
            files = ", ".join(Path(f).name for f in plan.merged[:3])
            if len(plan.merged) > 3:
                files = tr("{files} and {n} more").format(files=files, n=len(plan.merged) - 3)
            changes.append(
                plural(
                    "Its {files} is still in the merged mods. Launch rebuilds them first, so the game does not use it",
                    "Its {files} are still in the merged mods. Launch rebuilds them first, so the game does not use them",
                    len(plan.merged),
                ).format(files=files)
            )
        return Confirm(
            title=tr("Remove {name} from the profile").format(name=plan.name),
            changes=tuple(changes),
            apply=tr("Remove"),
            warning=tr(
                "The game stops loading it at the next launch. A mod set to load after it is left waiting for it."
            ),
            safety=tr("Undo in Activity puts it back, including a folder moved to the Recycle Bin."),
            option=tr("Also move the folder {folder} to the Recycle Bin").format(folder=plan.folder.name)
            if plan.folder is not None and plan.can_recycle
            else "",
        )

    def holder(self, profile, name: str, needs: list[str]) -> Confirm:
        changes = [
            tr("Its entry is taken out of {profile}").format(profile=Path(profile).name),
            tr("Nothing changes in the game: it loaded no files of its own"),
            tr("The folder and every mod in it stay, and so do their entries"),
        ]
        if needs:
            changes.append(
                tr("{names} must load after it: that setting is taken out too").format(names=", ".join(needs))
            )
        return Confirm(
            tr("Remove '{name}' from the profile").format(name=name),
            tuple(changes),
            tr("Remove"),
            safety=tr("A backup copy of the profile is kept."),
        )

    def trim(self, extra: list[dict]) -> Confirm:
        size = sum(b["size"] for b in extra)
        keep = profile_mods.KEEP_TOOL_BACKUPS
        return Confirm(
            title=plural(
                "Move {n} older rebuild backup to the Recycle Bin",
                "Move {n} older rebuild backups to the Recycle Bin",
                len(extra),
            ).format(n=len(extra)),
            changes=tuple(f"{b['folder'].name}  ·  {b['size'] / 1048576:,.0f} MB" for b in extra),
            apply=tr("Move to the Recycle Bin"),
            safety=tr(
                "Frees {mb} MB once the Recycle Bin is emptied. The newest {keep} stay, so the latest rebuilds can "
                "still be undone."
            ).format(mb=f"{size / 1048576:,.0f}", keep=keep),
        )

    def tool(self, tool) -> Confirm:
        """Before a mod's rebuild tool runs for the first time (and after it changes): what it runs (owner, D2)."""
        return Confirm(
            title=tr("Run {tool}?").format(tool=tool.label),
            changes=(),
            apply=tr("Allow and run"),
            detail=tr("It comes with {mod} and runs:\n\n{what}").format(
                mod=tool.package.get("name", ""), what=tool.describe()
            ),
            warning=tr(
                "It is a program from a mod: allow it only for mods you trust. You are asked again when the tool changes."
            ),
        )

    def delete_profile(self, profile, overhaul: str = "") -> Confirm:
        """overhaul: the label of an overhaul the launcher installed in it (profile_mods.overhaul_to_keep)."""
        p = Path(profile)
        kept = (
            (tr("{label}'s shared files stay; Remove overhaul first to take them out too.").format(label=overhaul),)
            if overhaul
            else ()
        )
        return Confirm(
            title=tr("Delete profile {name}?").format(name=p.stem),
            changes=(tr("The profile moves to Deleted profiles."), tr("Its mod folders stay on disk."), *kept),
            apply=tr("Delete"),
        )

    def online(self) -> Confirm:
        return Confirm(
            title=tr("Turn online matchmaking on"),
            changes=(tr("This profile starts the game with the official servers reachable"),),
            apply=tr("Turn on"),
            warning=tr(
                "me3 blocks matchmaking by default because playing online with modded data can get the account banned."
            ),
            safety=tr("Nothing else in the profile changes; a backup copy of the file is kept."),
        )

    def delete_refusal(self, code: str | None, profile_name: str = "") -> Refusal | None:
        if code == profile_mods.DELETE_NO_PROFILE:
            return Refusal(tr("No profile"), tr("Pick a profile first."))
        if code == profile_mods.DELETE_MANAGED:
            return Refusal(
                tr("Not this one"),
                tr("{name} is managed by its installer. Delete it there.").format(
                    name=profile_name or tr("This profile")
                ),
            )
        if code == profile_mods.DELETE_BUSY:
            return Refusal(tr("Wait for the current job"), tr("Delete the profile when it finishes."))
        return None

    def rename_block(self, code: str | None, name: str, game_running: bool) -> str:
        """Why the profile can't be renamed or copied now, in words; "" when it can (code: services.profile_rename.refusal)."""
        if code == profile_mods.DELETE_NO_PROFILE:
            return tr("Pick a profile first.")
        if code == profile_mods.DELETE_MANAGED:
            return tr("{name} is managed by its installer. Rename it there.").format(name=name or tr("This profile"))
        if code == profile_mods.DELETE_BUSY:
            return tr("Wait for the current job to finish.")
        if game_running:
            return tr("Close the game first. It has these files open.")
        return ""

    def move_in_confirm(self, name: str, folder: str, moved: int, copied: int) -> tuple[str, tuple[str, ...], str, str]:
        """(title, changes, safety, apply) of the Move into Bayle's folder confirm."""
        line = tr("{n} mods move.").format(n=moved) if moved != 1 else tr("1 mod moves.")
        if copied:
            line = (
                tr("{n} mods move, {m} are copied because other profiles in {folder} use them.")
                if moved != 1
                else tr("1 mod moves, {m} are copied because other profiles in {folder} use them.")
            ).format(n=moved, m=copied, folder=folder)
        return (
            tr("Move {name} into Bayle's folder?").format(name=name),
            (line,),
            tr("Undo in Activity."),
            tr("Move"),
        )

    def move_refused(self, problem: str) -> Refusal:
        return Refusal(tr("Load order not changed"), problem)

    def move_busy(self) -> Refusal:
        return Refusal(tr("Load order not changed"), tr("Wait for the current job to finish."))

    def edit_options_text(self) -> str:
        return tr("Edit options")

    # ---- overhauls installed with the launcher (preview); the Widgets Overhaul button uses these words too
    def overhaul_menu(self, on: bool, has: dict | None, leftovers: bool) -> OverhaulMenu:
        """on: services.mods.overhaul_preview_on; has: services.mods.profile_overhaul; leftovers: any to clean."""
        return OverhaulMenu(
            visible=on,
            install=tr("Install an overhaul with the launcher (preview)..."),
            remove=tr("Remove {label}...").format(label=has["label"]) if has else tr("Remove overhaul..."),
            can_remove=has is not None,
            clean=tr("Clean up installer leftovers..."),
            can_clean=leftovers,
        )

    def overhaul_folder_title(self) -> str:
        return tr("Install an overhaul: pick the folder you unpacked it into")

    def overhaul_unreadable(self, folder, why: str) -> Refusal:
        return Refusal(tr("Can't install from {name}").format(name=Path(folder).name), why)

    def overhaul_install(self, profile, preview) -> Confirm | Refusal:
        """The confirmation for install.preview (overhaul_install.InstallPreview), or why it can't go ahead."""
        if not preview.ok:
            return Refusal(
                tr("{label} can't be installed here").format(label=preview.label), " ".join(preview.refusals)
            )
        return Confirm(
            title=(tr("Update {label} in {profile}") if preview.update else tr("Install {label} in {profile}")).format(
                label=preview.label, profile=Path(profile).name
            ),
            changes=(*preview.lines, *preview.notes),
            apply=tr("Update") if preview.update else tr("Install"),
            safety=tr(
                "If anything fails, nothing changes. Undo in Activity puts it back. The overhaul's own installer does "
                "not run."
            ),
        )

    def overhaul_installing(self, preview) -> str:
        return (tr("Updating {label}...") if preview.update else tr("Installing {label}...")).format(
            label=preview.label
        )

    def overhaul_put_back(self, label: str) -> Pick:
        return Pick(
            title=tr("Put back what {label}'s installer changed?").format(label=label),
            body=tr(
                "Its installer changed these in your profile (compared with its oldest backup of it). Tick the ones "
                "to put back; the others stay as they are now."
            ),
            apply=tr("Put back"),
            none=tr("Leave them"),
        )

    def overhaul_remove(self, profile, label: str, preview) -> Confirm | Refusal:
        """The confirmation for overhaul_install.RemovePreview: switching a shared dependency back off is its
        option, unticked (owner, 3.22-A)."""
        if not preview.ok:
            return self.overhaul_remove_failed(label, " ".join(preview.refusals))
        asked = ", ".join(str(e.entry) for e in preview.asked)
        return Confirm(
            title=tr("Remove {label} from {profile}").format(label=label, profile=Path(profile).name),
            changes=tuple(preview.lines),
            apply=tr("Remove"),
            safety=tr("Undo in Activity puts it all back. Folders go to the Recycle Bin."),
            option=tr("Also switch {names} back off, as it was before the install").format(names=asked)
            if asked
            else "",
        )

    def overhaul_remove_failed(self, label: str, why: str) -> Refusal:
        return Refusal(tr("Can't remove {label}").format(label=label), why)

    def overhaul_removing(self, label: str) -> str:
        return tr("Removing {label}...").format(label=label)

    def overhaul_leftovers_later(self, label: str) -> Refusal:
        """The note after removing a profile its installer made (a toast, not a refusal)."""
        return Refusal(
            tr("{label}'s installer left folders behind").format(label=label),
            tr("Clean up installer leftovers shows them with their sizes once the removal is done."),
        )

    def leftovers(self, more_after: bool) -> Pick:
        """more_after: the installer's backups are asked about next, so going on with nothing ticked is allowed."""
        return Pick(
            title=tr("Clean up installer leftovers"),
            body=tr(
                "What an overhaul's own installer left beside your profile that no profile uses any more. Ticked ones "
                "go to the Recycle Bin."
            ),
            apply=tr("Move to the Recycle Bin"),
            none=tr("Next") if more_after else "",
        )

    def leftover_backups(self, leftover) -> Confirm:
        """Asked one at a time, last: the only copy of the profile from before the overhaul."""
        return Confirm(
            title=tr("Also remove {name}?").format(name=leftover.path.name),
            changes=(tr("{what} goes to the Recycle Bin").format(what=leftover.label),),
            apply=tr("Move to the Recycle Bin"),
            warning=tr(
                "These are its installer's backups of your profiles: the only copy from before the overhaul was "
                "installed. Keep them unless you're sure you don't need them."
            ),
        )

    def leftovers_moving(self) -> str:
        return tr("Moving leftovers to the Recycle Bin...")
