"""Debug only: DBG_FAKETRASH=1 replaces the Recycle Bin call with a plain delete."""

import os
import shutil
import time

if os.environ.get("DBG_FAKETRASH") == "1":
    from bayle.platform import trash

    def fake(path):
        shutil.rmtree(path)
        return {"kind": "gone", "item": "", "info": "", "original": str(path), "deleted": time.time()}

    trash._send_windows = fake
