from __future__ import annotations

from enum import StrEnum
from typing import ClassVar
from dataclasses import dataclass

import grpc

from stt_common.errors import Error as CommonError
from stt_common.errors import ErrorDefinition


class ErrorKey(StrEnum):
    """Stable error keys for stream ingest failures."""

    SESSION_REGISTRATION_FAILED = "session_registration_failed"
    CHUNK_PERSIST_TIMEOUT = "chunk_persist_timeout"
    CHUNK_PERSIST_FAILED = "chunk_persist_failed"
    FINAL_RESULT_TIMEOUT = "final_result_timeout"
    UNEXPECTED_STREAM_FAILURE = "unexpected_stream_failure"


ERROR_DEFINITIONS: dict[ErrorKey, ErrorDefinition] = {
    ErrorKey.SESSION_REGISTRATION_FAILED: ErrorDefinition(
        status=grpc.StatusCode.FAILED_PRECONDITION,
        message="session registration failed",
        context="ingest.session",
    ),
    ErrorKey.CHUNK_PERSIST_TIMEOUT: ErrorDefinition(
        status=grpc.StatusCode.DEADLINE_EXCEEDED,
        message="chunk persist timed out",
        context="ingest.persist",
    ),
    ErrorKey.CHUNK_PERSIST_FAILED: ErrorDefinition(
        status=grpc.StatusCode.INTERNAL,
        message="chunk persist failed",
        context="ingest.persist",
    ),
    ErrorKey.FINAL_RESULT_TIMEOUT: ErrorDefinition(
        status=grpc.StatusCode.DEADLINE_EXCEEDED,
        message="final result timed out",
        context="ingest.final_result",
    ),
    ErrorKey.UNEXPECTED_STREAM_FAILURE: ErrorDefinition(
        status=grpc.StatusCode.INTERNAL,
        message="unexpected stream failure",
        context="ingest.stream",
    ),
}


@dataclass(frozen=True, slots=True)
class InvalidAudioInput(CommonError):
    """Raised when uploaded audio cannot be decoded safely."""

    key: ErrorKey

    ERROR_DEFINITIONS: ClassVar[dict[ErrorKey, ErrorDefinition]] = ERROR_DEFINITIONS


def get_error_definition(key: ErrorKey) -> ErrorDefinition:
    """Fetch canonical error mapping for one runtime failure key."""
    return ERROR_DEFINITIONS[key]
