"""Set the version in both projects (apps/engine and apps/qt-desktop: pyproject.toml, bayle.__version__, the uv.locks).

Releases are normally cut by release-please (CONTRIBUTING.md); this is the manual fallback.

uv run python scripts/bump_version.py 4.1.0-rc.1   a release candidate (Beta channel only; SemVer 2.0 pre-release)
uv run python scripts/bump_version.py 4.1.0        the stable release (both channels)

Old -beta.N and -alpha.N versions are still read and accepted.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # apps/qt-desktop
ENGINE = ROOT.parent / "engine"
VERSION = r"\d+\.\d+\.\d+(?:-(?:alpha|beta|rc)\.\d+)?"


def pep440(v: str) -> str:
    """The form uv.lock records: 4.6.0-rc.3 -> 4.6.0rc3, 4.0.0-beta.6 -> 4.0.0b6."""
    return re.sub(r"-(alpha|beta|rc)\.(\d+)", lambda m: {"alpha": "a", "beta": "b", "rc": "rc"}[m[1]] + m[2], v)


def lock_line(package: str) -> re.Pattern[str]:
    return re.compile(rf'^name = "{package}"\nversion = "(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)"$', re.M)


# (file, the line that holds the version, how the version is written there); the engine and the desktop program
# always carry the same version
_PYPROJECT = re.compile(rf'^version = "({VERSION})"$', re.M)
FILES = [
    (ROOT / "pyproject.toml", _PYPROJECT, str),
    (ENGINE / "pyproject.toml", _PYPROJECT, str),
    (
        ENGINE / "src" / "bayle" / "__init__.py",
        re.compile(rf'^__version__ = "({VERSION})"(?:  # x-release-please-version)?$', re.M),
        str,
    ),
    (ENGINE / "uv.lock", lock_line("bayle-engine"), pep440),
    (ROOT / "uv.lock", lock_line("bayle-engine"), pep440),
    (ROOT / "uv.lock", lock_line("bayle-qt"), pep440),
]


def main() -> int:
    if len(sys.argv) != 2 or not re.fullmatch(VERSION, sys.argv[1]):
        print(__doc__, file=sys.stderr)
        return 2
    new = sys.argv[1]
    for path, rx, written in FILES:  # read afresh each time: uv.lock appears twice
        text = path.read_text(encoding="utf-8")
        if not rx.search(text):
            print(f"no version line in {path}", file=sys.stderr)
            return 1
        path.write_text(
            rx.sub(lambda m, to=written(new): m.group(0).replace(m.group(1), to), text, count=1),
            encoding="utf-8",
            newline="\n",
        )
        print(f"{path.relative_to(ROOT.parent)}: {written(new)}")
    print(
        f'\nNext:\n  uv lock\n  git commit -am "Release {new}"\n  git tag -a v{new} -m "Bayle {new}"\n'
        "  git push && git push --tags\n\nThe Release workflow publishes a vX.Y.Z-rc.N tag to the Beta channel and a plain vX.Y.Z to both channels."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
