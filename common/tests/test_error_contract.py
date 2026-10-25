from __future__ import annotations

from enum import StrEnum
from typing import ClassVar
from dataclasses import dataclass

from stt_common.errors import Error as CommonError
from stt_common.errors import ErrorDefinition


class _ErrorKey(StrEnum):
    WITH_MESSAGE = "with_message"
    WITHOUT_MESSAGE = "without_message"


@dataclass(frozen=True, slots=True)
class _Error(CommonError):
    key: _ErrorKey

    ERROR_DEFINITIONS: ClassVar[dict[_ErrorKey, ErrorDefinition]] = {
        _ErrorKey.WITH_MESSAGE: ErrorDefinition(
            status="error",
            message="failed to process",
            context="test.context",
            debug_details="boom",
            extra={"default": "value"},
        ),
        _ErrorKey.WITHOUT_MESSAGE: ErrorDefinition(
            status="warning",
        ),
    }


def test_error_populates_instance_from_definition() -> None:
    error = _Error(key=_ErrorKey.WITH_MESSAGE)

    assert error.status == "error"
    assert error.message == "failed to process"
    assert error.context == "test.context"
    assert error.debug_details == "boom"
    assert error.extra == {"default": "value"}


def test_error_string_uses_status_code_and_message() -> None:
    error = _Error(key=_ErrorKey.WITH_MESSAGE)

    assert str(error) == "error raised with status error: failed to process"


def test_error_string_omits_message_when_missing() -> None:
    error = _Error(key=_ErrorKey.WITHOUT_MESSAGE)

    assert str(error) == "error raised with status warning"


def test_error_populates_runtime_error_args_with_rendered_message() -> None:
    error = _Error(key=_ErrorKey.WITH_MESSAGE)

    assert error.args == ("error raised with status error: failed to process",)


def test_error_populates_runtime_error_args_without_optional_message() -> None:
    error = _Error(key=_ErrorKey.WITHOUT_MESSAGE)

    assert error.args == ("error raised with status warning",)
