"""The Mod Configs page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). What to
show comes from the presenter, what a change does from services/mod_configs.py. The tree is read on the host's
worker; one file is read when it is picked (settings files are small). Edits wait in `pending` until Save, which
writes only those values (refused when the file changed on disk since it was read)."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from PySide6.QtCore import Property, QObject, Signal, Slot

from bayle.coop import scaling as coop_scaling
from bayle.errors import OperationError
from bayle.formats import config_model
from bayle.platform.text import plural, tr
from bayle.services import mod_configs
from bayle.session import Session
from bayle.ui.models import plain
from bayle.ui.notifications import Notifier
from bayle.ui.refresh import Refresher
from bayle.views.mod_configs import ModConfigsPresenter
from bayle.views.mods import Confirm, Pick, Refusal
from bayle.work.prompts import Plan

SEAMLESS_OWN = ("PASSWORD", "SCALING", "LANGUAGE")  # sections the Seamless panel shows itself


def _why(e: Exception) -> str:
    return e.message if isinstance(e, OperationError) else str(e)


class ModConfigsHost(Protocol):
    """What the page needs from the window that hosts it (the Widgets launcher until the shell, S9)."""

    @property
    def busy(self) -> bool: ...
    @property
    def profile(self) -> Path | None: ...
    @property
    def session(self) -> Session: ...
    def run_in_background(self, work, on_result) -> None: ...
    def show_page(self, name: str) -> Any: ...
    def settings_changed(self, key: str) -> None:
        """A page saved key (here native_configs): the shell reads the settings again."""

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
        self._fingerprint = ("", "")  # Seamless: the regulation line and its note, read with the file
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
        s = self._seamless
        if s.spec is not None and s.scaling is not None:  # a preset or a number changed and not saved yet
            values = tuple(
                int(self._pending.get(("SCALING", k), v)) for k, v in zip(s.spec.keys, s.scaling, strict=True)
            )
            s = dataclasses.replace(s, scaling=values, preset=coop_scaling.preset_of(values, s.spec))
        return self.presenter.seamless(s, *self._fingerprint)

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

    def _snapshot(self) -> Path | None:
        return self.host.profile

    def _build(self, profile: Path | None):
        state = self.host.session.snapshot("mod_configs", profile=str(profile) if profile else "")
        return (Path(state.profile) if state.profile else None), list(state.nodes)

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
        session, profile = self.host.session, self._profile

        def work():  # the file is read off the UI thread
            try:
                read = session.run(
                    "mod_configs.open",
                    {"path": str(path), "seamless": node.kind == mod_configs.SEAMLESS, "profile": str(profile or "")},
                )
                doc = None if setup_file else mod_configs.parse_doc(path.name, read.text)
                opened = mod_configs.Opened(path, read.text, read.encoding, read.crlf, read.sha, doc)
                form = None
                if setup_file and node.kind != mod_configs.SEAMLESS and node.setup:
                    form = session.run("mod_configs.overhaul_form", {"profile": str(profile)})
                return read, opened, form, None
            except Exception as e:  # too big, not text, gone: said, nothing open
                return None, None, None, e

        def got(result) -> None:
            if token != self._open_token or self._node is not node:  # a newer open or a close came first
                return
            self._set_disk_changed(False)
            read, self._opened, form, err = result
            self._mtime = read.stamp if read is not None else None
            self._seamless = read.seamless if read is not None else None
            self._fingerprint = (read.fingerprint, read.fingerprint_note) if read is not None else ("", "")
            if form is not None:
                self._ov = self._ov_state(form, None)
            if err is not None:
                self._refuse(self.presenter.unreadable(path.name, _why(err)))
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
        session, path = self.host.session, str(opened.path)
        self.host.run_in_background(
            lambda: session.run("mod_configs.stamp", {"path": path}).stamp,
            lambda now: self._set_disk_changed(now is not None and now != seen),
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
            self._start_new(self._ov["mod"])

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
        if self._ov is not None:  # the setup's own file, as text
            self._save_overhaul_text(opened)
            return
        path = str(opened.path)
        if self._kind() == "text":
            kind, params = "text", {"path": path, "expect": opened.sha, "kind": "text", "text": self._text}
        else:
            edits = [
                {"section": section or "", "key": key, "value": value}
                for (section, key), value in self._pending.items()
            ]
            kind = "seamless" if self._seamless is not None else "values"
            params = {"path": path, "expect": opened.sha, "kind": kind, "edits": edits}
        self._call("mod_configs.save", params, lambda r: self._saved_file(opened, kind, r), self._save_failed)

    def _saved_file(self, opened: mod_configs.Opened, kind: str, r) -> None:
        if kind == "text":
            said = self.presenter.saved_text(opened.path.name)
        else:
            if r.missing:
                self._refuse(self.presenter.missing_keys(opened.path.name, list(r.missing)))
            said = self.presenter.saved(r.saved)
        self.notifier.toast(said)
        self._reopen()

    def _save_failed(self, e: OperationError) -> None:
        self._refuse(
            self.presenter.empty_password() if e.code == "password_empty" else self.presenter.could_not_save(e.message)
        )

    # ---- asking the session (every call runs on the host's worker; the answer comes back on the UI thread)
    def _call(
        self,
        name: str,
        params: dict,
        then: Callable[[Any], None],
        failed: Callable[[OperationError], None] | None = None,
    ) -> None:
        session = self.host.session

        def work():
            try:
                return session.run(name, params), None
            except OperationError as e:
                return None, e

        def landed(got) -> None:
            value, err = got
            if err is None:
                then(value)
            else:
                (failed or self._failed)(err)

        self.host.run_in_background(work, landed)

    def _failed(self, e: OperationError) -> None:
        """An operation said no: the code says why, never its words."""
        match e.code:
            case "password_empty":
                self._refuse(self.presenter.empty_password())
            case "cannot_set_up":
                self._refuse(Refusal(tr("Can't set it up"), e.message))
            case "cannot_turn_off":
                self._refuse(Refusal(tr("Can't turn it off"), e.message))
            case "not_settings":
                self._refuse(self.presenter.not_settings(e.message))
            case "nothing_to_change":
                self.notifier.toast(e.message)
            case "busy" | "plan_stale" | "plan_expired" | "unknown_plan":
                self.notifier.toast(e.message, error=True)
            case _:
                self._refuse(self.presenter.could_not_save(e.message))

    def _ask(
        self,
        name: str,
        params: dict,
        *,
        destructive: bool = False,
        guard: bool = False,
        confirmed: Callable[[], None] | None = None,
        done: Callable[[Plan], None] | None = None,
    ) -> None:
        """A plan operation: get its question, show it (after the unsaved-changes guard when guard), send the answer.
        confirmed runs when the user says yes, done when the answered plan has run."""
        session = self.host.session

        def answered(plan: Plan, ok: bool) -> None:
            if ok and confirmed is not None:
                confirmed()

            def answer():
                try:
                    session.answer(plan.id, {"ok": ok})
                    return None
                except OperationError as e:
                    return e

            def landed(err: OperationError | None) -> None:
                if err is not None:
                    self._failed(err)
                elif ok and done is not None:
                    done(plan)

            self.host.run_in_background(answer, landed)

        def shown(plan: Plan | Refusal) -> None:
            if isinstance(plan, Refusal):
                self._refuse(plan)
                return

            def ask() -> None:
                if isinstance(plan.words, Confirm):
                    self.notifier.confirm(plan.words, lambda ok: answered(plan, ok), destructive)

            self._guard(ask) if guard else ask()

        self._call(name, params, shown)

    # ---- the Overhaul setup (S7d): the profile's overhaul as a form, turned off, or a mod set up as one
    def _ov_state(self, form, mod: dict | None) -> dict:
        """The form's state for a setup: the choices the mod's files give and the values as the config has them."""
        return {
            "setup": form.setup,
            "choices": form.choices,
            "values": form.values,
            "new": mod is not None,
            "mod": mod,
            "folder": form.setup.get("folder"),
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
        patch = mod_configs.FormPatch.of(key, value)
        if patch is not None:
            mod_configs.patch_values(ov["values"], patch)
        ov["dirty"] = True
        self.dirtyChanged.emit()

    def _form(self) -> dict:
        """The form's values as the operations take them (the log check only when it was touched)."""
        assert self._ov is not None
        values = self._ov["values"]
        return {
            "natives": values["natives"],
            "files": values["files"],
            "tables": values["tables"],
            "health": values["health"] if values.get("health_touched") else None,
        }

    def _saved(self, node_key: str, said: str) -> None:
        self.notifier.toast(said)
        self._want, self._opened = node_key, None  # read the tree again: the file's fingerprint changed
        self.refresh()

    def _save_overhaul(self) -> None:
        ov = self._ov
        if ov is None or self._node is None:
            return
        if ov["new"]:
            self._install_new()
            return
        setup, key = ov["setup"], self._node.key
        params = {
            "profile": str(self._profile),
            "path": str(setup["path"]),
            "expect": setup["sha"],
            "form": self._form(),
        }
        self._call("mod_configs.save_setup", params, lambda r: self._setup_saved(key, r))

    def _setup_saved(self, node_key: str, r) -> None:
        self._saved(node_key, self.presenter.saved_text(r.name))
        self._reapply(r.overhaul_id)

    def _reapply(self, overhaul_id: str) -> None:
        """The saved setup, installed again in the profiles using it (their entries are the install's, not the file's)."""
        profile = self._profile
        if profile is None:
            return

        def failed(e: OperationError) -> None:
            if e.code == "busy":
                self.notifier.toast(
                    tr("Saved, but not applied to the profiles yet: wait for the current job, then save again."),
                    error=True,
                )
            else:
                self._failed(e)

        params = {"profile": str(profile), "overhaul_id": overhaul_id}
        self._call("mod_configs.apply_setup", params, lambda _job: None, failed)

    def _save_overhaul_text(self, opened: mod_configs.Opened) -> None:
        params = {"profile": str(self._profile), "path": str(opened.path), "expect": opened.sha, "text": self._text}
        key = self._node.key if self._node else "overhaul"
        self._call("mod_configs.save_setup", params, lambda r: self._setup_saved(key, r))

    def _start_new(self, mod: dict) -> None:
        """Show the proposal for a mod as a new setup (nothing is written until Save is confirmed)."""
        params = {
            "profile": str(self._profile),
            "folder": str(mod["folder"]),
            "name": mod["name"],
            "overhaul_id": mod["id"] or "",
        }
        self._call("mod_configs.overhaul_form", params, lambda form: self._show_new(form, mod))

    def _show_new(self, form, mod: dict) -> None:
        setup = form.setup
        self._node = mod_configs.ModNode(
            "overhaul:new", setup["config"].label, mod_configs.OVERHAUL, True, True, None, (), setup
        )
        self._opened = self._seamless = None
        self._pending, self._text, self._edit_text = {}, "", False
        self._ov = self._ov_state(form, mod)
        self.fileChanged.emit()
        self.dirtyChanged.emit()
        self.changed.emit()

    def _install_new(self) -> None:
        profile, ov = self._profile, self._ov
        if profile is None or ov is None or self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        mod = ov["mod"]
        params = {
            "profile": str(profile),
            "folder": str(ov["folder"]),
            "name": mod["name"],
            "overhaul_id": mod["id"] or "",
            "form": self._form(),
        }
        self._ask("mod_configs.install_setup", params, confirmed=lambda: setattr(self, "_want", "overhaul"))

    @Slot(str)
    def addOverhaulSetup(self, key: str) -> None:
        """Set a mod of the profile up as an overhaul: the mod of the node key (its button), else one picked from a
        list of the profile's mods."""
        profile = self._profile
        if profile is None or self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        node = next((n for n in self._nodes if n.key == key), None) if key else None
        self._call(
            "mod_configs.setup_candidates",
            {"profile": str(profile)},
            lambda r: self._choose_to_set_up([m.model_dump() for m in r.mods], node),
        )

    def _choose_to_set_up(self, mods: list[dict], node: mod_configs.ModNode | None) -> None:
        def go(mod: dict) -> None:
            self._guard(lambda: self._start_new(mod))

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
        profile = self._profile
        setup = self._ov["setup"] if self._ov is not None and not self._ov["new"] else None
        if setup is None and self._node is not None and self._node.kind == mod_configs.OVERHAUL:
            setup = self._node.setup  # a kept file of the overhaul is open: its setup is the node's
        if profile is None or setup is None or setup.get("verified") or self.host.busy:
            return
        self._ask("mod_configs.turn_off", {"profile": str(profile)}, destructive=True)

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
        params = {"target": str(node.target), "file": str(got)}
        self._call("mod_configs.attach", params, lambda _r: self._tied(node.key))

    @Slot(str)
    def detachFile(self, path: str) -> None:
        node = self._node
        if node is None or node.target is None:
            return
        self._opened = None
        params = {"target": str(node.target), "file": path}
        self._call("mod_configs.detach", params, lambda _r: self._tied(node.key))

    def _tied(self, node_key: str) -> None:
        self.host.settings_changed("native_configs")
        self._want = node_key
        self.refresh()

    # ---- Seamless Co-op: sharing with a friend
    @Slot()
    def copySettings(self) -> None:
        if self._seamless is None:
            return
        from PySide6.QtGui import QGuiApplication

        def copy(r) -> None:
            QGuiApplication.clipboard().setText(r.text)
            self.notifier.toast(self.presenter.copied())

        self._call("mod_configs.share", {"ini": str(self._seamless.ini)}, copy)

    @Slot()
    def pasteSettings(self) -> None:
        from PySide6.QtGui import QGuiApplication

        self._take_shared(QGuiApplication.clipboard().text())

    @Slot()
    def loadSettings(self) -> None:
        got = self.host.pick_file(self._words["load"], "Settings (*.ini *.txt *.json)")
        if got is None:
            return

        def read():
            try:
                return got.read_text(encoding="utf-8", errors="replace"), None
            except OSError as e:
                return None, e

        def read_done(result) -> None:
            text, err = result
            if err is not None:
                self._refuse(self.presenter.not_settings(str(err)))
            else:
                self._take_shared(text)

        self.host.run_in_background(read, read_done)

    @Slot()
    def saveSettingsAs(self) -> None:
        if self._seamless is None:
            return
        got = self.host.save_file(self._words["saveAs"], "seamless-coop-settings.ini")
        if got is not None:
            self._call(
                "mod_configs.export_share",
                {"ini": str(self._seamless.ini), "to": str(got)},
                lambda _r: self.notifier.toast(tr("Saved {name}").format(name=got.name)),
            )

    def _take_shared(self, text: str) -> None:
        ini = self._seamless.ini if self._seamless else None
        if ini is None:
            return

        def pasted(plan: Plan) -> None:
            n = len(plan.words.changes) if isinstance(plan.words, Confirm) else 0
            self.notifier.toast(self.presenter.saved(n))
            self._reopen()

        self._ask("mod_configs.paste", {"ini": str(ini), "text": text}, guard=True, done=pasted)

    @Slot()
    def openFolder(self) -> None:
        if self._opened is not None:
            self.host.open_path(self._opened.path.parent)
