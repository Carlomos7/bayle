"""Why an operation did not complete, as data a client can act on (no Qt, no SystemExit). A code is what callers
branch on; the message is for the player and the log; details is anything else a client may show (JSON-able)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorInfo:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class OperationError(Exception):
    """An operation refused or failed for a reason the player can be told. code: a stable snake_case word."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, dict(details or {})

    @classmethod
    def from_info(cls, info: ErrorInfo | None) -> OperationError:
        """The error a finished job ended with, raised again where its value was awaited (details kept)."""
        if info is None:
            return cls("failed", "Failed.")
        return cls(info.code, info.message, info.details)

    @property
    def info(self) -> ErrorInfo:
        return ErrorInfo(self.code, self.message, self.details)


class Cancelled(OperationError):
    """The player stopped the operation."""

    def __init__(self, message: str = "Stopped.", details: dict[str, Any] | None = None):
        super().__init__("cancelled", message, details)


class Busy(OperationError):
    """Another operation (or the game) is in the way; try again when it ends."""

    def __init__(self, message: str = "Something else is running.", details: dict[str, Any] | None = None):
        super().__init__("busy", message, details)
