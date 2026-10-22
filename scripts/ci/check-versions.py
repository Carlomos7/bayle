"""Fail unless every file bump_version.py manages carries the same version (release-please bumps them together)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bump_version import FILES, ROOT  # noqa: E402  # pyright: ignore[reportMissingImports]


def main() -> int:
    found: dict[str, str] = {}
    for path, rx in FILES.items():
        m = rx.search(path.read_text(encoding="utf-8"))
        found[str(path.relative_to(ROOT)).replace("\\", "/")] = m.group(1) if m else "<missing>"
    for name, version in found.items():
        print(f"{name}: {version}")
    if len(set(found.values())) > 1:
        print("versions disagree: run scripts/bump_version.py <version>", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
