"""This machine: where things are (paths: the game, its saves, me3; data_folder: the launcher's own folder;
steam), what runs (proc, processes), the play session's steps (session), logging and the jobs index
(logging), single-instance and file locks (instance, filelock), files, trash, desktop, me3_info and
steam_shortcuts. The bottom layer: nothing here imports the launcher's other packages; what it needs from
them (the data folder, the build's instance scope) the app sets at startup."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.adapters.system import (
        app_paths,
        data_folder,
        desktop,
        identity,
        logging,
        proc,
        processes,
        threads,
    )

__all__ = [
    "app_paths",
    "data_folder",
    "desktop",
    "identity",
    "logging",
    "proc",
    "processes",
    "threads",
]
