"""Tests for session token issuance and verification."""

from __future__ import annotations

import time

import jwt
import pytest

from rest_api.domain import ErrorKey, RestApiError
from rest_api.security import (
    issue_session_token,
    decode_session_token,
    verify_session_token,
)

_SECRET = "unit-secret"
_ALG = "HS256"


def test_issue_and_decode_roundtrip() -> None:
    token, expires_at = issue_session_token(user_id="abc", secret=_SECRET, algorithm=_ALG, ttl_s=60)
    assert decode_session_token(token=token, secret=_SECRET, algorithm=_ALG) == "abc"
    assert expires_at.tzinfo is not None


def test_verify_accepts_matching_subject() -> None:
    token, _ = issue_session_token(user_id="s1", secret=_SECRET, algorithm=_ALG, ttl_s=60)
    verify_session_token(token=token, secret=_SECRET, algorithm=_ALG, expected_user_id="s1")


def test_verify_rejects_subject_mismatch() -> None:
    token, _ = issue_session_token(user_id="s1", secret=_SECRET, algorithm=_ALG, ttl_s=60)
    with pytest.raises(RestApiError) as exc:
        verify_session_token(token=token, secret=_SECRET, algorithm=_ALG, expected_user_id="other")
    assert exc.value.key is ErrorKey.TOKEN_USER_MISMATCH


def test_invalid_signature_rejected() -> None:
    token, _ = issue_session_token(user_id="s1", secret=_SECRET, algorithm=_ALG, ttl_s=60)
    with pytest.raises(RestApiError) as exc:
        decode_session_token(token=token, secret="wrong-secret", algorithm=_ALG)
    assert exc.value.key is ErrorKey.INVALID_TOKEN


def test_expired_token_rejected() -> None:
    payload = {
        "sub": "s1",
        "scope": "session:stream",
        "iat": int(time.time()) - 120,
        "exp": int(time.time()) - 60,
    }
    token = jwt.encode(payload, _SECRET, algorithm=_ALG)
    with pytest.raises(RestApiError) as exc:
        decode_session_token(token=token, secret=_SECRET, algorithm=_ALG)
    assert exc.value.key is ErrorKey.TOKEN_EXPIRED


def test_missing_subject_rejected() -> None:
    token = jwt.encode(
        {"exp": int(time.time()) + 60, "sub": "", "scope": "session:stream"},
        _SECRET,
        algorithm=_ALG,
    )
    with pytest.raises(RestApiError) as exc:
        decode_session_token(token=token, secret=_SECRET, algorithm=_ALG)
    assert exc.value.key is ErrorKey.INVALID_TOKEN


def test_garbage_token_rejected() -> None:
    with pytest.raises(RestApiError) as exc:
        decode_session_token(token="not-a-jwt", secret=_SECRET, algorithm=_ALG)
    assert exc.value.key is ErrorKey.INVALID_TOKEN
