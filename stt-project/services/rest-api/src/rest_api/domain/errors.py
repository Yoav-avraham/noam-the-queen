"""Error contract for the rest API service.

Follows the shared keyed-error pattern from stt_common.errors. Each error key
maps to an ErrorDefinition whose ``status`` is the HTTP status code and whose
``extra["ws_close_code"]`` is the WebSocket close code used when the failure
occurs on the streaming endpoint.
"""

from __future__ import annotations

from enum import StrEnum
from http import HTTPStatus
from typing import ClassVar
from dataclasses import dataclass

from stt_common.errors import Error as CommonError
from stt_common.errors import ErrorDefinition


class WebSocketCloseCode:
    """WebSocket close codes used by the streaming endpoint.

    1000/1008/1009/1011 are RFC 6455 codes; the 44xx values are
    application-specific codes (the 4000-4999 range is reserved for apps).
    """

    NORMAL = 1000
    POLICY_VIOLATION = 1008
    MESSAGE_TOO_BIG = 1009
    INTERNAL_ERROR = 1011
    BAD_METADATA = 4400
    UNAUTHORIZED = 4401
    NOT_FOUND = 4404
    CONFLICT = 4409
    PAYLOAD_TOO_LARGE = 4413
    UPSTREAM_FAILURE = 4502
    TIMEOUT = 4504


class ErrorKey(StrEnum):
    """Stable error keys for rest API request and stream failures."""

    SESSION_NOT_FOUND = "session_not_found"
    SESSION_NOT_OPEN = "session_not_open"
    INVALID_TOKEN = "invalid_token"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_USER_MISMATCH = "token_user_mismatch"
    INVALID_METADATA = "invalid_metadata"
    METADATA_MISMATCH = "metadata_mismatch"
    EMPTY_UPLOAD = "empty_upload"
    UPLOAD_TOO_LARGE = "upload_too_large"
    STORAGE_FAILURE = "storage_failure"
    UPSTREAM_STREAM_FAILURE = "upstream_stream_failure"
    TRANSCRIPTION_TIMEOUT = "transcription_timeout"
    INTERNAL = "internal"


ERROR_DEFINITIONS: dict[ErrorKey, ErrorDefinition] = {
    ErrorKey.SESSION_NOT_FOUND: ErrorDefinition(
        status=HTTPStatus.NOT_FOUND,
        message="session not found",
        context="rest.session",
        extra={"ws_close_code": WebSocketCloseCode.NOT_FOUND},
    ),
    ErrorKey.SESSION_NOT_OPEN: ErrorDefinition(
        status=HTTPStatus.CONFLICT,
        message="session is not open for streaming",
        context="rest.session",
        extra={"ws_close_code": WebSocketCloseCode.CONFLICT},
    ),
    ErrorKey.INVALID_TOKEN: ErrorDefinition(
        status=HTTPStatus.UNAUTHORIZED,
        message="session token is invalid",
        context="rest.auth",
        extra={"ws_close_code": WebSocketCloseCode.UNAUTHORIZED},
    ),
    ErrorKey.TOKEN_EXPIRED: ErrorDefinition(
        status=HTTPStatus.UNAUTHORIZED,
        message="session token has expired",
        context="rest.auth",
        extra={"ws_close_code": WebSocketCloseCode.UNAUTHORIZED},
    ),
    ErrorKey.TOKEN_USER_MISMATCH: ErrorDefinition(
        status=HTTPStatus.UNAUTHORIZED,
        message="session token does not match the requested user",
        context="rest.auth",
        extra={"ws_close_code": WebSocketCloseCode.UNAUTHORIZED},
    ),
    ErrorKey.INVALID_METADATA: ErrorDefinition(
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        message="session metadata is invalid",
        context="rest.session",
        extra={"ws_close_code": WebSocketCloseCode.BAD_METADATA},
    ),
    ErrorKey.METADATA_MISMATCH: ErrorDefinition(
        status=HTTPStatus.BAD_REQUEST,
        message="streamed metadata does not match the session record",
        context="rest.session",
        extra={"ws_close_code": WebSocketCloseCode.BAD_METADATA},
    ),
    ErrorKey.EMPTY_UPLOAD: ErrorDefinition(
        status=HTTPStatus.BAD_REQUEST,
        message="no audio data was uploaded",
        context="rest.upload",
        extra={"ws_close_code": WebSocketCloseCode.BAD_METADATA},
    ),
    ErrorKey.UPLOAD_TOO_LARGE: ErrorDefinition(
        status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        message="uploaded audio exceeds the maximum allowed size",
        context="rest.upload",
        extra={"ws_close_code": WebSocketCloseCode.PAYLOAD_TOO_LARGE},
    ),
    ErrorKey.STORAGE_FAILURE: ErrorDefinition(
        status=HTTPStatus.BAD_GATEWAY,
        message="failed to persist audio to object storage",
        context="rest.storage",
        extra={"ws_close_code": WebSocketCloseCode.INTERNAL_ERROR},
    ),
    ErrorKey.UPSTREAM_STREAM_FAILURE: ErrorDefinition(
        status=HTTPStatus.BAD_GATEWAY,
        message="stream-api reported an unrecoverable error",
        context="rest.upstream",
        extra={"ws_close_code": WebSocketCloseCode.UPSTREAM_FAILURE},
    ),
    ErrorKey.TRANSCRIPTION_TIMEOUT: ErrorDefinition(
        status=HTTPStatus.GATEWAY_TIMEOUT,
        message="timed out waiting for the final transcript",
        context="rest.upstream",
        extra={"ws_close_code": WebSocketCloseCode.TIMEOUT},
    ),
    ErrorKey.INTERNAL: ErrorDefinition(
        status=HTTPStatus.INTERNAL_SERVER_ERROR,
        message="internal server error",
        context="rest.internal",
        extra={"ws_close_code": WebSocketCloseCode.INTERNAL_ERROR},
    ),
}


@dataclass(frozen=True, slots=True)
class RestApiError(CommonError):
    """Raised for rest API request and stream failures."""

    key: ErrorKey

    ERROR_DEFINITIONS: ClassVar[dict[ErrorKey, ErrorDefinition]] = ERROR_DEFINITIONS


def get_error_definition(key: ErrorKey) -> ErrorDefinition:
    """Fetch the canonical error mapping for one failure key."""
    return ERROR_DEFINITIONS[key]


def http_status_for(key: ErrorKey) -> int:
    """Return the integer HTTP status code for an error key."""
    return int(ERROR_DEFINITIONS[key].status)


def ws_close_code_for(key: ErrorKey) -> int:
    """Return the WebSocket close code for an error key."""
    return int(ERROR_DEFINITIONS[key].extra["ws_close_code"])
