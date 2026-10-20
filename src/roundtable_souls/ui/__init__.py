"""The window (PySide6 with Qt Quick), the only package that imports Qt: launcher (the shell: its host, adapter and
launch flow), pages (each page's adapter and presenter; the QML is in qml), find (the editor's find bar) and jobs (the
window's side of services/jobs.py)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from roundtable_souls.ui import find, jobs, launcher, pages

__all__ = ["find", "jobs", "launcher", "pages"]
