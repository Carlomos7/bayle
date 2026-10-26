"""Settings: the settings model and its rules (models), where the launcher's game folder is (layout), the Settings
page's service and the Locations actions (locations)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules.settings import (
        layout,
        locations,
        models,
        service,
    )

__all__ = [
    "layout",
    "locations",
    "models",
    "service",
]
