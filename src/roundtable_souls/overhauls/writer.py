"""Writing an overhaul config to the launcher's local overhauls/ folder (the Overhaul setup form's Save): the config
as TOML text, which is checked to read back as the same config before anything is written, and a file the player
changed since it was read is never overwritten.

The text keeps what the config sets (its fields left at their defaults are left out); comments of a hand-written
file are not kept, which is why a file changed since it was read is refused rather than replaced.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tomllib
from pathlib import Path

from roundtable_souls.overhauls.config import SHIPPED_DIR, OverhaulConfig, local_dir, read

HEADER = (
    "# Made with Roundtable Souls' Overhaul setup: your config, not verified.\n"
    "# Format: docs/Overhaul configs.md; schema: data/schemas/overhaul.schema.json.\n"
)
_BARE = re.compile(r"[A-Za-z0-9_-]+")


class WriteRefused(ValueError):
    """Why the config was not written (in plain words)."""


def _key(k: str) -> str:
    return k if _BARE.fullmatch(k) else json.dumps(k, ensure_ascii=False)


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # JSON's escapes are valid in a TOML basic string
    if isinstance(v, list):
        return "[" + ", ".join(_value(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(x)}" for k, x in v.items()) + " }"
    raise WriteRefused(f"a value of type {type(v).__name__} can't be written to TOML")


def _tables(v) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v)


def _emit(path: list[str], d: dict, out: list[str]) -> None:
    for k, v in d.items():
        if not isinstance(v, dict) and not _tables(v):
            out.append(f"{_key(k)} = {_value(v)}")
    for k, v in d.items():
        name = ".".join(_key(p) for p in [*path, k])
        if isinstance(v, dict):
            out += ["", f"[{name}]"]
            _emit([*path, k], v, out)
        elif _tables(v):
            for item in v:
                out += ["", f"[[{name}]]"]
                _emit([*path, k], item, out)


def render(config: OverhaulConfig) -> str:
    """The config as TOML text. Raises WriteRefused when the text would not read back as the same config."""
    out: list[str] = []
    _emit([], config.model_dump(by_alias=True, exclude_unset=True, exclude_none=True), out)
    text = HEADER + "\n" + "\n".join(out) + "\n"
    try:
        back = OverhaulConfig.model_validate(tomllib.loads(text))
    except ValueError as e:
        raise WriteRefused(f"the config would not read back: {e}") from e
    if back.model_dump() != config.model_dump():
        raise WriteRefused("the config would not read back as it is")
    return text


def sha256_of(path: Path) -> str | None:
    """The sha256 of a file as read (what save_local's expect compares), None when there is none."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _shipped_ids() -> set[str]:
    ids = set()
    for f in SHIPPED_DIR.glob("*.toml"):
        try:
            ids.add(read(f).id)
        except OSError, ValueError:
            continue
    return ids


def save_local(config: OverhaulConfig, *, expect: str | None, path: Path | None = None) -> Path:
    """Write the config to the local folder (path: the file it was read from, else <id>.toml there). expect: the
    sha256 of the file as it was read (sha256_of), None when it is new; a file that is not that one any more is not
    overwritten. The file it replaces is kept as <name>.bak. Raises WriteRefused."""
    if config.basic is not None and config.id in _shipped_ids():
        raise WriteRefused(f"{config.label} already has a verified setup that comes with the launcher.")
    if not config.id or Path(config.id).name != config.id or config.id in (".", ".."):
        raise WriteRefused(f"{config.id!r} can't be used as a file name.")
    if path is None:
        folder = local_dir()
        if folder is None:
            raise WriteRefused("The launcher's data folder is not set.")
        path = folder / f"{config.id}.toml"
    path = Path(path)
    text = render(config)
    if sha256_of(path) != expect:
        raise WriteRefused(
            f"{path.name} changed since it was read (or was made meanwhile); reload it and make your changes again."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8", newline="\n")
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    os.replace(temp, path)
    return path
