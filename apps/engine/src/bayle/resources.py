"""Files shipped inside the engine package: game definitions, schemas, item lists, the database migrations."""

from importlib.resources import files
from pathlib import Path

PACKAGE_DIR = Path(str(files("bayle")))
DATA_DIR = PACKAGE_DIR / "data"
MIGRATIONS_DIR = PACKAGE_DIR / "storage" / "migrations"  # Alembic loads these scripts by path, so builds ship them
