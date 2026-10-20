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
from roundtable_souls.ui.notifications import Notifier
from roundtable_souls.ui.pages.mod_configs.presenter import ModConfigsPresenter
from roundtable_souls.ui.pages.mods.presenter import Confirm, ModsPresenter, Refusal
from roundtable_souls.ui.text import tr

SEAMLESS_OWN = ("PASSWORD", "SCALING", "LANGUAGE")  # sections the Seamless panel shows itself


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
    def profiles(self) -> list[str]: ...
    def profile_index(self) -> int: ...
    def pick_profile(self, index: int) -> None: ...
    def pick_file(self, title: str, filters: str) -> Path | None:
        """Ask for a file to open; None when cancelled."""

    def save_file(self, title: str, name: str) -> Path | None:
        """Ask where to save a file; None when cancelled."""

    def open_path(self, path: Path) -> None: ...


class ModConfigsAdapter(QObject):
    changed = Signal()  # the tree, the profile
    fileChanged = Signal()  # the open file: what it shows (not each keystroke)
    dirtyChanged = Signal()

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
        self._node: mod_configs.ModNode | None = None
        self._opened: mod_configs.Opened | None = None
        self._seamless: mod_configs.Seamless | None = None
        self._pending: dict[tuple[str, str], str] = {}
        self._text = ""
        self._edit_text = False
        self._want: str = ""  # a mod to select once the tree is read (open_mod_configs)

    # ---- what QML reads
    title = Property(str, lambda self: self._words["title"], constant=True)
    words = Property(dict, lambda self: self._words, constant=True)
    profiles = Property(list, lambda self: self.host.profiles(), notify=changed)
    profileIndex = Property(int, lambda self: self.host.profile_index(), notify=changed)
    profileName = Property(str, lambda self: self._profile.stem if self._profile else "", notify=changed)
    hasProfile = Property(bool, lambda self: self._profile is not None, notify=changed)
    nodes = Property(list, lambda self: [self.presenter.node(n) for n in self._nodes], notify=changed)
    loading = Property(bool, lambda self: self._loading, notify=changed)
    selectedFile = Property(str, lambda self: str(self._opened.path) if self._opened else "", notify=fileChanged)
    fileKind = Property(str, lambda self: self._kind(), notify=fileChanged)
    crumb = Property(str, lambda self: self._crumb(), notify=fileChanged)
    sections = Property(list, lambda self: self._sections(), notify=fileChanged)
    seamless = Property(dict, lambda self: self._seamless_view(), notify=fileChanged)
    text = Property(str, lambda self: self._text, notify=fileChanged)
    editText = Property(bool, lambda self: self._edit_text, notify=fileChanged)
    dirty = Property(bool, lambda self: self._is_dirty(), notify=dirtyChanged)
    canAttach = Property(
        bool, lambda self: self._node is not None and self._node.target is not None, notify=fileChanged
    )
    selectedAttached = Property(bool, lambda self: self._attached(), notify=fileChanged)

    def _attached(self) -> bool:
        if self._node is None or self._opened is None:
            return False
        return any(f.path == self._opened.path and f.how == "attached" for f in self._node.files)

    def _kind(self) -> str:
        if self._opened is None:
            return ""
        if self._edit_text:
            return "text"
        if self._seamless is not None:
            return "seamless"
        if self._opened.doc is not None:
            return "form"
        return "markdown" if self._opened.path.suffix.lower() == ".md" else "text"

    def _crumb(self) -> str:
        if self._node is None:
            return ""
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

    def _is_dirty(self) -> bool:
        if self._opened is None:
            return False
        if self._edit_text or self._kind() in ("text", "markdown"):
            return self._text != self._opened.text
        return bool(self._pending)

    # ---- reading
    @Slot()
    def refresh(self) -> None:
        if self._loading:
            return
        profile = self.host.profile
        loc, settings = self.host.locations, self.host.settings
        self._loading = True
        self.changed.emit()

        def work():
            if profile is None or not Path(profile).is_file() or loc is None:
                return None, []
            return Path(profile), mod_configs.tree(profile, loc=loc, settings=settings)

        self.host.run_in_background(work, self._apply)

    def _apply(self, got) -> None:
        self._loading = False
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

    @Slot(int)
    def pickProfile(self, index: int) -> None:
        def go() -> None:
            self.host.pick_profile(index)
            self.refresh()

        self._guard(go)

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
        self._seamless = None
        try:
            self._opened = mod_configs.open_file(path)
            if node.kind == mod_configs.SEAMLESS:
                self._seamless = mod_configs.seamless(path)
        except Exception as e:  # too big, not text, gone: said, nothing open
            self._opened = None
            self._refuse(self.presenter.unreadable(path.name, str(e)))
        self._text = self._opened.text if self._opened else ""
        self.fileChanged.emit()
        self.dirtyChanged.emit()

    def _close(self) -> None:
        self._node = self._opened = self._seamless = None
        self._pending, self._text = {}, ""
        self.fileChanged.emit()
        self.dirtyChanged.emit()

    def _reopen(self) -> None:
        if self._node is not None and self._opened is not None:
            self._open(self._node, self._opened.path)

    def _refuse(self, r: Refusal) -> None:
        self.notifier.toast(f"{r.title}. {r.body}", error=True)

    # ---- editing
    @Slot(str, str, str)
    def setValue(self, section: str, key: str, value: str) -> None:
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
        if opened is None or not self._is_dirty():
            return
        try:
            if self._kind() in ("text", "markdown"):
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
