"""The app-data version marker (settings, records, journals; the database stays Alembic's).

Moves to adapters/persistence/datamigrations/ in Phase 3a of the engine refactor.
"""

from bayle.storage.datamigrations.runner import CURRENT_VERSION, MigrationError, migrate, write_json

__all__ = ["CURRENT_VERSION", "MigrationError", "migrate", "write_json"]
