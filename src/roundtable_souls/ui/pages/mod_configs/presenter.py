"""The Mod Configs page's presenter (technical specification §8.10, Mod Configs): the tree of mods with settings
files, the breadcrumb, the generated form's rows, the Seamless Co-op panel, and every word the page shows. Plain
Python, every string through tr(); it turns services/mod_configs.py's facts into what the page shows.

The Seamless Co-op words (each setting's name, one-line summary and explanation, the choice names, the section
titles) live here, not in coop/ (spec table, S7): the Widgets Co-op page uses them from here until it goes (S9)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roundtable_souls.formats import config_model
from roundtable_souls.services import mod_configs
from roundtable_souls.ui.file_actions import file_action_text
from roundtable_souls.ui.pages.mods.presenter import Confirm, Pick, Refusal
from roundtable_souls.ui.text import plural, tr

# ----------------------------------------------------------------------------- Seamless Co-op's words
SETTING_COPY = {
    "allow_invaders": {
        "label": "Invaders",
        "blurb": "Uninvited players can join and fight you.",
        "help": "When this is on, other players can invade your session and try to kill you and your party. Turn it off if you only want people you invited.",
    },
    "death_debuffs": {
        "label": "Death debuffs",
        "blurb": "Rot Essence after you die, until you rest.",
        "help": "When this is on, dying gives you Rot Essence. It lasts until you sit at a Site of Grace.",
    },
    "allow_summons": {
        "label": "Spirit summons",
        "blurb": "Ashes can help in multiplayer.",
        "help": "When this is on, spirit ashes work in a Seamless session the way they do when you play alone.",
    },
    "overhead_player_display": {
        "label": "Nameplates",
        "blurb": "What sits over other players.",
        "help": "Choose what appears over other players. Hidden removes the nameplate. Ping, level, and deaths help you tell people apart.",
        "choices": {0: "Name", 1: "Hidden", 2: "Ping", 3: "Level", 4: "Deaths", 5: "Level and ping"},
    },
    "skip_splash_screens": {
        "label": "Skip intro logos",
        "blurb": "Go straight to the menu when the game starts.",
        "help": "When this is on, the publisher and studio logos are skipped on boot.",
    },
    "append_steam_id_to_players": {
        "label": "Steam ID on nameplates",
        "blurb": "Show each player's Steam ID next to their name.",
        "help": "Adds the player's Steam ID to their nameplate. Useful if you need to report or block someone.",
        "choices": {0: "Off", 1: "On"},
    },
    "always_spectate_on_death": {
        "label": "Spectate after death",
        "blurb": "What you watch after you die.",
        "help": "Bosses and invasions keeps the usual Seamless camera. Until you rest keeps you watching teammates until the party wipes or someone sits at a grace.",
        "choices": {0: "Bosses and invasions", 1: "Until you rest"},
    },
    "default_boot_master_volume": {
        "label": "Menu volume",
        "blurb": "How loud the title screen is, before a save loads.",
        "help": "This is only the volume on the title screen. In-game volume is still set in the game's own options.",
    },
    "save_file_extension": {
        "label": "Save file",
        "blurb": "Which save Seamless writes.",
        "help": "Co-op uses a separate file from the standard game save, so they do not overwrite each other. Change this only if you know you need a different file. Letters and numbers only.",
    },
    "mod_language_override": {
        "label": "Language",
        "blurb": "Seamless Co-op's own text: the game's language, or a translation in its locale folder.",
        "help": "Game language uses the game's current language. The others are the translation files in Seamless Co-op's locale folder.",
    },
}
SECTION_TITLES = {
    "GAMEPLAY": "Gameplay",
    "SCALING": "Difficulty scaling",
    "PASSWORD": "Password",
    "SAVE": "Save file",
    "LANGUAGE": "Language",
}
VOLUME_STOPS = ((0, "Mute"), (3, "Quiet"), (5, "Medium"), (8, "Loud"), (10, "Max"))
SAVE_KINDS = (("co2", "Co-op"), ("sl2", "Standard"))


def volume_stops() -> tuple[tuple[int, str], ...]:
    return tuple((n, tr(label)) for n, label in VOLUME_STOPS)


def save_kinds() -> tuple[tuple[str, str], ...]:
    return tuple((ext, tr(label)) for ext, label in SAVE_KINDS)


def section_title(name: str) -> str:
    return tr(SECTION_TITLES[name.upper()]) if name.upper() in SECTION_TITLES else name.title()


def label_of(key: str) -> str:
    copy = SETTING_COPY.get(key)
    if copy:
        return tr(copy["label"])
    return key.replace("_", " ").strip().capitalize()


def setting_face(key: str, desc: str = ""):
    """(label, short blurb, help). Ini numbers stay out of the window."""
    copy = SETTING_COPY.get(key) or {}
    return (
        tr(copy["label"]) if copy.get("label") else label_of(key),
        tr(copy["blurb"]) if copy.get("blurb") else "",
        tr(copy["help"]) if copy.get("help") else _human_ini_comment(desc),
    )


def _human_ini_comment(desc: str) -> str:
    if not desc:
        return ""
    d = re.sub(r"\s*\d+\s*=\s*FALSE\s+\d+\s*=\s*TRUE", "", desc, flags=re.I)
    d = re.sub(r"\s*\d+\s*=\s*MUTE\s+\d+\s*=\s*MAX", "", d, flags=re.I)
    if "|" in d or re.search(r"\d+\s*=", d):
        d = re.split(r"\s*\d+\s*=", d, maxsplit=1)[0]
    d = re.sub(r"\s+", " ", d).strip(" .")
    return d + ("." if d else "")


def choice_label(key: str, n: int, raw: str) -> str:
    mapped = (SETTING_COPY.get(key) or {}).get("choices", {}).get(n)
    if mapped:
        return tr(mapped)
    t = (raw or "").strip().rstrip(".")
    t = re.sub(r"(?i)^display player ", "", t)
    low = t.lower()
    if low.startswith("will add the player's unique steam"):
        return tr("On")
    if low.startswith("spectate only"):
        return tr("Bosses and invasions")
    if low.startswith("always spectate"):
        return tr("Until you rest")
    if low == "no change":
        return tr("Off")
    if low == "soul level and ping":
        return tr("Level and ping")
    if low == "normal":
        return tr("Name")
    if low == "none":
        return tr("Hidden")
    t = re.sub(r"(?i)soul level", "Level", t)
    t = re.sub(r"(?i)death count", "Deaths", t)
    return t[:1].upper() + t[1:] if t else t


# ----------------------------------------------------------------------------- the page
def nested_title(path: str) -> str:
    """A TOML section path in player words: "window.deep" -> "Window › Deep", "[[builds]] #1" -> "Builds · 1"."""
    m = re.fullmatch(r"\[\[(.+?)\]\]\s*#(\d+)", path.strip())
    if m:
        return f"{_nice(m.group(1))} · {m.group(2)}"
    return " › ".join(_nice(p) for p in path.split(".")) if "." in path else path


def _nice(part: str) -> str:
    return part.strip().replace("_", " ").capitalize()


class ModConfigsPresenter:
    """Pure: everything the page shows comes from the arguments."""

    open_window_text = property(lambda self: tr("Open new Mod Configs window"))
    open_window_tip = property(lambda self: tr("A preview of the new Mod Configs page, in its own window."))

    def words(self) -> dict[str, str]:
        return {
            "title": tr("Mod Configs"),
            "noProfile": tr("Pick a profile first."),
            "noMods": tr("No mod in this profile has a settings file."),
            "pickFile": tr("Pick a file to edit it."),
            "editAsText": tr("Edit as text"),
            "save": tr("Save"),
            "discard": tr("Discard"),
            "resetAll": tr("Reset all"),
            "reset": tr("Reset to default"),
            "resetDisk": tr("Reset to the file's value"),
            "changed": tr("Changed"),
            "diskChanged": tr(
                "This file changed outside the launcher. Reload to see its current settings. Unsaved edits are dropped."
            ),
            "reload": tr("Reload"),
            "noMatch": tr("No setting matches"),
            "matchCount": tr("{n} settings match"),
            "noChanges": tr("No changes"),
            "findSetting": tr("Find a setting"),
            "emptyPickTitle": tr("Pick a file to edit"),
            "emptyPickBody": tr("Its settings show here as a form."),
            "emptyNoFilesTitle": tr("No settings files yet"),
            "emptyNoFilesBody": tr("Attach a settings file to a DLL mod on the Mods page and it shows here."),
            "goToMods": tr("Go to Mods"),
            "back": tr("Back"),
            "cancel": tr("Cancel"),
            "on": tr("On"),
            "off": tr("Off"),
            "readonly": tr("Only Edit as text can change this one"),
            "unsavedTitle": tr("Unsaved changes"),
            "unsavedBody": tr("This file has changes that are not saved. Save them, or discard them?"),
            "noForm": tr("This file can't be shown as settings, so it is open here to edit directly."),
            "attach": tr("Attach a file..."),
            "detach": tr("Detach"),
            "password": tr("Password"),
            "showPassword": tr("Show"),
            "hidePassword": tr("Hide"),
            "passwordHint": tr("Friends type the same password to join your session."),
            "difficulty": tr("Difficulty"),
            "preset": tr("Party size"),
            "language": tr("Language"),
            "gameLanguage": tr("Game language"),
            "otherSettings": tr("Other settings"),
            "share": tr("Share with a friend"),
            "shareBody": tr(
                "Copy settings puts every setting, the password too, on the clipboard as text. Paste settings shows "
                "what a friend's text would change before anything is written."
            ),
            "copy": tr("Copy settings"),
            "paste": tr("Paste settings"),
            "load": tr("Load settings..."),
            "saveAs": tr("Save settings..."),
            "more": tr("More"),
            "disabled": tr("Disabled"),
            "setUpOverhaul": tr("Set up as an overhaul..."),
            "turnOffOverhaul": tr("Turn off overhaul setup..."),
            "setUpModLink": tr("Set up a mod as an overhaul..."),
        }

    # ---- the tree
    def node(self, node: mod_configs.ModNode) -> dict[str, Any]:
        """One mod: its name, the line under it, whether it is muted, and its files."""
        if node.kind == mod_configs.SEAMLESS:
            name = tr("Seamless Co-op")
            sub = "" if node.loaded else tr("Install Seamless Co-op to use these settings")
            tip = tr("Still editable here.") if node.loaded and not node.enabled else ""
        else:
            name = node.name
            sub, tip = "", ""
        return {
            "key": node.key,
            "kind": node.kind,
            "name": name,
            "sub": sub,
            "disabled": node.loaded and not node.enabled,  # shown as the Disabled tag beside the name
            "disabledTip": tip,
            "muted": not node.loaded or not node.enabled,
            "action": self.overhaul_action(node),
            "files": [
                {"path": str(f.path), "name": f.path.name, "kind": f.kind, "attached": f.how == "attached"}
                for f in node.files
            ],
        }

    def overhaul_node(self, node: mod_configs.ModNode) -> dict[str, Any]:
        """The tree's entry for the overhaul setup: its label, and whether the launcher verified it."""
        setup = node.setup or {}
        return {
            "key": node.key,
            "kind": node.kind,
            "muted": False,
            "disabled": False,
            "disabledTip": "",
            "action": self.overhaul_action(node),
            "name": tr("Overhaul setup") + ": " + node.name,
            "sub": self.overhaul_status(bool(setup.get("verified"))),
            "files": [
                {
                    "path": str(f.path),
                    "name": tr("Setup") if f.how == "overhaul" else f.path.name,
                    "kind": f.kind,
                    "attached": False,
                }
                for f in node.files
            ],
        }

    @staticmethod
    def overhaul_action(node: mod_configs.ModNode) -> str:
        """The one overhaul entry a mod's menu offers: setUp (a DLL or package), turnOff (its own setup, unless the
        launcher ships it verified), or none."""
        if node.kind in ("native", "package"):
            return "setUp"
        return "turnOff" if node.kind == mod_configs.OVERHAUL and not (node.setup or {}).get("verified") else ""

    @staticmethod
    def overhaul_status(verified: bool) -> str:
        return tr("verified") if verified else tr("your config, not verified")

    def overhaul_label(self, label: str, verified: bool) -> str:
        """How the overhaul is named wherever its state is said (this page, the Mods page's Parameters card)."""
        return f"{label} ({self.overhaul_status(verified)})"

    def overhaul(self, setup: dict, choices: dict, values: dict, steps: list[str], new: bool) -> dict[str, Any]:
        """The Overhaul setup form: setup is services.mods.overhaul_setup_of (or the proposal for a new one); values
        the working copy (natives, keep, off: the binders used whole). The basic level is generated rows (the page's
        ConfigForm); the advanced level and a verified setup are shown read-only."""
        config, verified = setup["config"], bool(setup.get("verified"))
        basic_level = setup["level"] == "basic" and config.basic is not None and not verified
        sections: list[dict] = []
        if basic_level:
            for n in values["natives"]:
                f = n["file"]
                rows = [
                    self._ov_row(
                        f,
                        "early:" + f,
                        tr("Start before the game sets itself up"),
                        "bool",
                        str(bool(n["load_early"])).lower(),
                    ),
                    self._ov_row(
                        f, "after:" + f, tr("Load after the other DLLs"), "bool", str(bool(n["after_others"])).lower()
                    ),
                    self._ov_row(
                        f, "init:" + f, tr("Run a function when it loads"), "text", n.get("initializer") or ""
                    ),
                ]
                sections.append({"title": Path(f).name, "rows": rows})
            if choices["files"]:
                sections.append(
                    {
                        "title": tr("Files"),
                        "rows": [
                            row for r in choices["files"] for row in self.file_rows(r, values["files"][r["file"]])
                        ],
                    }
                )
        if basic_level:
            sections.append(self.health_section(values.get("health") or {}))
        if verified:
            note = tr(
                "This profile comes with the launcher and is verified. Use Remove {label} on the Mods page to take it out."
            ).format(label=config.short_label)
        elif not basic_level:
            note = tr("This profile's steps were edited by hand. They are shown below; Edit as text changes them.")
        elif new:
            note = tr("Check the settings, then Save to set this mod up as an overhaul. You see what it does first.")
        else:
            note = ""
        return {
            "label": config.label,
            "status": self.overhaul_status(verified),
            "loadsLast": tr("Loads after all the other mods, whatever is set here."),
            "note": note,
            "sections": sections,
            "steps": steps if not basic_level else [],
            "stepsTitle": tr("What it does"),
            "isNew": new,
            "editable": not verified,
        }

    def health_section(self, form: dict[str, str]) -> dict[str, Any]:
        """Check a log after each run: where the mod writes it and the text that means it failed to start."""
        rows = [
            self._ov_row(
                "health", "health:log", tr("Log file (relative to the mod's folder)"), "text", form.get("log", "")
            ),
            self._ov_row("health", "health:fail", tr("Text that means it failed"), "text", form.get("fail", "")),
            self._ov_row(
                "health", "health:ok", tr("Text that means it started (optional)"), "text", form.get("ok", "")
            ),
        ]
        rows[1]["blurb"] = tr("Plain text; start with re: for a regular expression.")
        return {"title": tr("Check a log after each run"), "rows": rows}

    def file_rows(self, r: dict, action: str) -> list[dict[str, Any]]:
        """The Files table's rows for one file: its choice, and for a placed file the game path it goes to."""
        shown = "place" if action.startswith("place:") else action
        row = self._ov_row("file", "file:" + r["file"], r["file"], "choice", shown)
        row["choices"] = [{"value": c, "label": file_action_text(r["kind"], c)} for c in r["choices"]]
        row["blurb"] = tr("By itself: {what}").format(what=file_action_text(r["kind"], r["choices"][0]).lower())
        out = [row]
        if shown == "place":
            out.append(self._ov_row("file", "target:" + r["file"], tr("Game path"), "text", action[6:]))
        return out

    @staticmethod
    def _ov_row(section: str, key: str, label: str, kind: str, value: str) -> dict[str, Any]:
        return {
            "section": section,
            "key": key,
            "label": label,
            "blurb": "",
            "help": "",
            "kind": kind,
            "value": value,
            "choices": [],
            "lo": 0,
            "hi": 0,
            "tip": "",
            "onValue": "true",
            "offValue": "false",
        }

    def turn_off(self, preview) -> Confirm | Refusal:
        """The confirmation for overhaul_install.TurnOffPreview, or why it can't go ahead."""
        if not preview.ok:
            return Refusal(tr("Can't turn it off"), " ".join(preview.refusals))
        label = preview.remove.config.label
        return Confirm(
            title=tr("Turn off the overhaul setup of {label}").format(label=label),
            changes=tuple(preview.lines),
            apply=tr("Turn off"),
            safety=tr("Undo in Activity puts it all back."),
        )

    def install_setup(self, preview) -> Confirm | Refusal:
        """The confirmation for overhaul_install.InstallPreview of a new setup."""
        if not preview.ok:
            return Refusal(tr("Can't set it up"), " ".join(preview.refusals))
        return Confirm(
            title=tr("Set up {label} as an overhaul").format(label=preview.label),
            changes=(*preview.lines, *preview.notes),
            apply=tr("Set up"),
            safety=tr("If anything fails, nothing changes. Undo in Activity puts it back."),
        )

    def pick_overhaul_mod(self) -> Pick:
        return Pick(
            title=tr("Set up which mod as an overhaul?"),
            body=tr("An overhaul loads after all the other mods and can merge their files. Tick the mod to set up."),
            apply=tr("Next"),
            none="",
        )

    def crumb(self, mod_name: str, path: Path | None) -> str:
        return f"{mod_name} / {path.name}" if path else mod_name

    # ---- a file as a form
    def form(self, doc: config_model.Document, seamless: bool = False, skip: tuple[str, ...] = ()) -> list[dict]:
        """The sections and their rows; skip: sections another part of the page shows (Seamless's password and
        difficulty)."""
        out = []
        for s in doc.sections:
            if s.name.upper() in skip:
                continue
            rows = [self.row(item, seamless) for item in s.settings]
            if rows:
                out.append(
                    {
                        "title": section_title(s.name) if seamless else nested_title(s.name or ""),
                        "path": s.name or "",
                        "rows": rows,
                    }
                )
        return out

    def row(self, item: config_model.Setting, seamless: bool = False) -> dict[str, Any]:
        if seamless:
            label, blurb, help_text = setting_face(item.key, item.desc)
        else:
            label, blurb, help_text = item.key, "", _human_ini_comment(item.desc)
        kind = "readonly" if item.readonly else item.kind
        choices: list[dict] = []
        if kind == "choice":
            choices = [{"value": str(n), "label": choice_label(item.key, n, raw)} for n, raw in item.extra]
        if seamless and item.key == "default_boot_master_volume":
            kind, choices = "choice", [{"value": str(n), "label": lab} for n, lab in volume_stops()]
        if seamless and item.key == "save_file_extension" and item.value in {k for k, _ in SAVE_KINDS}:
            kind, choices = "choice", [{"value": k, "label": lab} for k, lab in save_kinds()]
        lo, hi = item.extra if kind in ("int",) and item.extra else (0, 0)
        return {
            "section": item.section,
            "key": item.key,
            "label": label,
            "blurb": blurb,
            "help": help_text,
            "kind": kind,
            "value": item.value.strip(),
            "choices": choices,
            "lo": lo,
            "hi": hi,
            "tip": tr("Default: {value}").format(value=item.default) if item.default is not None else "",
            # what a switch writes: TOML's true / false, an ini's 1 / 0
            "onValue": "true" if item.value.strip().lower() in ("true", "false") else "1",
            "offValue": "false" if item.value.strip().lower() in ("true", "false") else "0",
        }

    def reset_tip(self, source: str) -> str:
        return tr("Back to the default its comment gives") if source == "default" else tr("Back to the value on disk")

    # ---- Seamless Co-op
    def seamless(self, s: mod_configs.Seamless, fingerprint_line: str = "", fingerprint_note: str = "") -> dict:
        spec = s.spec
        return {
            "hasPassword": s.password is not None,
            "password": s.password or "",
            "presets": [tr(n) for n in (spec.presets if spec else {})] + [tr("Custom")],
            "presetKeys": [*(spec.presets if spec else {}), "Custom"],
            "preset": s.preset,
            "scaling": [
                {"key": k, "label": tr(lab), "value": v}
                for k, lab, v in zip(spec.keys, spec.labels, s.scaling or (), strict=False)
            ]
            if spec and s.scaling
            else [],
            "scalingHint": tr(spec.hint) if spec else "",
            "presetValues": {n: list(v) for n, v in (spec.presets if spec else {}).items()},
            "languages": [{"value": v, "label": v or tr("Game language")} for v in s.languages],
            "language": s.language,
            "fingerprint": fingerprint_line,
            "fingerprintNote": fingerprint_note,
        }

    # ---- confirmations, refusals and toasts
    def saved(self, n: int) -> str:
        return plural(
            "{n} setting saved. It applies the next time the game starts.",
            "{n} settings saved. They apply the next time the game starts.",
            n,
        ).format(n=n)

    def saved_text(self, name: str) -> str:
        return tr("{name} saved. It applies the next time the game starts.").format(name=name)

    def could_not_save(self, why: str) -> Refusal:
        return Refusal(tr("Not saved"), why)

    def missing_keys(self, name: str, keys: list[str]) -> Refusal:
        return Refusal(tr("Not saved"), tr("Not in {name}: {keys}").format(name=name, keys=", ".join(keys)))

    def empty_password(self) -> Refusal:
        return Refusal(tr("Password needed"), tr("The Seamless Co-op password cannot be empty."))

    def copied(self) -> str:
        return tr("Settings copied.")

    def not_settings(self, why: str) -> Refusal:
        return Refusal(
            tr("Not settings text"), tr("The text could not be read as co-op settings: {why}").format(why=why)
        )

    def nothing_to_change(self, unknown: list[str]) -> str:
        said = tr("Nothing to change: it matches your settings.")
        return said + (" " + tr("Ignored: {keys}").format(keys=", ".join(unknown)) if unknown else "")

    def paste(self, changes: dict[str, tuple[str, str]], unknown: list[str]) -> Confirm:
        n = len(changes)
        return Confirm(
            title=plural("Apply {n} setting from your friend", "Apply {n} settings from your friend", n).format(n=n),
            changes=tuple(f"{label_of(k)}:  {old}  →  {new}" for k, (old, new) in changes.items()),
            apply=tr("Apply"),
            detail=tr("Ignored (not in your file): {keys}").format(keys=", ".join(unknown)) if unknown else "",
            safety=tr("They apply the next time the game starts. A backup of the file is kept."),
        )

    def unreadable(self, name: str, why: str) -> Refusal:
        return Refusal(tr("Can't open {name}").format(name=name), why)
