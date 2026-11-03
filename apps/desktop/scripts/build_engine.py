r"""Freeze the engine alone (no Qt, no Pillow, no Velopack) as a PyInstaller onedir folder for the Tauri shell to bundle
(docs/decisions/0016-identity-and-updater.md), then check it: the database migrations are inside, and the frozen
`--backend` prints its handshake on a temporary data folder and stops when stdin closes.

    uv run --project apps/engine python apps/desktop/scripts/build_engine.py

Output: apps/desktop/target/engine-dist/bayle-engine/ (bayle-engine.exe and _internal\), which tauri.conf.json bundles
as the `engine` resource folder.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESKTOP = HERE.parent
REPO = DESKTOP.parents[1]
ENGINE = REPO / "apps" / "engine"
OUT = DESKTOP / "target" / "engine-dist"
PYINSTALLER = (
    "pyinstaller==6.22.3"  # the version the Qt build resolves (apps/qt-desktop/uv.lock)
)


def freeze() -> Path:
    migrations = ENGINE / "src" / "bayle" / "adapters" / "persistence" / "migrations"
    cmd = [
        "uv",
        "run",
        "--project",
        str(ENGINE),
        "--extra",
        "api",
        "--with",
        PYINSTALLER,
        "pyinstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--noupx",
        "--name",
        "bayle-engine",
        "--collect-data",
        "bayle",
        "--collect-all",
        "py7zr",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "PIL",
        "--exclude-module",
        "PySide6",
        # Alembic loads the migration scripts by path, so they ship as files (--collect-data leaves .py files out)
        "--add-data",
        f"{migrations}{os.pathsep}bayle/adapters/persistence/migrations",
        "--hidden-import",
        "lupa.lua51",
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "pydantic_settings",
        "--distpath",
        str(OUT),
        "--workpath",
        str(OUT.parent / "engine-work"),
        "--specpath",
        str(OUT.parent),
        str(HERE / "engine_entry.py"),
    ]
    subprocess.run(cmd, check=True)
    folder = OUT / "bayle-engine"
    if not any(p.name == "env.py" for p in folder.rglob("migrations/env.py")):
        raise SystemExit(
            "build_engine: the database migrations did not make it into the build"
        )
    return folder


def smoke(folder: Path) -> None:
    exe = folder / ("bayle-engine.exe" if sys.platform == "win32" else "bayle-engine")
    with tempfile.TemporaryDirectory() as tmp:
        env = os.environ | {
            "BAYLE_DATA": str(Path(tmp) / "data"),
            "BAYLE_API_TOKEN": "smoke-test-token-0123456789",
        }
        for name in ("LOCALAPPDATA", "APPDATA", "USERPROFILE", "HOME", "XDG_DATA_HOME"):
            env[name] = str(Path(tmp) / name.lower())
            Path(env[name]).mkdir()
        proc = subprocess.Popen(
            [str(exe), "--backend"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        handshake = json.loads(proc.stdout.readline() or b"null")
        proc.stdin.close()
        code = proc.wait(timeout=30)
        if not handshake or code != 0:
            raise SystemExit(
                f"build_engine: the frozen engine failed its smoke test: {proc.stderr.read().decode()}"
            )
        print(f"build_engine: handshake {handshake}, exit {code}")


if __name__ == "__main__":
    built = freeze()
    smoke(built)
    size = sum(p.stat().st_size for p in built.rglob("*") if p.is_file())
    print(f"build_engine: {built} ({size / 1e6:.1f} MB)")
