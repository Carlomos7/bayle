"""This machine: processes under a name (proc), dead game shells (processes), the desktop's open handler (desktop),
the install's facts (app_paths: frozen or not, the data and executable folders, Velopack and AppImage; identity: the
build's identity), the run and job logs and the jobs index (logging) and the UI-thread guard (threads). What the
launcher needs bound at startup (the data folder, the instance scope) the runtime sets."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.system import (
        app_paths,
        desktop,
        identity,
        logging,
        proc,
        processes,
        threads,
    )

__all__ = [
    "app_paths",
    "desktop",
    "identity",
    "logging",
    "proc",
    "processes",
    "threads",
]
