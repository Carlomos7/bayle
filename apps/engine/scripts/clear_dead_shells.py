"""Remove dead eldenring.exe shells from the command line (the launcher's Clear button does the same).

When Elden Ring exits it spawns a second copy of itself that dies at once, and on some machines that corpse stays in
the process list (see platform/processes.py). This asks for elevation (one UAC prompt) and terminates only processes
that are provably dead. Its job log goes to the launcher's data folder like any other job's.

    uv run python scripts/clear_dead_shells.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

from bayle.adapters.games import paths
from bayle.adapters.system import logging as run_logging
from bayle.adapters.system import processes
from bayle.adapters.system.logging import log
from bayle.modules.games import catalog
from bayle.runtime.bootstrap import use_data_folder


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="only report, do not kill")
    a = ap.parse_args()
    use_data_folder()
    game = catalog.ELDEN_RING
    run_logging.start_log("clear_dead_game_shells", game.key)
    if paths.exe_running(game.exe):
        log("note: a real game instance is running; it will not be touched")
    found, remaining = processes.clear(game.exe, a.dry_run)
    sys.exit(1 if remaining and not a.dry_run else 0)


if __name__ == "__main__":
    main()
