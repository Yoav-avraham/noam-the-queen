from __future__ import annotations

from enum import Enum, StrEnum
from typing import Any, ClassVar
from dataclasses import field, dataclass
from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class ErrorDefinition:
    """Shared metadata model for service error keys."""

    status: Any
    message: str | None = None
    context: str | None = None
    debug_details: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Error(RuntimeError):
    """Keyed runtime error resolved against service ERROR_DEFINITIONS."""

    key: StrEnum
    status: Any = field(init=False)
    message: str | None = field(init=False)
    context: str | None = field(init=False)
    debug_details: str | None = field(init=False)
    extra: dict[str, Any] = field(init=False)

    ERROR_DEFINITIONS: ClassVar[Mapping[StrEnum, ErrorDefinition]]

    def __post_init__(self) -> None:
        definition = self.ERROR_DEFINITIONS[self.key]
        object.__setattr__(self, "status", definition.status)
        object.__setattr__(self, "message", definition.message)
        object.__setattr__(self, "context", definition.context)
        object.__setattr__(self, "debug_details", definition.debug_details)
        object.__setattr__(self, "extra", dict(definition.extra))
        RuntimeError.__init__(self, str(self))

    @staticmethod
    def _format_status(status: Any) -> str:
        if isinstance(status, StrEnum):
            return status.value
        if isinstance(status, Enum):
            return status.name
        return str(status)

    def __str__(self) -> str:
        status = self._format_status(self.status)
        if self.message:
            return f"error raised with status {status}: {self.message}"
        return f"error raised with status {status}"
