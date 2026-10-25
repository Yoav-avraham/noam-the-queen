"""Domain layer: core value types and the service error contract."""

from __future__ import annotations

from .types import (
    SessionStatus,
    TranscriptSegment,
    AggregatedTranscript,
)
from .errors import (
    ERROR_DEFINITIONS,
    ErrorKey,
    RestApiError,
    WebSocketCloseCode,
    http_status_for,
    ws_close_code_for,
    get_error_definition,
)

__all__ = [
    "ERROR_DEFINITIONS",
    "AggregatedTranscript",
    "ErrorKey",
    "RestApiError",
    "SessionStatus",
    "TranscriptSegment",
    "WebSocketCloseCode",
    "get_error_definition",
    "http_status_for",
    "ws_close_code_for",
]
