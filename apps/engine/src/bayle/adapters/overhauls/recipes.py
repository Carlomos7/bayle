"""Reading the overhaul configs: the shipped folder (data/overhauls) and the local one (overhauls/ in the launcher's
data folder), one TOML file per overhaul, validated as overhauls.config.OverhaulConfig. A local file with the same id
replaces the shipped one; a file that does not read or fit is left out and problems() says why."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from pydantic import ValidationError
from pydantic_core import ErrorDetails

from bayle.modules.overhauls.config import OverhaulConfig, schema
from bayle.resources import DATA_DIR

SHIPPED_DIR = DATA_DIR / "overhauls"


# ----------------------------------------------------------------------------- loading
_problems: list[str] = []
_origins: dict[str, Path] = {}  # config id -> the file the last load() took it from


def local_dir() -> Path | None:
    """The local folder (overhauls/ in the launcher's data folder), or None before the data folder is set."""
    from bayle.adapters.filesystem import data_folder

    try:
        return data_folder.data_root() / "overhauls"
    except RuntimeError:
        return None


def read(path: Path) -> OverhaulConfig:
    """One config file. Raises ValueError (tomllib's and Pydantic's errors are ValueErrors) or OSError."""
    return OverhaulConfig.model_validate(tomllib.loads(Path(path).read_text(encoding="utf-8")))


def load(game: str | None = None) -> list[OverhaulConfig]:
    """Every usable config, shipped then local (a local one replaces the shipped one with its id), for one game when
    given. Files that do not read or fit are left out; problems() lists them."""
    found: dict[str, OverhaulConfig] = {}
    _problems.clear()
    _origins.clear()
    for folder in (SHIPPED_DIR, local_dir()):
        if folder is None or not folder.is_dir():
            continue
        for f in sorted(folder.glob("*.toml")):
            try:
                cfg = read(f)
            except ValidationError as e:
                first = e.errors()[0]
                where = ".".join(str(x) for x in first["loc"])
                _problems.append(f"{f}: {where}: {first['msg']}" + _moved(first))
                continue
            except (OSError, ValueError) as e:
                _problems.append(f"{f}: {str(e).splitlines()[0] if str(e) else type(e).__name__}")
                continue
            found[cfg.id] = cfg
            _origins[cfg.id] = f
    return [c for c in found.values() if game is None or c.game == game]


# Keys an earlier version of the format had, and where they went (said when a file still uses one).
_MOVED = {
    "seamless": "since 3.20 a required mod is listed in the build's requires",
    "script_append": 'since 3.20 a script fragment is added with do = "hook" (append is fragment, refuse is markers)',
}


def _moved(error: ErrorDetails) -> str:
    hits = [str(x) for x in error["loc"]] + [str(error.get("input"))]
    for key, why in _MOVED.items():
        if any(h == key for h in hits) or f"'{key}'" in error.get("msg", ""):
            return f" ({key}: {why})"
    return ""


def origin(config_id: str) -> Path | None:
    """The file the last load() took the config with this id from."""
    return _origins.get(config_id)


def verified(config_id: str) -> bool:
    """A shipped config not replaced by a local one ("verified"); a local one is the player's ("your config, not
    verified")."""
    found = _origins.get(config_id)
    return found is not None and found.parent == SHIPPED_DIR


def problems() -> list[str]:
    """Why config files were left out by the last load()."""
    return list(_problems)


def schema_path() -> Path:
    return DATA_DIR / "schemas" / "overhaul.schema.json"


def write_schema() -> Path:
    """Regenerate data/schemas/overhaul.schema.json from the model (tests check they match)."""
    path = schema_path()
    path.write_text(json.dumps(schema(), indent=1) + "\n", encoding="utf-8", newline="\n")
    return path
