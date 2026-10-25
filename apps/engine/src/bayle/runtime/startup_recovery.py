"""Finish or undo the operations a run left half done, once at every start (before the database opens).

It calls the existing recovery code and adds none of its own: the move-in and layout recoveries per ready game, and
the interrupted-install recovery of each game's remembered profile. A window that is already open owns these
journals, so nothing is touched while it holds the instance name.
"""

from __future__ import annotations

import os

from bayle.adapters.persistence.settings_file import load_settings
from bayle.adapters.system import logging as run_logging
from bayle.modules.games import catalog
from bayle.modules.games.locate import Locations
from bayle.modules.launch import play as core
from bayle.modules.mods import layout, move_in
from bayle.modules.mods import service as mod_service
from bayle.runtime import instance


def recover(covered: set[str] | None = None) -> list[str]:
    """covered, when given, gets each profile whose interrupted install was looked at (normcased), so a later step
    for the profile in use can skip it."""
    if instance.held(instance.WINDOW):
        return []
    settings = load_settings()
    said: list[str] = []
    ready = [g for g in catalog.GAMES if g.ready]
    for g in ready:
        loc = Locations.from_settings(settings, g)
        try:
            said += move_in.recover(loc)
        except Exception as e:  # as at the old start: nothing changed, it is tried again at the next one
            run_logging.log(f"warning: unfinished move into Bayle's folder not resolved ({g.key}): {e}")
    try:
        said += layout.finish_pending()
    except Exception as e:
        run_logging.log(f"warning: unfinished change of the profiles folders not resolved: {e}")
    for g in ready:
        profile = core.remembered_profile(settings, g)
        if profile:
            said += mod_service.recover_interrupted(profile, timeout=0.5)  # logs and swallows its own errors
            if covered is not None:
                covered.add(os.path.normcase(str(profile)))
    return said
