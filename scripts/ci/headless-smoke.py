"""Import every module outside ui/ and fail if any needs Qt. Run in an environment synced without the qt extra."""

import importlib
import pkgutil
import sys

import bayle

failed = []
for m in pkgutil.walk_packages(bayle.__path__, "bayle."):
    if m.name.startswith("bayle.ui") or m.name == "bayle.__main__":
        continue
    try:
        importlib.import_module(m.name)
    except ModuleNotFoundError as e:
        if m.name.startswith("bayle.api") and e.name in ("fastapi", "uvicorn", "pydantic_settings", "starlette"):
            continue  # the api extra is not installed in this job
        failed.append(f"{m.name}: {e!r}")
    except Exception as e:
        failed.append(f"{m.name}: {e!r}")
if "PySide6" in sys.modules:
    failed.append("PySide6 was imported")
if failed:
    sys.exit("\n".join(failed))
print("headless import smoke ok")
