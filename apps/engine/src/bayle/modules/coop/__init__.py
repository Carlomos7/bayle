"""Seamless Co-op's settings: finding a setup's ini and reading or writing it (ini), the difficulty scaling per
game (scaling), and sharing the whole file as JSON (share)."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # each module is imported where it is used, not here: importing the package does nothing
    from bayle.modules.coop import (
        ini,
        scaling,
        service,
        share,
    )

__all__ = [
    "ini",
    "scaling",
    "service",
    "share",
]
