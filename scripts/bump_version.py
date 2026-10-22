"""Set the version in pyproject.toml, the package and the desktop/api manifests, ready to commit and tag.

Releases are normally cut by release-please (CONTRIBUTING.md); this is the manual fallback.

uv run python scripts/bump_version.py 4.1.0-rc.1   a release candidate (Beta channel only; SemVer 2.0 pre-release)
uv run python scripts/bump_version.py 4.1.0        the stable release (both channels)

Old -beta.N and -alpha.N versions are still read and accepted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?"
JSON_VERSION = re.compile(rf'^  "version": "({VERSION})",?$', re.M)
FILES = {
    ROOT / "pyproject.toml": re.compile(rf'^version = "({VERSION})"$', re.M),
    ROOT / "src" / "bayle" / "__init__.py": re.compile(
        rf'^__version__ = "({VERSION})"(?:  # x-release-please-version)?$', re.M
    ),
    # npm and Cargo take the same SemVer; the first match is the package's own version
    ROOT / "package.json": JSON_VERSION,
    ROOT / "apps" / "desktop" / "package.json": JSON_VERSION,
    ROOT / "packages" / "api" / "package.json": JSON_VERSION,
    ROOT / "apps" / "desktop" / "src-tauri" / "tauri.conf.json": JSON_VERSION,
    ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml": re.compile(rf'^version = "({VERSION})"$', re.M),
    ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.lock": re.compile(
        rf'^name = "bayle-desktop"\nversion = "({VERSION})"$', re.M
    ),
}


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(VERSION, sys.argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    new = sys.argv[1]
    for path, rx in FILES.items():
        text = path.read_text(encoding="utf-8")
        if not rx.search(text):
            print(f"no version line in {path}", file=sys.stderr)
            return 1
        path.write_text(
            rx.sub(lambda m: m.group(0).replace(m.group(1), new), text, count=1), encoding="utf-8", newline="\n"
        )
        print(f"{path.relative_to(ROOT)}: {new}")
    print(
        f'\nNext:\n  uv lock\n  git commit -am "Release {new}"\n  git tag -a v{new} -m "Roundtable Souls {new}"\n'
        "  git push && git push --tags\n\nThe Release workflow publishes a vX.Y.Z-rc.N tag to the Beta channel and a plain vX.Y.Z to both channels."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
