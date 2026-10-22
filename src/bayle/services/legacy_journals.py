"""What the older build would have done on its own start: finish or undo the operations it left half done.

The app-data migration (storage.datamigrations) calls recover() before it backs anything up, because these recoveries
change user files and no metadata backup can undo them. It calls the existing recovery code and adds none of its own:
the move-in and layout recoveries the shell ran at start (session.shell.state.reload_profiles, per ready game) and
the interrupted-install recovery of the remembered profile (session.startup). Delete it when the floor rises past
the builds that wrote these journals. (The plan puts it beside the runner; the layering needs it above mods.)
"""

from __future__ import annotations

from bayle.config.settings import load_settings
from bayle.game import catalog
from bayle.game.locate import Locations
from bayle.mods import layout, move_in
from bayle.platform import logging as run_logging
from bayle.services import mods as mod_service
from bayle.services import play as core


def recover() -> list[str]:
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
    return said
