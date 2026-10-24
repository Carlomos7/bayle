"""The Install mod dialog's words and state (technical specification §8.2 and "Dialogs kept"). Plain Python, every
string through tr(): an InstallDraft holds the plan's facts the engine gave (services.mod_install.plan_facts) and what
the player has changed in it, view() turns both into what the QML dialog shows, and choices() turns the edits back
into the InstallChoices the engine installs with. The engine keeps nothing of the edits."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bayle.overhauls import basic
from bayle.platform.text import tr
from bayle.services.mod_configs import SetupValues
from bayle.services.mod_install import InstallChoices, OverhaulPreview

from bayle_qt.pages.mods.file_actions import file_action_text, shown_path


def _size(n: int) -> str:
    return f"{n / 1048576:.1f} MB" if n >= 1048576 else f"{max(1, n // 1024)} KB"


def group_text() -> dict[str, str]:
    """What each kind of file is, and (for the ones left unticked) why it is not needed."""
    return {
        "game": tr("game files"),
        "regulation": tr("the game's parameters"),
        "dll": tr("the DLL mod"),
        "settings": tr("its settings"),
        "files": tr("its files"),
        "doc": tr("readme / docs, not needed to play"),
        "profile": tr("an me3 profile, not needed: the mod is added to yours"),
        "loader": tr("another mod loader, not needed with me3"),
        "other": tr("not recognised, installed as shipped"),
    }


# the game's msg/<folder> names
LANGUAGES = {
    "engus": "English",
    "jpnjp": "Japanese",
    "frafr": "French",
    "deude": "German",
    "itait": "Italian",
    "spaes": "Spanish (Spain)",
    "spaar": "Spanish (Latin America)",
    "polpl": "Polish",
    "porbr": "Portuguese (Brazil)",
    "rusru": "Russian",
    "korkr": "Korean",
    "zhotw": "Chinese (Traditional)",
    "zhocn": "Chinese (Simplified)",
    "thath": "Thai",
    "araae": "Arabic",
}
LOADED = ("game", "regulation", "dll", "files")  # something of these must stay ticked


def words() -> dict[str, str]:
    """The fixed labels of the dialog, by key."""
    return {
        "variantLabel": tr("The archive has more than one: which to install"),
        "folderName": tr("Folder name"),
        "id": tr("Id"),
        "whatToInstall": tr("What to install"),
        "itemsNote": tr("Unticked files are left out. Tick one to keep it with the mod anyway."),
        "regulation": tr("regulation.bin"),
        "install": tr("Install"),
        "cancel": tr("Cancel"),
        "working": tr("Working..."),
        "importInstead": tr("Import its profile instead..."),
        "overhaulOption": tr("Set up as an overhaul (loads last, merged with the mods before it)"),
        "dllEarly": tr("Start before the game sets itself up"),
        "dllAfter": tr("Load after the other DLLs"),
        "dllInit": tr("Run a function when it loads"),
    }


@dataclass
class InstallDraft:
    """plan: the engine's plan facts; profile: the profile it installs into. overhaul_on: the Settings switch
    "Install overhauls with the launcher (preview)" is on, which is when the overhaul option is offered. install_id
    and stamp: the open install and the profile's stamp the engine gave."""

    plan: dict
    profile: Path
    overhaul_on: bool = False
    install_id: str = ""
    stamp: tuple[int, int] | None = None
    name_text: str = ""
    id_text: str = ""
    id_follows: bool = True
    variant: str | None = None
    ticks: dict[str, bool] = field(default_factory=dict)
    place_last: bool = False  # regulation.bin goes last instead of before the package that must stay last
    rebuild: bool = True
    after_last: bool = False
    overhaul: bool = False
    preview: dict | None = None  # {"lines", "notes", "refusals"} of the overhaul install, once worked out
    planned: tuple = ()  # (name, id, variant) the plan is for
    previewed: tuple = ()  # (mode, name, variant) the preview is for
    setup_edited: bool = False  # the player changed the DLL options, Files table or text tables: sent as the setup
    gen: int = 0  # counts the edits that ask for a new plan: a heavy read answers only for the one it started with
    texts: list[dict] = field(default_factory=list)  # the setup's texts entries: file, table, tables to choose from
    files: list[dict] = field(default_factory=list)  # the setup's Files table (services.mod_configs.file_rows)
    natives: list[dict] = field(default_factory=list)  # the setup's DLLs as set (Basic natives), shown for review
    busy: bool = False  # a replan or preview is running
    problem: str = ""  # why the last edit could not be planned (the last good plan stays)
    library_choice: str = ""  # here | everywhere (a new version of a Shared mod); separate | share (identical copies)

    def __post_init__(self) -> None:
        self.name_text = self.plan["name"]
        self.id_text = self.plan.get("id") or self.plan["name"]
        self.variant = self.plan.get("variant") or None
        self.reset_ticks()
        self.overhaul = self.option == "suggested" or self.option == "matched"
        self.library_choice = "here" if self._library().get("shared") else "separate"
        self.planned = self.key()

    def _library(self) -> dict:
        return self.plan.get("library") or {}

    def _blocked(self) -> str:
        """Why a new version of a Shared mod can't be installed here ("" when it can)."""
        found = self._library()
        if not found.get("blocked"):
            return ""
        return tr(
            "{name} is Shared and this version has its own parameters (regulation.bin), which need a rebuild that "
            "updating a Shared mod does not run. Use a separate copy of it first, then install."
        ).format(name=found["shared"]["name"])

    def _library_view(self) -> dict:
        found = self._library()
        if found.get("blocked"):
            return {"shown": False}
        if found.get("shared"):
            info = found["shared"]
            text = (
                tr(
                    "{name} is Shared by {n} profiles. Update here gives this profile the new version and the others keep theirs."
                )
                if info["profiles"] > 1
                else tr("{name} is Shared. The new version is added to its shared files.")
            ).format(name=info["name"], n=info["profiles"])
            options = [{"key": "here", "text": tr("Update here")}]
            if info["profiles"] > 1:
                options.append({"key": "everywhere", "text": tr("Update everywhere")})
        elif found.get("identical"):
            text = tr(
                "The same files are in {names}. Share keeps one copy for all of them; their copies go to the Recycle Bin."
            ).format(names=", ".join(found["identical"]))
            options = [{"key": "separate", "text": tr("Keep separate")}, {"key": "share", "text": tr("Share")}]
        else:
            return {"shown": False}
        if self.library_choice not in {o["key"] for o in options}:
            self.library_choice = options[0]["key"]
        return {"shown": True, "text": text, "options": options, "choice": self.library_choice}

    # ---- edits
    def key(self) -> tuple:
        return (self.name_text.strip(), self.id_text.strip(), self.variant or None)

    def asked(self) -> None:
        """An edit that needs the engine's replan or preview: Install waits for them."""
        self.busy = True
        self.gen += 1

    def reset_ticks(self) -> None:
        items = [] if self.plan.get("in_place") else self.plan.get("contents") or []
        self.ticks = {it["name"]: bool(it["on"]) for it in items}

    def set_name(self, text: str) -> None:
        self.name_text = text
        if self.id_follows:
            self.id_text = text

    def set_id(self, text: str) -> None:
        self.id_text, self.id_follows = text, False

    def set_after_last(self, on: bool) -> None:
        self.after_last = on
        if self._target():
            self.place_last = on  # regulation.bin follows: before it, or last (its file replaces the merge)

    def new_plan(self, plan: dict, *, variant_changed: bool = False) -> None:
        self.plan = plan
        self.planned = self.key()
        if variant_changed:
            self.reset_ticks()
            self.setup_edited, self.natives, self.files, self.texts = False, [], [], []  # another download's rows

    # ---- the setup's form (an overhaul's DLL options, Files table and text tables)
    def set_native(self, file: str, kind: str, value: str) -> bool:
        """A DLL option (kind early | after | init); False when no row has that file."""
        row = next((n for n in self.natives if n["file"] == file), None)
        if row is None:
            return False
        row.update({"early": {"load_early": value == "true"}, "after": {"after_others": value == "true"},
                    "init": {"initializer": value.strip() or None}}[kind])  # fmt: skip
        return self._setup_changed()

    def set_table(self, file: str, table: str) -> bool:
        row = next((t for t in self.texts if t["file"] == file), None)
        if row is None:
            return False
        row["table"] = table
        return self._setup_changed()

    def set_file(self, file: str, value: str) -> bool:
        """A choice of the Files table (an action, or place:<game path>)."""
        row = next((r for r in self.files if r["file"] == file), None)
        if row is None:
            return False
        action, target = basic.decode_action(value)
        row["action"], row["target"] = action, target or (row["target"] if action == "place" else "")
        return self._setup_changed()

    def _setup_changed(self) -> bool:
        self.previewed, self.setup_edited = (), True
        return True

    def setup_values(self) -> SetupValues | None:
        """The form as the engine takes it; None while the player has not changed it (the engine uses its own)."""
        if not self.setup_edited:
            return None
        return SetupValues(
            [dict(n) for n in self.natives],
            {r["file"]: basic.encode_action(r["action"], r["target"]) for r in self.files},
            {t["file"]: t["table"] for t in self.texts},
        )

    # ---- the engine's answers
    def needs_preview(self) -> bool:
        mode = self.overhaul_mode
        return bool(mode) and (mode, self.name_text.strip(), self.variant or None) != self.previewed

    def apply_preview(self, pv: OverhaulPreview, mode: str, key: tuple) -> None:
        """The engine's overhaul preview for the mode and key (name, id, variant) it was asked for."""
        refusals = list(pv.refusals)
        if pv.editable:  # a verified config has no form: the rows stay as they were
            self.natives, self.files = [dict(n) for n in pv.natives], [dict(r) for r in pv.files]
            self.texts = [dict(t) for t in pv.texts]
        if any(not t["table"] for t in self.texts):  # said once per file below, not by the engine too
            refusals = [r for r in refusals if not r.startswith("Choose the table of ")]
        for t in self.texts:
            if not t["table"]:
                refusals.append(
                    tr("Choose the table for the texts added to {file} before installing.").format(
                        file=shown_path(t["file"])
                    )
                )
        self.preview = {"lines": list(pv.lines), "notes": list(pv.notes), "refusals": refusals}
        self.previewed = (mode, key[0], key[2])

    # ---- the overhaul option
    @property
    def option(self) -> str:
        """plain | suggested | matched | refused, from what the download is."""
        found = self.plan.get("overhaul")
        if found and found.get("refusal"):
            return "refused"
        if found:
            return "matched"
        return "suggested" if self.plan.get("overhaul_hint") else "plain"

    @property
    def overhaul_mode(self) -> str:
        """ "" (an ordinary install), "matched" (a config already describes it) or "setup" (ticked: set it up)."""
        if not (self.overhaul_on and self.overhaul) or self.option == "refused":
            return ""
        return "matched" if self.option == "matched" else "setup"

    def _option_view(self) -> dict:
        found, hint = self.plan.get("overhaul") or {}, self.plan.get("overhaul_hint") or {}
        state, text, level = self.option, "", "muted"
        if not self.overhaul_on:
            offered = state != "plain"
            return {
                "shown": False,
                "hint": tr(
                    'This looks like an overhaul. Turn on "Install overhauls with the launcher (preview)" in '
                    "Settings to set it up as one; until then it installs as an ordinary mod."
                )
                if offered and state != "refused"
                else "",
            }
        if state == "plain":
            text = tr("For mods that replace large parts of the game. Off for ordinary mods.")
        elif state == "suggested":
            reasons = {
                "installer": tr("it ships its own installer ({file})"),
                "profile": tr("it ships an me3 profile ({file})"),
                "regulation_with_dlls": tr("it has a regulation.bin together with DLLs"),
            }
            why = reasons.get(hint.get("reason", ""), tr("it looks like one")).format(file=hint.get("file", ""))
            text = tr("Ticked because {why}. Untick to install it as an ordinary mod.").format(why=why)
        elif state == "matched":
            label = found.get("label", "")
            version = f" {found['version']}" if found.get("version") else ""
            text = tr("Already set up: the {label}{version} config matches. Change it on Mod Configs.").format(
                label=label, version=version
            )
        else:
            text, level = found.get("refusal", ""), "error"
        return {
            "shown": True,
            "state": state,
            "ticked": self.overhaul and state != "refused",
            "locked": state in ("matched", "refused"),
            "text": text,
            "level": level,
            "badge": (tr("verified") if found.get("verified") else tr("your config, not verified"))
            if state == "matched"
            else "",
            "badgeLevel": "success" if found.get("verified") else "warning",
        }

    # ---- regulation.bin
    def _regulation_on(self) -> bool:
        return bool(self.plan.get("kind") == "package" and self.ticks.get("regulation.bin"))

    def _target(self) -> str | None:
        others = self.plan.get("regulation_packages") or []
        return self.plan.get("merge_target") or (others[-1]["name"] if others else None)

    def _insert_before(self) -> str | None:
        return None if self.place_last else self._target()

    def _rebuild_shown(self) -> bool:
        """Offered when regulation.bin is ticked and there is something to do after the install: combining this pack
        with the other packs' parameters, and/or the overlay's rebuild tool (which needs the pack before it)."""
        p = self.plan
        if not (p.get("merge_offered") and self._regulation_on()):
            return False
        before = p.get("already_listed") or self._insert_before() is not None
        return bool(p.get("merge_combine") or before)

    def _rebuild_text(self) -> str:
        p = self.plan
        if p.get("merge_combine") and p.get("merge_tool"):
            return tr("Combine parameters and rebuild after install")
        if p.get("merge_combine"):
            return tr("Combine parameters with the other packs after install")
        return tr("Rebuild combined parameters after install")

    def _reg_view(self) -> dict:
        p = self.plan
        on = self._regulation_on()
        others = p.get("regulation_packages") or []
        placed = not p.get("already_listed")  # a reinstall keeps its entry where it is
        target = self._target()
        shown_rebuild = self._rebuild_shown()
        notes = p.get("merge_notes") or []
        out = {
            "shown": on,
            "about": "",
            "effect": "",
            "effectLevel": "muted",
            "places": [],
            "placeIndex": 1 if self.place_last or not target else 0,
            "placeShown": on and bool(others) and placed and not p.get("stay_last"),
            "rebuildShown": shown_rebuild,
            "rebuildText": self._rebuild_text(),
            "rebuild": self.rebuild,
            "notes": "\n".join(notes) if shown_rebuild and self.rebuild else "",
        }
        if target:
            out["places"].append(tr("Before {name}, the package that must stay last").format(name=target))
        out["places"].append(tr("Last: this mod's regulation.bin is used"))
        if not on:
            return out
        if not others:
            out["about"] = tr(
                "It replaces the game's parameters (weapons, enemies, items...). No other package here has one, so "
                "this mod's is used."
            )
            return out
        winner = others[-1]["name"]
        out["about"] = tr(
            "It replaces the game's parameters as one whole file, and me3 uses only the last one in the load order. "
            "{winner}'s is used now."
        ).format(winner=winner)
        combining = shown_rebuild and self.rebuild and p.get("merge_combine")
        if combining:
            text = tr(
                "Its parameters are combined with the other packs' into one file, so all of them apply; they apply "
                "once the combine succeeds."
            )
            if p.get("merge_tool"):
                text += " " + tr("Placed before {name}, whose rebuild tool then takes the combined file.").format(
                    name=target or winner
                )
            out["effect"] = text
        elif placed and self._insert_before() is None:
            out["effect"], out["effectLevel"] = (
                tr(
                    "{winner}'s parameters will not apply: this pack's regulation.bin replaces them, which usually "
                    "breaks {winner} unless this pack was made for it."
                ).format(winner=winner),
                "warning",
            )
        elif shown_rebuild and self.rebuild:
            out["effect"] = tr(
                "{winner} keeps working, and the rebuild folds this pack's parameters into the package that must "
                "stay last. They apply only once the rebuild succeeds; a pack whose in-game options start hidden "
                "shows nothing until then."
            ).format(winner=winner)
        else:
            how = (
                tr("Tick {what} to fold them in.").format(what=self._rebuild_text().split(" after")[0])
                if p.get("merge_offered")
                else tr(
                    "They would need merging into {winner}'s. Untick regulation.bin above to leave the file out."
                ).format(winner=winner)
            )
            out["effect"], out["effectLevel"] = (
                tr("This pack's parameters will not apply: {winner}'s regulation.bin is used. {how}").format(
                    winner=winner, how=how
                ),
                "warning",
            )
        return out

    def _last_view(self) -> dict:
        last = self.plan.get("stay_last")
        if not last or self.overhaul_mode:
            return {"shown": False}
        if self.after_last:
            text, level = (
                tr(
                    "Loads after {last}, the mod that must stay last: where both ship a file, this mod's copy is "
                    "used and {last}'s merged one is not. Only for a mod made to go on top of it."
                ).format(last=last),
                "warning",
            )
        else:
            text, level = (
                tr("Placed before {last}, the mod that must stay last, so {last} includes its changes.").format(
                    last=last
                ),
                "muted",
            )
        return {
            "shown": True,
            "text": text,
            "level": level,
            "check": tr("Advanced: load after {last} instead (replaces its files)").format(last=last),
            "on": self.after_last,
        }

    # ---- the whole dialog
    def _what(self) -> str:
        p = self.plan
        size = _size(p["size"])
        if p["kind"] == "package":
            what = tr("Package") + f"  ·  {', '.join(p['assets'])}  ·  {size}"
            if p.get("languages"):
                langs = ", ".join(LANGUAGES.get(x.lower(), x) for x in p["languages"])
                what += "\n" + tr("Text in {langs}; other languages keep the game's own text.").format(langs=langs)
            return what
        return tr("DLL mod") + f"  ·  {', '.join(Path(d).name for d in p['dlls'])}  ·  {size}"

    def _note(self, mode: str) -> tuple[str, str]:
        p = self.plan
        if self.problem:
            return self.problem, "error"
        if p.get("name_problem") and not mode:
            return p["name_problem"], "error"
        if self._blocked() and not mode:
            return self._blocked(), "error"
        if mode:
            return tr("Set up as an overhaul: it loads last, and Undo takes it back."), "muted"
        lines = []
        if p.get("in_place"):
            lines.append(tr("The files are already there; only the profile changes."))
        elif p.get("exists"):
            lines.append(
                tr("A folder named {name} is already there and is replaced.").format(name=Path(p["dest"]).name)
            )
        if p.get("used_by") and not p.get("in_place"):
            lines.append(
                tr("{names} also use it, so updating changes it for them too.").format(names=", ".join(p["used_by"]))
            )
        if p.get("already_listed"):
            lines.append(tr("It is already in the profile, so no new entry is added."))
        else:
            lines.append(tr("Options changes its load order, and anything else, once it is in."))
        return " ".join(lines), "error" if p.get("exists") and not p.get("in_place") else "muted"

    def can_install(self) -> bool:
        p = self.plan
        if self.busy or self.problem or p.get("error") or not self.name_text.strip():
            return False
        mode = self.overhaul_mode
        if mode:
            return bool(self.preview) and not self.preview.get("refusals")
        if self.option == "refused" and self.overhaul_on:
            return False
        if p.get("name_problem") or self._blocked():
            return False
        if p["kind"] == "package" and (not self.id_text.strip() or p.get("id_taken")):
            return False
        if self.ticks:  # something the game loads must be ticked
            groups = {i["name"]: i["group"] for i in p.get("contents") or []}
            return any(on and groups.get(n, "") in LOADED for n, on in self.ticks.items())
        return True

    def view(self) -> dict:
        p = self.plan
        package = p["kind"] == "package"
        mode = self.overhaul_mode
        try:
            where = str(Path(p["dest"]).relative_to(self.profile.parent))
        except KeyError, ValueError, TypeError:
            where = str(p.get("dest") or "")
        groups = group_text()
        items = []
        for it in [] if (mode or p.get("in_place") or self._library().get("shared")) else p.get("contents") or []:
            what = groups.get(it["group"], it["group"])
            if it.get("extra") and it["group"] == "other":
                what = tr("beside the mod's folder, not part of it")
            tip = (
                tr("{where}: ticked, it is copied into the mod's folder.").format(where=it["extra"])
                if it.get("extra")
                else ""
            )
            items.append(
                {
                    "name": it["name"],
                    "what": what,
                    "size": _size(it["size"]),
                    "on": self.ticks.get(it["name"], False),
                    "tip": tip,
                }
            )
        note, note_level = self._note(mode)
        id_taken = package and p.get("id_taken")
        return {
            "title": tr("Install {name}").format(name=self.name_text.strip() or p["name"]),
            "what": self._what(),
            "variants": p.get("variants") or [],
            "variant": self.variant or "",
            "name": self.name_text,
            "id": self.id_text,
            "nameLabel": tr("Name") if mode == "setup" else tr("Folder name"),
            "where": "" if mode else tr("Goes into this profile's folder: {where}").format(where=where),
            "idShown": package and not mode,
            "idNote": tr("'{id}' is already used by another package; me3 needs each id once.").format(id=p.get("id"))
            if id_taken
            else tr("What other entries use to load before or after it."),
            "idError": bool(id_taken),
            "nameError": bool(p.get("name_problem")) and not mode,
            "items": items,
            "regulation": {"shown": False} if mode else self._reg_view(),
            "last": self._last_view(),
            "note": note,
            "noteLevel": note_level,
            "option": self._option_view(),
            "library": {"shown": False} if mode else self._library_view(),
            "overhaul": self._overhaul_preview(mode),
            "natives": self.natives if mode else [],
            "files": [self._file_view(r) for r in self.files] if mode else [],
            "texts": [self._text_view(t) for t in self.texts] if mode else [],
            "mode": mode,
            "profilesInside": bool(p.get("profiles_inside")),  # the download ships .me3 profiles: Import can take them
            "canInstall": self.can_install(),
            "busy": self.busy,
            "installText": tr("Install as overhaul") if mode else tr("Install"),
            "error": p.get("error") or "",
        }

    @staticmethod
    def _text_view(t: dict) -> dict:
        choices = [{"value": n, "label": n} for n in t["tables"]]
        if not t["table"]:
            choices.insert(0, {"value": "", "label": tr("(choose a table)")})
        return {
            "file": t["file"],
            "label": tr("Texts added to {file}").format(file=shown_path(t["file"])),
            "table": t["table"],
            "choices": choices,
            "chosen": next((c["label"] for c in choices if c["value"] == t["table"]), t["table"]),
        }

    @staticmethod
    def _file_view(r: dict) -> dict:
        return {
            "file": r["file"],
            "action": r["action"],
            "target": r["target"],
            "choices": [{"value": c, "label": file_action_text(r["kind"], c)} for c in r["choices"]],
        }

    def _overhaul_preview(self, mode: str) -> dict:
        pv = self.preview
        if not mode:
            return {"shown": False}
        if pv is None:
            return {"shown": True, "ready": False, "lines": [], "notes": [], "refusals": []}
        return {"shown": True, "ready": True, **pv}

    # ---- when Install is pressed
    def choices(self) -> InstallChoices:
        """What the player set, for the engine to install with."""
        return InstallChoices(
            name=self.name_text,
            id=self.id_text,
            variant=self.variant,
            exclude=tuple(n for n, on in self.ticks.items() if not on),
            place_last=self.place_last,
            rebuild=self.rebuild,
            after_last=self.after_last,
            library_choice=self.library_choice,
            overhaul=self.overhaul,
            setup=self.setup_values() if self.overhaul_mode else None,
        )
