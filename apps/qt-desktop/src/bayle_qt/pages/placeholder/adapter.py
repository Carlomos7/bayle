"""The adapter of the page a game without support yet shows (Dark Souls III, Sekiro): what was found for the game on
this PC (its folder, its saves, its me3 profiles) and the two folders to open. Nothing on it can change a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bayle.game.locate import installed_dir
from bayle.platform.text import plural, tr
from PySide6.QtCore import Property, QObject, Signal, Slot

from bayle_qt.notifications import Notifier


class PlaceholderAdapter(QObject):
    changed = Signal()

    def __init__(self, host: Any, notifier: Notifier, parent: QObject | None = None):
        super().__init__(parent)
        self.host = host
        self.notifier = notifier
        self._info: dict = self._read()

    def _read(self) -> dict:
        g = self.host.game
        if g is None:  # the self-test's host has no game
            return {
                "title": "",
                "intro": "",
                "foundTitle": "",
                "rows": [],
                "gameFolder": "",
                "savesFolder": "",
                "gameButton": "",
                "savesButton": "",
            }
        loc = self.host.locations
        game_dir = installed_dir(g)
        try:
            saves = loc.save_files()
            profiles = loc.me3_profiles()
        except OSError:
            saves, profiles = [], []
        n = len(saves)
        rows = [
            {"label": tr("Game"), "value": str(game_dir) if game_dir else tr("Not found in any Steam library.")},
            {
                "label": tr("Saves"),
                "value": (plural("{n} save file", "{n} save files", n).format(n=n) + f" · {saves[0].parent}")
                if saves
                else tr("None found."),
            },
            {
                "label": tr("me3 profiles"),
                "value": ", ".join(p.name for p in profiles) if profiles else tr("None made for this game yet."),
            },
        ]
        return {
            "title": g.name,
            "intro": tr(
                "Support for {game} is coming. Launch, mods and saves stay off on this game until then, so nothing "
                "here can change its files. Pick Elden Ring or Nightreign at the top to use the launcher."
            ).format(game=g.name),
            "foundTitle": tr("Found on this PC"),
            "rows": rows,
            "gameFolder": str(game_dir) if game_dir else "",
            "savesFolder": str(saves[0].parent) if saves else "",
            "gameButton": tr("Game folder"),
            "savesButton": tr("Saves folder"),
        }

    title = Property(str, lambda self: self._info.get("title") or tr("Not supported yet"), notify=changed)
    placeholder = Property(dict, lambda self: self._info, notify=changed)

    @Slot()
    def refresh(self) -> None:
        self._info = self._read()
        self.changed.emit()

    @Slot(str)
    def openFolder(self, path: str) -> None:
        if path:
            self.host.open_path(Path(path))
