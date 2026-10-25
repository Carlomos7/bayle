"""Save files: read-only checks (analyze), named repairs (fix, loading, vanilla, regulation, repair, nightreign_repair),
copies (transfer, library), backups and their retention (backups), what a worker forgets after a write (caches), the
report's shapes (models) and the Saves page's typed interface (service, saves_page). Parsing and decrypting the files
is adapters.saves."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules.saves import (
        analyze,
        backups,
        caches,
        fix,
        library,
        loading,
        models,
        regulation,
        repair,
        saves_page,
        service,
        transfer,
        vanilla,
    )

__all__ = [
    "analyze",
    "backups",
    "caches",
    "fix",
    "library",
    "loading",
    "models",
    "regulation",
    "repair",
    "saves_page",
    "service",
    "transfer",
    "vanilla",
]
