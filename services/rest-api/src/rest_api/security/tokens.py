"""Signed session token issuance and verification (JWT HS*).

Tokens are independent of a transcription session: a caller receives a signed
bearer token from ``POST /v1/authorize/{user_id}`` and must present it when
opening the Socket.IO connection. The token's ``sub`` claim binds it to the
authorized ``user_id``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import jwt

from ..domain import ErrorKey, RestApiError

logger = logging.getLogger(__name__)

_TOKEN_SCOPE = "session:stream"
_DEFAULT_ALGORITHM = "HS256"
_DEFAULT_TTL_S = 3600


def issue_session_token(
    *,
    secret: str,
    algorithm: str = _DEFAULT_ALGORITHM,
    ttl_s: int = _DEFAULT_TTL_S,
    user_id: str,
) -> tuple[str, datetime]:
    """Issue a signed token bound to ``user_id``.

    Args:
        user_id: The user this token authorizes.
        secret: Shared signing secret.
        algorithm: JWT signing algorithm (e.g. ``HS256``).
        ttl_s: Token lifetime in seconds.

    Returns:
        A tuple of (encoded token, absolute expiry timestamp).
    """
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=ttl_s)
    payload = {
        "sub": user_id,
        "scope": _TOKEN_SCOPE,
        "iat": issued_at,
        "exp": expires_at,
    }
    token = jwt.encode(payload, secret, algorithm=algorithm)
    return token, expires_at


def decode_session_token(*, token: str, secret: str, algorithm: str = _DEFAULT_ALGORITHM) -> str:
    """Decode and validate a token, returning the bound user id.

    Raises:
        RestApiError: ``TOKEN_EXPIRED`` when expired, ``INVALID_TOKEN`` for any
            other signature/format/claim failure.
    """
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": ["sub", "exp", "scope"]},
        )
    except jwt.ExpiredSignatureError as exc:
        logger.info("rejected expired session token", extra={"error": str(exc)})
        raise RestApiError(key=ErrorKey.TOKEN_EXPIRED) from exc
    except jwt.PyJWTError as exc:
        logger.info("rejected invalid session token", extra={"error": str(exc)})
        raise RestApiError(key=ErrorKey.INVALID_TOKEN) from exc

    scope = payload.get("scope")

    if scope != _TOKEN_SCOPE:
        logger.info("session token has unexpected scope", extra={"scope": scope})
        raise RestApiError(key=ErrorKey.INVALID_TOKEN)

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject:
        logger.info("session token missing subject claim")
        raise RestApiError(key=ErrorKey.INVALID_TOKEN)
    return subject


def verify_session_token(
    *,
    token: str,
    secret: str,
    algorithm: str = _DEFAULT_ALGORITHM,
    expected_user_id: str,
) -> None:
    """Verify a token and assert it is bound to ``expected_user_id``.

    Raises:
        RestApiError: ``TOKEN_EXPIRED`` / ``INVALID_TOKEN`` on decode failure,
            ``TOKEN_USER_MISMATCH`` when the subject does not match.
    """
    subject = decode_session_token(token=token, secret=secret, algorithm=algorithm)
    if subject != expected_user_id:
        logger.info(
            "session token subject mismatch",
            extra={"expected": expected_user_id, "actual": subject},
        )
        raise RestApiError(key=ErrorKey.TOKEN_USER_MISMATCH)
