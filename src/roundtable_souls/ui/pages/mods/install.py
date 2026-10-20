"""The Install mod dialog's words and state (technical specification §8.2 and "Dialogs kept"). Plain Python, every
string through tr(): an InstallDraft holds a plan (mods.install.plan_install) and what the player has changed in
it, and view() turns both into what the QML dialog shows. The wording is the Widgets dialog's
(ui/dialogs/install.py), moved; the overhaul option is S3g's, in its five states."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from roundtable_souls.ui.text import tr


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
        "overhaulName": tr("Name"),
        "id": tr("Id"),
        "whatToInstall": tr("What to install"),
        "itemsNote": tr("Unticked files are left out. Tick one to keep it with the mod anyway."),
        "regulation": tr("regulation.bin"),
        "placeBefore": tr("Before the package that must stay last"),
        "placeLast": tr("Last: this mod's regulation.bin is used"),
        "install": tr("Install"),
        "installOverhaul": tr("Install as overhaul"),
        "cancel": tr("Cancel"),
        "working": tr("Working..."),
        "overhaulOption": tr("Set up as an overhaul (loads last, merged with the mods before it)"),
        "verified": tr("verified"),
        "yourConfig": tr("your config, not verified"),
    }


@dataclass
class InstallDraft:
    """plan: a plan_mod_install result; profile: the profile it installs into. overhaul_on: the Settings switch
    "Install overhauls with the launcher (preview)" is on, which is when the overhaul option is offered."""

    plan: dict
    profile: Path
    overhaul_on: bool = False
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
    busy: bool = False  # a replan or preview is running

    def __post_init__(self) -> None:
        self.name_text = self.plan["name"]
        self.id_text = self.plan.get("id") or self.plan["name"]
        self.variant = self.plan.get("variant") or None
        self.reset_ticks()
        self.overhaul = self.option == "suggested" or self.option == "matched"

    # ---- edits
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
        if variant_changed:
            self.reset_ticks()

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
        return tr("DLL mod") + f"  ·  {', '.join(d.name for d in p['dlls'])}  ·  {size}"

    def _note(self, mode: str) -> tuple[str, str]:
        p = self.plan
        if p.get("name_problem") and not mode:
            return p["name_problem"], "error"
        if mode:
            return tr("Set up as an overhaul: it loads last, and Undo takes it back."), "muted"
        lines = []
        if p.get("in_place"):
            lines.append(tr("The files are already there; only the profile changes."))
        elif p.get("exists"):
            lines.append(
                tr("A folder named {name} is already there and is replaced.").format(name=Path(p["dest"]).name)
            )
        if p.get("already_listed"):
            lines.append(tr("It is already in the profile, so no new entry is added."))
        else:
            lines.append(tr("Options changes its load order, and anything else, once it is in."))
        return " ".join(lines), "error" if p.get("exists") and not p.get("in_place") else "muted"

    def can_install(self) -> bool:
        p = self.plan
        if self.busy or p.get("error") or not self.name_text.strip():
            return False
        mode = self.overhaul_mode
        if mode:
            return bool(self.preview) and not self.preview.get("refusals")
        if self.option == "refused" and self.overhaul_on:
            return False
        if p.get("name_problem"):
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
        for it in [] if (mode or p.get("in_place")) else p.get("contents") or []:
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
            "where": "" if mode else tr("Goes into {where}").format(where=where),
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
            "overhaul": self._overhaul_preview(mode),
            "mode": mode,
            "canInstall": self.can_install(),
            "busy": self.busy,
            "installText": tr("Install as overhaul") if mode else tr("Install"),
            "error": p.get("error") or "",
        }

    def _overhaul_preview(self, mode: str) -> dict:
        pv = self.preview
        if not mode:
            return {"shown": False}
        if pv is None:
            return {"shown": True, "ready": False, "lines": [], "notes": [], "refusals": []}
        return {"shown": True, "ready": True, **pv}

    # ---- when Install is pressed
    def finish(self) -> dict:
        """The plan to install, with 'exclude' (names left out), 'merge', 'insert_before' and 'after_overlay' set."""
        p = dict(self.plan)
        p["exclude"] = [n for n, on in self.ticks.items() if not on]
        p["merge"] = self._rebuild_shown() and self.rebuild
        placed = self._regulation_on() and not p.get("already_listed")
        p["insert_before"] = self._insert_before() if placed else None  # a package name
        p["after_overlay"] = bool(p.get("stay_last")) and self.after_last
        return p
