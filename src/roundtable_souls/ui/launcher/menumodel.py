"""A menu as a list model for QML (technical specification §8.10, Shell): the rows of one menu, with a nested model for
a submenu. The shell recomputes the menus whenever its state changes; `update` writes the new values into the rows in
place (`dataChanged`) when the menu's shape is the same, so an open menu is never rebuilt under the user's hand."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, QObject, QPersistentModelIndex, Qt

from roundtable_souls.ui.launcher.menu import Item

ROLES = ("itemId", "label", "enabled", "checked", "shortcut", "icon", "kind", "sub")


def _kind(item: Item) -> str:
    return "separator" if item.separator else "submenu" if item.items else "entry"


class MenuModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []
        self._subs: list[MenuModel | None] = []

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._rows)

    def roleNames(self) -> dict[int, QByteArray]:
        return {Qt.ItemDataRole.UserRole + 1 + i: QByteArray(r.encode()) for i, r in enumerate(ROLES)}

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        i, k = index.row(), role - Qt.ItemDataRole.UserRole - 1
        if not index.isValid() or not 0 <= i < len(self._rows) or not 0 <= k < len(ROLES):
            return None
        return self._subs[i] if ROLES[k] == "sub" else self._rows[i].get(ROLES[k])

    @staticmethod
    def _row(item: Item) -> dict[str, Any]:
        return {
            "itemId": item.id,
            "label": item.label,
            "enabled": item.enabled,
            "checked": item.checked,
            "shortcut": item.shortcut,
            "icon": item.icon,
            "kind": _kind(item),
        }

    def update(self, items: tuple[Item, ...]) -> None:
        rows = [self._row(i) for i in items]
        shape = [(r["itemId"], r["kind"]) for r in rows]
        if shape == [(r["itemId"], r["kind"]) for r in self._rows]:
            for i, row in enumerate(rows):
                if row != self._rows[i]:
                    self._rows[i] = row
                    self.dataChanged.emit(self.index(i), self.index(i))
                sub = self._subs[i]
                if sub is not None:
                    sub.update(items[i].items)
            return
        self.beginResetModel()
        self._rows = rows
        self._subs = []
        for item in items:
            sub = None
            if item.items:
                sub = MenuModel(self)
                sub.update(item.items)
            self._subs.append(sub)
        self.endResetModel()
