"""Write the API contract offline (no server, no token). --check compares to the committed snapshot instead.
Run: uv run python scripts/export_openapi.py [--check]"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bayle.api.app import create_app
from bayle.api.settings import ApiSettings

SNAPSHOT = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"


def render() -> str:
    spec = create_app(ApiSettings(token="x" * 16)).openapi()
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        if SNAPSHOT.exists() and SNAPSHOT.read_text(encoding="utf-8") == text:
            return 0
        print(f"{SNAPSHOT} is stale: run scripts/export_openapi.py and commit it.", file=sys.stderr)
        return 1
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
