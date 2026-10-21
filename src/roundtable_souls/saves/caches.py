"""Forgetting what a process has remembered about the game and the installed mods: the item names of the mods, and the
item IDs the game's regulation.bin defines. A worker process (platform/cpu.py) keeps these between tasks and is told
to forget with cpu.invalidate(kind) when the main process learns they changed."""

from __future__ import annotations

KINDS = ("item_names", "game_items", "all")


def forget(kind: str = "all") -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown cache {kind!r}")
    from roundtable_souls.saves import analyze, item_names

    if kind in ("item_names", "all"):
        item_names._CACHE = None
    if kind in ("game_items", "all"):
        analyze._GAME_IDS = None
