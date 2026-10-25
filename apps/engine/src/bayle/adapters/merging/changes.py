"""What a merge reports: the result, which parts each mod changed, and where changes met."""

from __future__ import annotations

from dataclasses import dataclass, field

REMOVED = object()  # a part a mod's copy leaves out


@dataclass
class Result:
    data: bytes
    changed: dict[str, list[str]] = field(default_factory=dict)  # inner path -> the mods that changed it
    clashes: dict[str, list[str]] = field(default_factory=dict)  # inner path -> mods whose changes met; the last won
    merged: bool = True  # False: the file could not be merged and the last mod's copy is used whole
    removed: dict[str, list[str]] = field(default_factory=dict)  # inner path -> mods whose copy left it out
    notes: dict[str, list[str]] = field(default_factory=dict)  # inner path -> what a rule decided there, and why
    # inner path -> what the game will make of the result there that the player should know (game-level checks)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    # archive path ("" = the file merged) -> mod -> how many of the game's inner files its copy lacks
    omissions: dict[str, dict[str, int]] = field(default_factory=dict)

    def take(self, other: Result) -> None:
        """Add what a merge inside one of this result's inner files reports (all but its data)."""
        self.changed.update(other.changed)
        self.clashes.update(other.clashes)
        self.removed.update(other.removed)
        self.notes.update(other.notes)
        for path, said in other.warnings.items():
            self.warnings.setdefault(path, []).extend(said)
        self.omissions.update(other.omissions)

    def omission_notices(self, name: str) -> list[tuple[str, str]]:
        """(archive path, words) per mod whose copy of an archive lacks inner files the game has: "Sekiro Animations
        lacks 58 animations the current game uses (they won't play)". name: the merged file's game path."""
        from bayle.adapters.games import knowledge

        out = []
        for where, mods in sorted(self.omissions.items()):
            path = f"{name}/{where}" if where else name
            said = knowledge.binder_omission(knowledge.binder_kind(where or name))
            for mod, n in mods.items():
                if said is not None:
                    what = f"{n} {said.one if n == 1 else said.many} the current game uses"
                    out.append((path, f"{mod} lacks {what}" + (f" ({said.effect})" if said.effect else "")))
                else:
                    files = "inner file" if n == 1 else "inner files"
                    out.append((path, f"{mod} lacks {n} {files} the current game has (left out of the result)"))
        return out

    def summary(self) -> str:
        n = len(self.changed)
        text = f"{n} part{'s' if n != 1 else ''} changed"
        if self.clashes:
            text += f", {len(self.clashes)} changed by more than one mod (the later one's used)"
        return text
