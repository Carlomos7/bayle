"""Import every module of the engine (bayle) and fail if any needs Qt or bayle_qt. Run in the engine's environment,
which has neither PySide6 nor bayle_qt; this file only imports bayle."""

import importlib
import pkgutil
import sys

import bayle

failed = []
for m in pkgutil.walk_packages(bayle.__path__, "bayle."):
    if m.name == "bayle.__main__":  # runs the command line on import
        continue
    try:
        importlib.import_module(m.name)
    except ModuleNotFoundError as e:
        if m.name.startswith("bayle.api") and e.name in ("fastapi", "uvicorn", "pydantic_settings", "starlette"):
            continue  # the api extra is not installed in this job
        failed.append(f"{m.name}: {e!r}")
    except Exception as e:
        failed.append(f"{m.name}: {e!r}")
if any(n.split(".")[0] in ("PySide6", "bayle_qt") for n in sys.modules):
    failed.append("PySide6 or bayle_qt was imported")
if failed:
    sys.exit("\n".join(failed))
print("headless import smoke ok")
