"""What the Mods page reads about one profile, in one pass and without writing: the page facts, the Load order scan,
the rebuild tool to ask about, the last rebuild that can be taken back, the overhaul state, and whether Seamless Co-op
also sits in the game folder. Run it off the UI thread. Finishing an interrupted change (a write) is not part of it:
that is mods.recover on the session. The presenter (views.mods) turns the result into what the page shows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bayle.game.locate import Locations
from bayle.mods import conflicts as mod_overview
from bayle.mods import order as mod_order
from bayle.mods import profile_edit
from bayle.services import coop as coop_service
from bayle.services import mods as mod_service
from bayle.services import play as play_service
from bayle.services import profile_mods


@dataclass(frozen=True)
class PageRead:
    facts: profile_mods.PageFacts
    scan: dict
    tool: Any  # the rebuild tool to ask about (profile_mods.tool_to_offer), or None
    rebuild_undo: dict | None  # the newest rebuild's job record that can still be taken back
    overhaul_on: bool
    overhaul: dict | None  # mods.profile_overhaul
    leftovers: bool
    seamless: str  # "" | "move" | "cleanup": Seamless Co-op also in the game folder
    rename_code: str  # why the profile can't be renamed or copied whatever is running (a DELETE_* code), or ""


def launch_for(loc: Locations, profile: str, kind: str = "me3", source: str = ""):
    """The setup the page is about, as the rules about deleting and Seamless Co-op read it."""
    return play_service.LaunchProfile(kind, profile, source=source or None, loc=loc)


def read(profile, *, loc: Locations, launch=None, settings=None) -> PageRead:
    prof = Path(profile)
    try:
        seamless = coop_service.game_folder_seamless(launch) if launch is not None else None
    except Exception:  # a game folder that cannot be read: nothing to offer
        seamless = None
    facts = profile_mods.page_facts(prof, loc=loc, settings=settings)
    try:
        scan = mod_overview.overview(prof, loc=loc)
    except Exception as e:  # a broken profile or record: the page shows what it has
        scan = {"profile": str(prof), "scan": {"error": str(e)}}
    tool = profile_mods.tool_to_offer(prof, loc.game, loc=loc)
    try:
        undo = profile_mods.last_rebuild_undo(prof)
    except Exception:
        undo = None
    try:
        on = mod_service.overhaul_preview_on(loc)
        has = mod_service.profile_overhaul(prof, loc=loc) if on else None
        left = bool(mod_service.overhaul_leftovers(prof, loc=loc)) if on else False
    except Exception:  # an overhaul config or record that does not read: no overhaul entries
        on, has, left = False, None, False
    block = profile_mods.delete_refusal(launch, False, loc=loc) if launch is not None else None
    return PageRead(facts, scan, tool, undo, on, has, left, seamless.kind if seamless is not None else "", block or "")


def folder_name(profile, entry: dict) -> str:
    """The entry's folder name (a package's folder, a DLL's parent): where the Rename dialog starts; "" without a path."""
    if not entry.get("path"):
        return ""
    folder = profile_edit.resolve(Path(profile), entry["path"])
    return (folder if entry["kind"] == "package" else folder.parent).name


def drop_reasons(profile, kind: str, index: int, *, loc: Locations) -> dict[int, str]:
    """For a drag of entry `index`: why dropping it at each position (0-based among its kind as shown) would be refused,
    "" where it is allowed. The same rules a move applies (mods.order.move), over the profile text read once."""
    prof = Path(profile)
    text = profile_edit.read_text(prof)
    target = mod_order.target(prof, loc)
    shown = mod_order.display_order(prof, text, kind)
    out: dict[int, str] = {}
    for to in range(len(shown)):
        try:
            plan = mod_order.move(prof, text, kind, index, to, target)
            out[to] = plan.problem if plan.text is None and plan.problem else ""
        except Exception as e:
            out[to] = str(e)
    return out
