"""The version the window shows must be the version the package is built as."""

import tomllib

import bayle
from support import repo_root


def test_package_version_matches_pyproject():
    pyproject = repo_root() / "pyproject.toml"
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    assert project["version"] == bayle.__version__
