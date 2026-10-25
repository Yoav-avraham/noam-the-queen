"""Tests for the error contract mappings."""

from __future__ import annotations

from http import HTTPStatus

import pytest

from rest_api.domain import (
    ERROR_DEFINITIONS,
    ErrorKey,
    RestApiError,
    http_status_for,
    ws_close_code_for,
    get_error_definition,
)


def test_every_key_has_a_definition() -> None:
    for key in ErrorKey:
        assert key in ERROR_DEFINITIONS


def test_every_definition_has_http_status_and_ws_code() -> None:
    for key in ErrorKey:
        definition = get_error_definition(key)
        assert isinstance(definition.status, HTTPStatus)
        assert "ws_close_code" in definition.extra


def test_http_status_for_returns_int() -> None:
    assert http_status_for(ErrorKey.SESSION_NOT_FOUND) == 404


def test_ws_close_code_for_returns_app_code() -> None:
    assert ws_close_code_for(ErrorKey.INVALID_TOKEN) == 4401


def test_rest_api_error_resolves_message() -> None:
    error = RestApiError(key=ErrorKey.SESSION_NOT_OPEN)
    assert error.message == "session is not open for streaming"
    assert "session is not open" in str(error)


def test_rest_api_error_is_runtime_error() -> None:
    with pytest.raises(RuntimeError):
        raise RestApiError(key=ErrorKey.STORAGE_FAILURE)
