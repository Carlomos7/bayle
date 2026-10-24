"""The Mod Configs page's adapter: the thin QObject the QML page binds to (technical specification §8.6 D5). What to
show comes from the presenter, what a change does from the engine's Mod configs interface (host.features.mod_configs,
services/mod_configs.py), called on the host's worker. The tree is read there; one file is read when it is picked
(settings files are small). Edits wait in `pending` until Save, which writes only those values (refused as stale when
the file changed on disk since it was read). Installing, turning off, applying and exporting are jobs the page
follows; the plans are a check, the presenter's words asked through the Notifier, and a start with the stamp checked."""

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
from bayle.services.features import Features
from bayle.ui.models import plain
from bayle.ui.notifications import Notifier
from bayle.ui.pages.mod_configs.presenter import ModConfigsPresenter
from bayle.ui.pages.mods.presenter import ModsPresenter
from bayle.ui.refresh import Refresher
from bayle.work.prompts import Confirm, Pick, Refusal

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
    def features(self) -> Features: ...
    def run_in_background(self, work, on_result) -> None: ...
    def follow_job(self, job_id: str, done) -> None: ...
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
        self._fingerprint: tuple[Any, str] = (
            None,
            "",
        )  # Seamless: the parameters' fingerprint and its file, read with it
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
        fp, regulation = self._fingerprint
        words = ModsPresenter()
        note = words.parameters({}, False, fp).fingerprint_note if fp else ""
        return self.presenter.seamless(s, words.fingerprint(fp, regulation), note)

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
        state = self.host.features.mod_configs.page(str(profile) if profile else "")
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
        service, profile = self.host.features.mod_configs, str(self._profile or "")

        def work():  # the file is read off the UI thread
            try:
                read = service.open(profile, path, seamless=node.kind == mod_configs.SEAMLESS)
                doc = None if setup_file else mod_configs.parse_doc(path.name, read.opened.text)
                opened = dataclasses.replace(read.opened, doc=doc)
                form = None
                if setup_file and node.kind != mod_configs.SEAMLESS and node.setup:
                    form = service.overhaul_form(profile)
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
            self._fingerprint = (read.fingerprint, read.regulation) if read is not None else (None, "")
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
        service, profile, path = self.host.features.mod_configs, str(self._profile or ""), opened.path

        def stat():
            try:
                return service.stamp(profile, path)
            except OperationError:  # no longer listed: the tree is read again soon
                return None

        self.host.run_in_background(stat, lambda now: self._set_disk_changed(now is not None and now != seen))

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
        profile, service = str(self._profile or ""), self.host.features.mod_configs
        if self._kind() == "text":
            kind, text, edits = "text", self._text, []
        else:
            edits = [(section or "", key, value) for (section, key), value in self._pending.items()]
            kind, text = ("seamless" if self._seamless is not None else "values"), ""
        self._query(
            lambda: service.save(profile, opened.path, opened.sha, kind, text=text, edits=edits),  # type: ignore[arg-type]
            lambda r: self._saved_file(opened, kind, r),
            self._save_failed,
        )

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
        if e.code == "password_empty":
            self._refuse(self.presenter.empty_password())
        elif e.code == "stale":
            self._refuse(self.presenter.stale(str(e.details.get("name", ""))))
        else:
            self._refuse(self.presenter.could_not_save(e.message))

    # ---- asking the engine (every call runs on the host's worker; the answer comes back on the UI thread)
    def _query(
        self,
        read: Callable[[], Any],
        then: Callable[[Any], None],
        failed: Callable[[OperationError], None] | None = None,
    ) -> None:
        """read() on the worker; then(value) on success, else failed(error) (default: _failed)."""

        def work():
            try:
                return read(), None
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
        """The engine said no: the code says why, never its words."""
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
                self.notifier.toast(self.presenter.nothing_to_change(list(e.details.get("unknown", []))))
            case "stale":
                self._refuse(self.presenter.stale(str(e.details.get("name", ""))))
            case "busy":
                self.notifier.toast(e.message, error=True)
            case _:
                self._refuse(self.presenter.could_not_save(e.message))

    def _ask(
        self,
        check: Callable[[], Any],
        words: Callable[[Any], Confirm | Refusal],
        start: Callable[[Any], Any],
        *,
        destructive: bool = False,
        guard: bool = False,
        confirmed: Callable[[], None] | None = None,
        done: Callable[[Any, Any], None] | None = None,
    ) -> None:
        """A plan: check() gives its facts, words(facts) is the question (or why not), and on yes start(facts) runs
        on the worker (the engine refuses it as stale when the facts changed meanwhile). A job id it returns is
        followed and done(facts, snapshot) runs when the job has ended; any other value is done(facts, value)."""

        def answered(plan: Any, ok: bool) -> None:
            if not ok:
                return
            if confirmed is not None:
                confirmed()

            def landed(got: Any) -> None:
                if isinstance(got, str):
                    self.host.follow_job(got, lambda snap: done(plan, snap) if done is not None else None)
                elif done is not None:
                    done(plan, got)

            self._query(lambda: start(plan), landed)

        def shown(plan: Any) -> None:
            question = words(plan)
            if isinstance(question, Refusal):
                self._refuse(question)
                return

            def ask() -> None:
                self.notifier.confirm(question, lambda ok: answered(plan, ok), destructive)

            self._guard(ask) if guard else ask()

        self._query(check, shown)

    def _ended_ok(self, snap: Any, said: str) -> bool:
        """A followed job has ended: said when it went well, else its failure in the code's words. True when it went well."""
        if snap is not None and snap.state == "done":
            self.notifier.toast(said)
            return True
        err = getattr(snap, "error", None)
        if err is not None:
            self._failed(OperationError(err.code, err.message, err.details))
        return False

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

    def _form(self) -> mod_configs.SetupValues:
        """The form's values as the engine takes them (the log check only when it was touched)."""
        assert self._ov is not None
        values = self._ov["values"]
        return mod_configs.SetupValues(
            values["natives"],
            values["files"],
            values["tables"],
            values["health"] if values.get("health_touched") else None,
        )

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
        setup, key, form = ov["setup"], self._node.key, self._form()
        service, profile = self.host.features.mod_configs, str(self._profile)
        self._query(
            lambda: service.save_setup(profile, setup["path"], setup["sha"], form=form),
            lambda r: self._setup_saved(key, r),
        )

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

        def ended(snap) -> None:
            self._ended_ok(snap, tr("Applied to the profiles using it."))
            self.refresh()

        service = self.host.features.mod_configs
        self._query(
            lambda: service.apply_setup(str(profile), overhaul_id),
            lambda job_id: self.host.follow_job(job_id, ended),
            failed,
        )

    def _save_overhaul_text(self, opened: mod_configs.Opened) -> None:
        service, profile, text = self.host.features.mod_configs, str(self._profile), self._text
        key = self._node.key if self._node else "overhaul"
        self._query(
            lambda: service.save_setup(profile, opened.path, opened.sha, text=text),
            lambda r: self._setup_saved(key, r),
        )

    def _start_new(self, mod: dict) -> None:
        """Show the proposal for a mod as a new setup (nothing is written until Save is confirmed)."""
        service, profile = self.host.features.mod_configs, str(self._profile)
        self._query(
            lambda: service.overhaul_form(profile, str(mod["folder"]), mod["name"], mod["id"] or ""),
            lambda form: self._show_new(form, mod),
        )

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
        mod, form, service = ov["mod"], self._form(), self.host.features.mod_configs
        folder, name, overhaul_id = str(ov["folder"]), mod["name"], mod["id"] or ""

        def ended(plan, snap) -> None:
            self._ended_ok(snap, tr("{label} is set up as an overhaul.").format(label=plan.label))
            self.refresh()

        self._ask(
            lambda: service.check_install_setup(str(profile), folder, name, form, overhaul_id),
            self.presenter.install_setup,
            lambda plan: service.install_setup(str(profile), folder, name, form, plan.stamp, overhaul_id),
            confirmed=lambda: setattr(self, "_want", "overhaul"),
            done=ended,
        )

    @Slot(str)
    def addOverhaulSetup(self, key: str) -> None:
        """Set a mod of the profile up as an overhaul: the mod of the node key (its button), else one picked from a
        list of the profile's mods."""
        profile = self._profile
        if profile is None or self.host.busy:
            self.notifier.toast(tr("Wait for the current job"), error=True)
            return
        node = next((n for n in self._nodes if n.key == key), None) if key else None
        service = self.host.features.mod_configs
        self._query(
            lambda: service.setup_candidates(str(profile)),
            lambda mods: self._choose_to_set_up([{"name": m.name, "id": m.id, "folder": m.folder} for m in mods], node),
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
        service = self.host.features.mod_configs

        def ended(plan, snap) -> None:
            self._ended_ok(snap, tr("Turned off the overhaul setup of {label}.").format(label=plan.label))
            self.refresh()

        self._ask(
            lambda: service.check_turn_off(str(profile)),
            self.presenter.turn_off,
            lambda plan: service.turn_off(str(profile), plan.stamp),
            destructive=True,
            done=ended,
        )

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
        service, profile, target = self.host.features.mod_configs, str(self._profile), node.target
        self._query(lambda: service.attach(profile, target, got), lambda _r: self._tied(node.key))

    @Slot(str)
    def detachFile(self, path: str) -> None:
        node = self._node
        if node is None or node.target is None:
            return
        self._opened = None
        service, profile, target = self.host.features.mod_configs, str(self._profile), node.target
        self._query(lambda: service.detach(profile, target, path), lambda _r: self._tied(node.key))

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

        def copy(text: str) -> None:
            QGuiApplication.clipboard().setText(text)
            self.notifier.toast(self.presenter.copied())

        service, profile, ini = self.host.features.mod_configs, str(self._profile), self._seamless.ini
        self._query(lambda: service.share(profile, ini), lambda text: copy(text))

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
            service, profile, ini = self.host.features.mod_configs, str(self._profile), self._seamless.ini

            def ended(snap) -> None:
                self._ended_ok(snap, tr("Saved {name}").format(name=got.name))

            self._query(
                lambda: service.export_share(profile, ini, got), lambda job_id: self.host.follow_job(job_id, ended)
            )

    def _take_shared(self, text: str) -> None:
        ini = self._seamless.ini if self._seamless else None
        if ini is None:
            return

        def pasted(_plan, n: int) -> None:
            self.notifier.toast(self.presenter.saved(n))
            self._reopen()

        service, profile = self.host.features.mod_configs, str(self._profile)
        self._ask(
            lambda: service.check_paste(profile, ini, text),
            lambda plan: self.presenter.paste(plan.changes, list(plan.unknown)),
            lambda plan: service.paste(profile, ini, text, plan.stamp),
            guard=True,
            done=pasted,
        )

    @Slot()
    def openFolder(self) -> None:
        if self._opened is not None:
            self.host.open_path(self._opened.path.parent)
