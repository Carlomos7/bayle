"""The words for what the setup does with each file of a mod (the Files table of the Overhaul setup form and of the
Install mod dialog), by the kind of file (overhauls.basic.KINDS)."""

from roundtable_souls.ui.text import tr


def file_action_text(kind: str, action: str) -> str:
    if action == "merge":
        return (
            tr("Combine the parameters with the other mods")
            if kind == "regulation"
            else tr("Merge with the other mods")
        )
    if action == "whole":
        return tr("Copy whole, no merging")
    if action == "keep":
        return tr("Keep my copy when the mod updates")
    if action == "place":
        return tr("Place at a game path (merged there)")
    if action == "leave":
        return tr("Leave out")
    return tr("Copy into the mod's package") if kind == "game" else tr("Copy as it is")
