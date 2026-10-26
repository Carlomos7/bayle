"""Opening a folder, file or URL with the desktop's default handler."""

import os
import subprocess
import sys


def open_path(target) -> None:
    """Open a folder, file or URL with the desktop's default handler."""
    target = str(target)
    if sys.platform == "win32":  # checked directly (no IS_WINDOWS flag): pyright narrows only this form
        os.startfile(target)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", target])
    else:
        subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
