"""The Mod Configs page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). What to
show comes from the presenter, what a change does from services/mod_configs.py. The tree is read on the host's
worker; one file is read when it is picked (settings files are small). Edits wait in `pending` until Save, which
writes only those values (refused when the file changed on disk since it was read)."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from roundtable_souls.coop import scaling as coop_scaling
from roundtable_souls.formats import config_model
from roundtable_souls.services import mod_configs
from roundtable_souls.services import mods as mod_service
from roundtable_souls.ui.models import plain
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.mod_configs.presenter import ModConfigsPresenter
from roundtable_souls.ui.pages.mods.presenter import Confirm, ModsPresenter, Pick, Refusal
from roundtable_souls.ui.refresh import Refresher
from roundtable_souls.ui.text import plural, tr

SEAMLESS_OWN = ("PASSWORD", "SCALING", "LANGUAGE")  # sections the Seamless panel shows itself


def _stamp(path: Path) -> tuple[int, int] | None:
    """Modification time and size: what tells that a file changed under the page."""
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


class ModConfigsHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell, S9)."""

    @property
    def busy(self) -> bool: ...
    @property
    def locations(self) -> Any: ...
    @property
    def profile(self) -> Path | None: ...
    @property
    def settings(self) -> Any: ...
    def run_in_background(self, work, on_result) -> None: ...
    def show_page(self, name: str) -> Any: ...
    def run_job(self, job, status: str) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None:
        """Ask for a file to open; None when cancelled."""

    def save_file(self, title: str, name: str) -> Path | None:
        """Ask where to save a file; None when cancelled."""

    def open_path(self, path: Path) -> None: ...


class ModConfigsAdapter(QObject):
    changed = Signal()  # the tree, the profile
    fileChanged = Signal()  # the open file: what it shows (not each keystroke)
    dirtyChanged = Signal()
    diskChangedChanged = Signal()
    pickRequested = Signal(str, dict, list)  # a tick list: its key, its words (presenter.Pick), the rows' labels

    def __init__(
        self, host: ModConfigsHost, notifier: Notifier, presenter: ModConfigsPresenter | None = None, parent=None
    ):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self.presenter = presenter or ModConfigsPresenter()
        self._words = self.presenter.words()
        self._nodes: list[mod_configs.ModNode] = []
        self._profile: Path | None = None
        self._loading = False
        self._refresher = Refresher(self.host, self._snapshot, self._build, self._apply, busy=self._set_loading)
        self._node: mod_configs.ModNode | None = None
        self._opened: mod_configs.Opened | None = None
        self._seamless: mod_configs.Seamless | None = None
        self._pending: dict[tuple[str, str], str] = {}
        self._text = ""
        self._edit_text = False
        self._want: str = ""  # a mod to select once the tree is read (open_mod_configs)
        self._ov: dict | None = None  # the open Overhaul setup: its setup, choices, working values, new?, dirty?
        self._picks: dict[str, Any] = {}  # an open tick list's key -> what runs with the ticked indexes

    # ---- what QML reads
    title = Property(str, lambda self: self._words["title"], constant=True)
    words = Property(dict, lambda self: self._words, constant=True)
    profileName = Property(str, lambda self: self._profile.stem if self._profile else "", notify=changed)
    hasProfile = Property(bool, lambda self: self._profile is not None, notify=changed)
    nodes = Property(
        list,
        lambda self: [
            self.presenter.overhaul_node(n) if n.kind == mod_configs.OVERHAUL else self.presenter.node(n)
            for n in self._nodes
        ],
        notify=changed,
    )
    loading = Property(bool, lambda self: self._loading, notify=changed)
    selectedFile = Property(str, lambda self: self._selected(), notify=fileChanged)
    overhaul = Property(dict, lambda self: self._overhaul_view(), notify=fileChanged)
    canEditText = Property(bool, lambda self: self._can_edit_text(), notify=fileChanged)
    formNote = Property(str, lambda self: self._form_note(), notify=fileChanged)
    overhaulAction = Property(str, lambda self: self._overhaul_action(), notify=fileChanged)
    fileKind = Property(str, lambda self: self._kind(), notify=fileChanged)
    crumb = Property(str, lambda self: self._crumb(), notify=fileChanged)
    sections = Property(list, lambda self: self._sections(), notify=fileChanged)
    seamless = Property(dict, lambda self: self._seamless_view(), notify=fileChanged)
    text = Property(str, lambda self: self._text, notify=fileChanged)
    editText = Property(bool, lambda self: self._edit_text, notify=fileChanged)
    dirty = Property(bool, lambda self: self._is_dirty(), notify=dirtyChanged)
    diskChanged = Property(bool, lambda self: self._disk_changed, notify=diskChangedChanged)
    changedKeys = Property(list, lambda self: self._changed_keys(), notify=dirtyChanged)
    changeText = Property(str, lambda self: self._change_text(), notify=dirtyChanged)
    changeCount = Property(int, lambda self: self._change_count(), notify=dirtyChanged)
    canAttach = Property(
        bool, lambda self: self._node is not None and self._node.target is not None, notify=fileChanged
    )
    selectedAttached = Property(bool, lambda self: self._attached(), notify=fileChanged)

    def _attached(self) -> bool:
        if self._node is None or self._opened is None:
            return False
        return any(f.path == self._opened.path and f.how == "attached" for f in self._node.files)

    def _selected(self) -> str:
        if self._opened is not None:
            return str(self._opened.path)
        return str(self._ov["folder"]) if self._ov is not None else ""  # a new setup: the mod's folder

    def _has_form(self) -> bool:
        """The open file reads as settings (a TOML that does not parse has a doc but no form)."""
        doc = self._opened.doc if self._opened else None
        return doc is not None and (doc.toml is not None or doc.lang != config_model.TOML)

    def _can_edit_text(self) -> bool:
        """The toggle is only for a file that has a form (or an overhaul setup); a plain text file opens as text."""
        if self._opened is None or (self._ov is not None and self._ov["setup"].get("verified")):
            return False
        return self._ov is not None or self._has_form() or self._is_readme()

    def _is_readme(self) -> bool:
        return self._opened is not None and any(
            f.path == self._opened.path and f.kind == mod_configs.README
            for f in (self._node.files if self._node else ())
        )

    def _form_note(self) -> str:
        """Why a settings-looking file opens as text, when it could not be read as settings."""
        doc = self._opened.doc if self._opened else None
        return self._words["noForm"] if doc is not None and not self._has_form() else ""

    def _overhaul_action(self) -> str:
        """What the overhaul menu offers for the open mod: setUp, turnOff, or nothing."""
        if self._node is None or (self._ov is not None and self._ov["new"]):
            return ""
        return self.presenter.overhaul_action(self._node)

    def _kind(self) -> str:
        if self._ov is not None and not self._edit_text:
            return "overhaul"
        if self._opened is None:
            return ""
        if self._edit_text:
            return "text"
        if self._seamless is not None:
            return "seamless"
        if self._is_readme():
            return "readme"
        return "form" if self._has_form() else "text"

    def _crumb(self) -> str:
        if self._node is None:
            return ""
        if self._node.kind == mod_configs.OVERHAUL:
            own = self._node.files[0].path if self._node.files else None
            kept = self._opened is not None and self._opened.path != own
            name = self.presenter.overhaul_node(self._node)["name"] if self._node.setup else self._node.name
            return self.presenter.crumb(name, self._opened.path if kept and self._opened else None)
        return self.presenter.crumb(
            self.presenter.node(self._node)["name"], self._opened.path if self._opened else None
        )

    def _sections(self) -> list:
        if self._opened is None or self._opened.doc is None:
            return []
        if self._seamless is not None:
            return self.presenter.form(self._opened.doc, seamless=True, skip=SEAMLESS_OWN)
        return self.presenter.form(self._opened.doc)

    def _seamless_view(self) -> dict:
        if self._seamless is None:
            return {}
        line, note = "", ""
        profile, loc = self._profile, self.host.locations
        if profile is not None and loc is not None:
            from roundtable_souls.services import game_checks

            fp = game_checks.regulation_fingerprint(profile, loc)
            words = ModsPresenter()
            line = words.fingerprint(fp, loc.game.regulation)
            note = words.parameters({}, False, fp).fingerprint_note if fp else ""
        s = self._seamless
        if s.spec is not None and s.scaling is not None:  # a preset or a number changed and not saved yet
            values = tuple(
                int(self._pending.get(("SCALING", k), v)) for k, v in zip(s.spec.keys, s.scaling, strict=True)
            )
            s = dataclasses.replace(s, scaling=values, preset=coop_scaling.preset_of(values, s.spec))
        return self.presenter.seamless(s, line, note)

    def _changed_keys(self) -> list:
        """ "section|key" of every setting whose waiting value differs from the file's (the form's Changed marker)."""
        opened = self._opened
        if not self._pending or opened is None or opened.doc is None:
            return []
        disk = config_model.parse(opened.text, opened.doc.lang)
        out = []
        for (section, key), value in self._pending.items():
            item = disk.find(key, section)
            if item is None or item.value != value:
                out.append(f"{section}|{key}")
        return out

    def _change_text(self) -> str:
        n = self._change_count()
        if n == 0:
            return tr("No changes")
        return plural("{n} change not saved", "{n} changes not saved", n).format(n=n)

    @Slot()
    def openMods(self) -> None:
        self.host.show_page("mods")

    def _change_count(self) -> int:
        if self._ov is not None and not self._edit_text:
            return 1 if self._ov["dirty"] else 0
        if self._edit_text or self._kind() == "text":
            return 1 if self._is_dirty() else 0
        return len(self._changed_keys())

    def _is_dirty(self) -> bool:
        if self._ov is not None and not self._edit_text:
            return bool(self._ov["dirty"])
        if self._opened is None:
            return False
        if self._edit_text or self._kind() == "text":
            return self._text != self._opened.text
        return bool(self._pending)

    # ---- reading
    # ---- what the shell's menu and keys may ask of this page (ui/launcher/menu.py)
    COMMANDS = {
        "saveUnsaved": "save",
        "discardUnsaved": "discard",
        "back": "_back",
    }

    def command(self, name: str, args) -> bool:
        """Run a menu command; False when this page has none by that name."""
        method = self.COMMANDS.get(name)
        if method is None:
            return False
        getattr(self, method)(*args)
        return True

    def _back(self) -> None:
        pass

    def unsaved_words(self) -> list[str]:
        return [tr("Mod Configs: a settings file has changes that are not saved")] if self._is_dirty() else []

    def seamless_pending(self) -> bool:
        """Seamless Co-op settings edited and not saved: they are applied by Launch."""
        return bool(self._seamless is not None and self._pending)

    def save_pending_seamless(self) -> str | None:
        """Launch saves what is pending first (a pending password or scaling): the reason it could not, or None."""
        if not self.seamless_pending():
            return None
        self.save()
        return None if not self.seamless_pending() else tr("The co-op settings could not be saved, so Launch stopped.")

    @Slot()
    def refresh(self) -> None:
        self._refresher.request()

    def _snapshot(self) -> tuple:
        return self.host.profile, self.host.locations, self.host.settings

    @staticmethod
    def _build(snap: tuple):
        profile, loc, settings = snap
        if profile is None or not Path(profile).is_file() or loc is None:
            return None, []
        return Path(profile), mod_configs.tree(profile, loc=loc, settings=settings)

    def _set_loading(self, on: bool) -> None:
        self._loading = on
        self.changed.emit()

    def _apply(self, got) -> None:
        profile, nodes = got
        moved = profile != self._profile
        self._profile, self._nodes = profile, nodes
        self.changed.emit()
        want = self._want or (self._node.key if self._node and not moved else "")
        self._want = ""
        node = next((n for n in nodes if n.key == want or n.name.lower() == want.lower()), None) if want else None
        if node is None and (moved or self._node is None):
            node = nodes[0] if nodes else None
        if (
            node is not None
            and node.files
            and (moved or self._opened is None or node.key != getattr(self._node, "key", ""))
        ):
            self._open(node, node.files[0].path)
        elif node is None:
            self._close()

    def select_mod(self, name: str) -> None:
        """Select a mod by its name or key once the tree is read (the Mods page's links)."""
        self._want = name
        self.refresh()

    @Slot(str, str)
    def selectFile(self, key: str, path: str) -> None:
        node = next((n for n in self._nodes if n.key == key), None)
        if node is not None:
            self._guard(lambda: self._open(node, Path(path)))

    def _guard(self, then) -> None:
        """Run then, asking first when the open file has unsaved changes (Discard goes on, Cancel stays)."""
        if not self._is_dirty():
            then()
            return
        words = Confirm(
            title=self._words["unsavedTitle"], changes=(self._words["unsavedBody"],), apply=self._words["discard"]
        )
        self.notifier.ask(words, lambda ok, _o: then() if ok else None)

    def _open(self, node: mod_configs.ModNode, path: Path) -> None:
        self._node, self._pending, self._edit_text = node, {}, False
        self._seamless = self._ov = None
        self._open_token = token = getattr(self, "_open_token", 0) + 1
        setup_file = node.kind == mod_configs.OVERHAUL and bool(node.setup) and node.files[0].path == path

        def work():  # the file is read off the UI thread
            try:
                self._mtime = _stamp(path)
                opened = mod_configs.open_file(path, form=not setup_file)
                seamless = mod_configs.seamless(path) if node.kind == mod_configs.SEAMLESS else None
                return opened, seamless, None
            except Exception as e:  # too big, not text, gone: said, nothing open
                return None, None, e

        def got(result) -> None:
            if token != self._open_token or self._node is not node:  # a newer open or a close came first
                return
            self._set_disk_changed(False)
            self._opened, self._seamless, err = result
            try:
                if err is None and node.kind != mod_configs.SEAMLESS and setup_file and node.setup:
                    self._ov = self._new_ov(node.setup, None)
            except Exception as e:
                self._opened, err = None, e
            if err is not None:
                self._refuse(self.presenter.unreadable(path.name, str(err)))
            self._text = self._opened.text if self._opened else ""
            self.fileChanged.emit()
            self.dirtyChanged.emit()

        self.host.run_in_background(work, got)

    _mtime: tuple[int, int] | None = None
    _disk_changed = False

    def _set_disk_changed(self, on: bool) -> None:
        if on != self._disk_changed:
            self._disk_changed = on
            self.diskChangedChanged.emit()

    @Slot()
    def checkDisk(self) -> None:
        """Has the open file changed on disk since it was read? (a stat, off the UI thread)"""
        opened, seen = self._opened, self._mtime
        if opened is None or seen is None or self._disk_changed:
            return
        path = opened.path
        self.host.run_in_background(
            lambda: _stamp(path), lambda now: self._set_disk_changed(now is not None and now != seen)
        )

    @Slot()
    def reload(self) -> None:
        """Read the file again, dropping the waiting edits (the InfoBar's Reload)."""
        self._reopen()

    def _close(self) -> None:
        self._open_token = getattr(self, "_open_token", 0) + 1
        self._node = self._opened = self._seamless = self._ov = None
        self._pending, self._text = {}, ""
        self.fileChanged.emit()
        self.dirtyChanged.emit()

    def _reopen(self) -> None:
        if self._node is not None and self._opened is not None:
            self._open(self._node, self._opened.path)
        elif self._ov is not None and self._ov["mod"] is not None:  # a new setup: back to the proposal
            self._start_new(self._ov["setup"]["config"], self._ov["mod"])

    def _refuse(self, r: Refusal) -> None:
        self.notifier.toast(f"{r.title}. {r.body}", error=True)

    # ---- editing
    @Slot(str, str, str)
    def setValue(self, section: str, key: str, value: str) -> None:
        if self._ov is not None and not self._edit_text:
            self._set_overhaul(key, value)
            return
        self._pending[(section, key)] = value
        self.dirtyChanged.emit()

    @Slot(str, str)
    def resetValue(self, section: str, key: str) -> None:
        item = self._opened.doc.find(key, section) if self._opened and self._opened.doc else None
        if item is None:
            return
        value, _source = mod_configs.reset_value(item)
        if value == item.value:
            self._pending.pop((section, key), None)
        else:
            self._pending[(section, key)] = value
        self._apply_pending_view()

    @Slot()
    def resetAll(self) -> None:
        doc = self._opened.doc if self._opened else None
        if doc is None:
            return
        for s in doc.sections:
            for item in s.settings:
                if item.default is not None and not item.readonly and item.default != item.value:
                    self._pending[(s.name, item.key)] = item.default
        self._apply_pending_view()

    def _apply_pending_view(self) -> None:
        """Show the waiting values in the form (Reset changes what a control shows)."""
        opened = self._opened
        if opened is not None and opened.doc is not None:
            fresh = config_model.parse(opened.text, opened.doc.lang)
            for (section, key), value in self._pending.items():
                fresh.set(key, value, section)
            opened.doc = fresh
        self.fileChanged.emit()
        self.dirtyChanged.emit()

    @Slot(str)
    def setPreset(self, name: str) -> None:
        spec = self._seamless.spec if self._seamless else None
        values = spec.presets.get(name) if spec else None
        if spec is None or values is None:
            return
        for key, value in zip(spec.keys, values, strict=True):
            self._pending[("SCALING", key)] = str(value)
        self.fileChanged.emit()
        self.dirtyChanged.emit()

    @Slot(str)
    def edit(self, text: str) -> None:
        self._text = text
        self.dirtyChanged.emit()

    @Slot(bool)
    def setEditText(self, on: bool) -> None:
        if self._opened is None or on == self._edit_text:
            return
        self._guard(lambda: self._switch_text(on))

    def _switch_text(self, on: bool) -> None:
        self._pending, self._text = {}, self._opened.text if self._opened else ""
        self._edit_text = on
        self.fileChanged.emit()
        self.dirtyChanged.emit()

    @Slot()
    def discard(self) -> None:
        self._reopen()

    @Slot()
    def save(self) -> None:
        opened = self._opened
        if self._ov is not None and not self._edit_text and self._is_dirty():
            self._save_overhaul()
            return
        if opened is None or not self._is_dirty():
            return
        try:
            if self._ov is not None:  # the setup's own file, as text
                self._save_overhaul_text(opened)
                return
            if self._kind() == "text":
                mod_configs.save_text(opened, self._text)
                said = self.presenter.saved_text(opened.path.name)
            elif self._seamless is not None:
                values = {key: value for (_section, key), value in self._pending.items()}
                missing = mod_configs.save_seamless(opened.path, values)
                if missing:
                    self._refuse(self.presenter.missing_keys(opened.path.name, missing))
                said = self.presenter.saved(len(values) - len(missing))
            else:
                mod_configs.save_values(opened, dict(self._pending))
                said = self.presenter.saved(len(self._pending))
        except ValueError as e:
            empty = "password" in str(e).lower()
            self._refuse(self.presenter.empty_password() if empty else self.presenter.could_not_save(str(e)))
            return
        except Exception as e:  # changed on disk, can't be written: nothing changed
            self._refuse(self.presenter.could_not_save(str(e)))
            return
        self.notifier.toast(said)
        self._reopen()

    # ---- the Overhaul setup (S7d): the profile's overhaul as a form, turned off, or a mod set up as one
    def _new_ov(self, setup: dict, mod: dict | None) -> dict:
        """The form's state for a setup: the choices the mod's files give and the values as the config has them."""
        choices = mod_configs.overhaul_choices(setup)
        values = {
            "natives": choices["natives"],
            "keep": {f for f, on in choices["keep"] if on},
            "off": {f for f, on in choices["merged"] if not on},
            "place": dict(choices["place"]),
        }
        return {
            "setup": setup,
            "choices": choices,
            "values": values,
            "new": mod is not None,
            "mod": mod,
            "folder": setup.get("folder"),
            "dirty": mod is not None,  # a proposal is saved to set the mod up
        }

    def _overhaul_view(self) -> dict:
        ov = self._ov
        if ov is None:
            return {}
        config = ov["setup"]["config"]
        return self.presenter.overhaul(
            ov["setup"], ov["choices"], ov["values"], mod_configs.step_lines(config), bool(ov["new"])
        )

    def _set_overhaul(self, key: str, value: str) -> None:
        ov = self._ov
        if ov is None:
            return
        kind, _, name = key.partition(":")
        values = ov["values"]
        native = next((n for n in values["natives"] if n["file"] == name), None)
        if kind == "early" and native is not None:
            native["load_early"] = value == "true"
        elif kind == "after" and native is not None:
            native["after_others"] = value == "true"
        elif kind == "init" and native is not None:
            native["initializer"] = value.strip() or None
        elif kind == "keep":
            values["keep"].add(name) if value == "true" else values["keep"].discard(name)
        elif kind == "place":
            values["place"][name] = value.strip()
        elif kind == "merge":
            values["off"].discard(name) if value == "true" else values["off"].add(name)
        ov["dirty"] = True
        self.dirtyChanged.emit()

    def _with_values(self):
        ov = self._ov
        assert ov is not None
        values = ov["values"]
        return mod_configs.with_basic(
            ov["setup"]["config"],
            natives=values["natives"],
            keep=sorted(values["keep"]),
            not_merged=sorted(values["off"]),
            place={k: v for k, v in values["place"].items() if v},
        )

    def _saved(self, node_key: str, said: str) -> None:
        self.notifier.toast(said)
        self._want, self._opened = node_key, None  # read the tree again: the file's fingerprint changed
        self.refresh()

    def _save_overhaul(self) -> None:
        ov = self._ov
        if ov is None or self._node is None:
            return
        config = self._with_values()
        if ov["new"]:
            self._install_new(config)
            return
        setup = ov["setup"]
        try:
            mod_service.save_overhaul_setup(config, expect=setup["sha"], path=setup["path"], folder=setup["folder"])
        except Exception as e:  # a verified one, changed on disk since, a config that would not read back
            self._refuse(self.presenter.could_not_save(str(e)))
            return
        self._saved(self._node.key, self.presenter.saved_text(setup["path"].name))
        self._reapply()

    def _reapply(self) -> None:
        """The saved setup, installed again in the profiles using it (their entries are the install's, not the file's)."""
        profile = self._profile
        if profile is None or self.host.busy:
            return

        def job(_launch, loc):
            from roundtable_souls.platform import logging as run_logging

            run_logging.start_log("launcher: apply the saved overhaul setup", loc.game.key)
            try:
                mod_service.reapply_overhaul_setup(profile, loc=loc)
            except Exception as e:
                run_logging.log(f"error: {e}")
                raise SystemExit(1) from e

        self.host.run_job(job, tr("Applying the overhaul setup to the profiles using it..."))

    def _save_overhaul_text(self, opened: mod_configs.Opened) -> None:
        try:
            config = mod_configs.parse_overhaul_text(self._text)
            mod_service.save_overhaul_setup(config, expect=opened.sha, path=opened.path)
        except Exception as e:
            self._refuse(self.presenter.could_not_save(str(e)))
            return
        self._saved(self._node.key if self._node else "overhaul", self.presenter.saved_text(opened.path.name))
        self._reapply()

    def _start_new(self, config, mod: dict) -> None:
        """Show the proposal for a mod as a new setup (nothing is written until Save is confirmed)."""
        setup = {
            "config": config,
            "verified": False,
            "level": "basic",
            "folder": mod["folder"],
            "path": None,
            "sha": None,
        }
        self._node = mod_configs.ModNode(
            "overhaul:new", config.label, mod_configs.OVERHAUL, True, True, None, (), setup
        )
        self._opened = self._seamless = None
        self._pending, self._text, self._edit_text = {}, "", False
        self._ov = self._new_ov(setup, mod)
        self.fileChanged.emit()
        self.dirtyChanged.emit()
        self.changed.emit()

    def _install_new(self, config) -> None:
        profile, loc, ov = self._profile, self.host.locations, self._ov
        if profile is None or ov is None or self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        folder = ov["folder"]

        def work():
            try:
                return mod_service.preview_overhaul_setup(profile, folder, config, loc=loc), ""
            except Exception as e:
                return None, str(e)

        def got(result) -> None:
            preview, why = result
            if preview is None:
                self._refuse(Refusal(tr("Can't set it up"), why))
                return
            words = self.presenter.install_setup(preview)
            if isinstance(words, Refusal):
                self._refuse(words)
                return

            def answered(ok: bool, _option: bool) -> None:
                if not ok or self.host.busy:
                    return

                def job(_launch, loc):
                    from roundtable_souls.platform import logging as run_logging

                    run_logging.start_log(f"launcher: set up {preview.label} as an overhaul", loc.game.key)
                    mod_service.install_overhaul_setup(preview, loc=loc)

                self._want = "overhaul"
                self.host.run_job(job, tr("Installing {label} as an overhaul...").format(label=preview.label))

            self.notifier.ask(words, answered)

        self.host.run_in_background(work, got)

    @Slot(str)
    def addOverhaulSetup(self, key: str) -> None:
        """Set a mod of the profile up as an overhaul: the mod of the node key (its button), else one picked from a
        list of the profile's mods."""
        profile = self._profile
        if profile is None or self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        mods = mod_configs.mods_to_set_up(profile)
        node = next((n for n in self._nodes if n.key == key), None) if key else None

        def go(mod: dict) -> None:
            try:
                config = mod_service.propose_overhaul_setup(
                    mod["folder"], mod["name"], loc=self.host.locations, overhaul_id=mod["id"] or None
                )
            except ValueError as e:
                self._refuse(Refusal(tr("Can't set it up"), str(e)))
                return
            self._guard(lambda: self._start_new(config, mod))

        chosen = next((m for m in mods if node is not None and m["name"] == node.name), None)
        if chosen is not None:
            go(chosen)
        elif mods:
            self._pick(
                self.presenter.pick_overhaul_mod(),
                [m["name"] for m in mods],
                lambda ticked: go(mods[ticked[0]]) if ticked else None,
            )
        else:
            self._refuse(Refusal(tr("Nothing to set up"), self._words["noMods"]))

    @Slot()
    def setUpSelectedAsOverhaul(self) -> None:
        self.addOverhaulSetup(self._node.key if self._node else "")

    @Slot()
    def turnOffOverhaul(self) -> None:
        profile, loc = self._profile, self.host.locations
        setup = self._ov["setup"] if self._ov is not None and not self._ov["new"] else None
        if setup is None and self._node is not None and self._node.kind == mod_configs.OVERHAUL:
            setup = self._node.setup  # a kept file of the overhaul is open: its setup is the node's
        if profile is None or setup is None or setup.get("verified") or self.host.busy:
            return
        label = setup["config"].label

        def work():
            try:
                return mod_service.preview_turn_off_overhaul(profile, loc=loc), ""
            except Exception as e:
                return None, str(e)

        def got(result) -> None:
            preview, why = result
            if preview is None:
                self._refuse(Refusal(tr("Can't turn it off"), why))
                return
            words = self.presenter.turn_off(preview)
            if isinstance(words, Refusal):
                self._refuse(words)
                return

            def answered(ok: bool, _option: bool) -> None:
                if not ok or self.host.busy:
                    return

                def job(_launch, loc):
                    from roundtable_souls.platform import logging as run_logging

                    run_logging.start_log(f"launcher: turn off overhaul {label}", loc.game.key)
                    mod_service.turn_off_overhaul(preview)

                self.host.run_job(job, tr("Removing the overhaul setup of {label}...").format(label=label))

            self.notifier.ask(words, answered, destructive=True)

        self.host.run_in_background(work, got)

    def _pick(self, words: Pick, rows: list[str], then) -> None:
        key = f"pick-{len(self._picks) + 1}"
        self._picks[key] = then
        self.pickRequested.emit(key, plain(words), rows)

    @Slot(str, list)
    def picked(self, key: str, indexes: list) -> None:
        then = self._picks.pop(key, None)
        if then is not None:
            then([int(i) for i in indexes])

    @Slot(str)
    def pickCancelled(self, key: str) -> None:
        self._picks.pop(key, None)

    # ---- attaching a file to a mod
    @Slot()
    def attachFile(self) -> None:
        node = self._node
        if node is None or node.target is None:
            return
        got = self.host.pick_file(self._words["attach"], "")
        if got is None:
            return
        mod_configs.attach(self.host.settings, node.target, got)
        self._want = node.key
        self.refresh()

    @Slot(str)
    def detachFile(self, path: str) -> None:
        node = self._node
        if node is None or node.target is None:
            return
        mod_configs.detach(self.host.settings, node.target, Path(path))
        self._want = node.key
        self._opened = None
        self.refresh()

    # ---- Seamless Co-op: sharing with a friend
    @Slot()
    def copySettings(self) -> None:
        if self._seamless is None:
            return
        from PySide6.QtGui import QGuiApplication

        QGuiApplication.clipboard().setText(mod_configs.share_text(self._seamless.ini))
        self.notifier.toast(self.presenter.copied())

    @Slot()
    def pasteSettings(self) -> None:
        from PySide6.QtGui import QGuiApplication

        self._take_shared(QGuiApplication.clipboard().text())

    @Slot()
    def loadSettings(self) -> None:
        got = self.host.pick_file(self._words["load"], "Settings (*.ini *.txt *.json)")
        if got is not None:
            try:
                self._take_shared(got.read_text(encoding="utf-8", errors="replace"))
            except OSError as e:
                self._refuse(self.presenter.not_settings(str(e)))

    @Slot()
    def saveSettingsAs(self) -> None:
        if self._seamless is None:
            return
        got = self.host.save_file(self._words["saveAs"], "seamless-coop-settings.ini")
        if got is not None:
            got.write_text(mod_configs.share_text(self._seamless.ini), encoding="utf-8")
            self.notifier.toast(tr("Saved {name}").format(name=got.name))

    def _take_shared(self, text: str) -> None:
        ini = self._seamless.ini if self._seamless else None
        if ini is None:
            return
        try:
            changes, unknown, opened = mod_configs.plan_paste(ini, text)
        except Exception as e:
            self._refuse(self.presenter.not_settings(str(e)))
            return
        if not changes:
            self.notifier.toast(self.presenter.nothing_to_change(unknown))
            return

        def answered(ok: bool, _option: bool) -> None:
            if not ok:
                return
            try:
                mod_configs.apply_paste(opened, changes)
            except Exception as e:
                self._refuse(self.presenter.could_not_save(str(e)))
                return
            self.notifier.toast(self.presenter.saved(len(changes)))
            self._reopen()

        self._guard(lambda: self.notifier.ask(self.presenter.paste(changes, unknown), answered))

    @Slot()
    def openFolder(self) -> None:
        if self._opened is not None:
            self.host.open_path(self._opened.path.parent)
