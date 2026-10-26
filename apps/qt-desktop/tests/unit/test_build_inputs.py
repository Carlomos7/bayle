"""scripts/build.py is never run in tests (no PyInstaller build here), so its inputs are checked statically: every
path it hands PyInstaller exists, the entry module imports, and the version and vpk pins agree."""

import importlib.util
import tomllib
from pathlib import Path

import pytest
from bayle import __version__

from support import repo_root

ROOT = repo_root()


@pytest.fixture(scope="module")
def build():
    spec = importlib.util.spec_from_file_location("build_script", ROOT / "scripts" / "build.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def pyinstaller_args(build, monkeypatch, tmp_path):
    """The command line build.pyinstaller() would run, with nothing run and nothing written outside tmp_path."""
    seen = []
    monkeypatch.setattr(build, "run", lambda *args, **kw: seen.append([str(a) for a in args]))
    monkeypatch.setattr(build, "check_identity", lambda *a: None)
    monkeypatch.setattr(build, "check_migrations", lambda *a: None)
    monkeypatch.setattr(build, "BUILD", tmp_path / "build")
    build.pyinstaller("python", None)
    return seen[0]


def values(args, flag):
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


def test_build_hands_pyinstaller_paths_that_exist(build, pyinstaller_args):
    for add in values(pyinstaller_args, "--add-data"):
        assert Path(add.rsplit(build.os.pathsep, 1)[0]).exists(), add
    for flag in ("--icon", "--paths", "--additional-hooks-dir"):
        for path in values(pyinstaller_args, flag):
            assert Path(path).exists(), (flag, path)
    assert Path(pyinstaller_args[-1]) == ROOT / "scripts" / "entry.py" and Path(pyinstaller_args[-1]).is_file()


def test_build_packs_both_packages_and_their_data(build, pyinstaller_args):
    assert {"bayle", "bayle_qt"} <= set(values(pyinstaller_args, "--collect-data"))
    pkg = build.PKG
    for needed in ("qml/Main.qml", "assets/icon.ico", "self-test.json", "updater/data/release-signing.pub"):
        assert (pkg / needed).is_file(), needed
    assert (build.engine_package() / "resources").is_dir() and (build.MIGRATIONS / "env.py").is_file()
    assert (build.MIGRATIONS / "versions").is_dir()


def test_the_frozen_entry_calls_the_desktop_main():
    text = (ROOT / "scripts" / "entry.py").read_text(encoding="utf-8")
    assert "from bayle_qt.entry import main" in text
    from bayle_qt.entry import main

    assert callable(main)


def test_hooks_read_the_desktop_self_test_list():
    hook = (ROOT / "scripts" / "pyinstaller_hooks" / "hook-PySide6.QtQml.py").read_text(encoding="utf-8")
    assert '"bayle_qt" / "self-test.json"' in hook and (ROOT / "src" / "bayle_qt" / "self-test.json").is_file()


def test_versions_and_vpk_pin_agree(build):
    mine = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    engine = tomllib.loads((ROOT.parent / "engine" / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert mine["version"] == engine["version"] == __version__
    assert f"velopack=={build.VPK_VERSION}" in mine["dependencies"]
