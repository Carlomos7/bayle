"""SemVer 2.0 versions: -rc.N pre-releases (old -beta.N still read), their order, and scripts/bump_version.py."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from roundtable_souls import __version__
from roundtable_souls.updates import feed

ROOT = Path(__file__).resolve().parents[2]


def test_rc_orders_between_the_last_stable_and_its_release():
    order = ["4.0.3", "4.1.0-beta.2", "4.1.0-rc.1", "4.1.0-rc.2", "4.1.0", "4.1.1"]
    keys = [feed.version_key(v) for v in order]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert feed.is_newer("4.1.0-rc.1", "4.0.3") and feed.is_newer("4.1.0", "4.1.0-rc.1")
    assert not feed.is_newer("4.1.0-rc.1", "4.1.0")


def test_rc_and_old_beta_are_pre_releases():
    assert feed.is_prerelease("4.1.0-rc.1") and feed.is_prerelease("4.0.0-beta.6") and not feed.is_prerelease("4.1.0")
    assert feed.parse_version("v4.1.0-rc.1") == "4.1.0-rc.1" and feed.parse_version("v4.0.0-beta.6") == "4.0.0-beta.6"


def _bump_version():
    spec = importlib.util.spec_from_file_location("bump_version", ROOT / "scripts" / "bump_version.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("v", ["4.1.0", "4.1.0-rc.1", "4.0.0-beta.6"])
def test_bump_version_accepts(v):
    assert re.fullmatch(_bump_version().VERSION, v)


@pytest.mark.parametrize("v", ["4.1", "v4.1.0", "4.1.0-rc1", "4.1.0-rc"])
def test_bump_version_rejects(v):
    assert not re.fullmatch(_bump_version().VERSION, v)


def test_bump_version_reads_both_version_files():
    for path, rx in _bump_version().FILES.items():
        m = rx.search(path.read_text(encoding="utf-8"))
        assert m and m.group(1) == __version__
