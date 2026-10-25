"""Audio object storage backed by MinIO/S3 (via aioboto3).

Uploaded audio is archived under ``sessions/{session_id}/audio/{filename}``. The
S3 client session factory is injectable so the storage layer can be unit-tested
without a live MinIO endpoint.
"""

from __future__ import annotations

import os
import re
from typing import Any
import logging
from collections.abc import Callable

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

from ..domain import ErrorKey, RestApiError

logger = logging.getLogger(__name__)

_DEFAULT_FILENAME = "upload.bin"
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]")
_BUCKET_EXISTS_CODES = ["BucketAlreadyOwnedByYou", "BucketAlreadyExists"]

SessionFactory = Callable[[], aioboto3.Session]

_S3_CLIENT_CONFIG = Config(request_checksum_calculation="when_required")


def _safe_filename(filename: str | None) -> str:
    """Reduce a client-supplied filename to a safe object-key leaf."""
    if not filename:
        return _DEFAULT_FILENAME
    base = os.path.basename(filename)
    cleaned = _SAFE_FILENAME.sub("_", base).strip("._")
    return cleaned or _DEFAULT_FILENAME


def build_object_key(session_id: str, filename: str | None) -> str:
    """Build the S3 object key for a session's uploaded audio."""
    return f"sessions/{session_id}/audio/{_safe_filename(filename)}"


class AudioObjectStorage:
    """Stores uploaded audio files in an S3-compatible object store."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        session_factory: SessionFactory | None = None,
        verify: bool | str = False,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._session_factory: SessionFactory = session_factory or aioboto3.Session
        self._verify = verify

    @property
    def bucket(self) -> str:
        """Return the configured destination bucket name."""
        return self._bucket

    def _client(self) -> Any:
        """Open an async S3 client context manager."""
        session = self._session_factory()
        return session.client(
            "s3",
            endpoint_url=self._endpoint_url,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            region_name=self._region,
            verify=self._verify,
            config=_S3_CLIENT_CONFIG
        )

    async def ensure_bucket(self) -> None:
        """Create the destination bucket if it does not already exist."""
        async with self._client() as client:
            try:
                await client.head_bucket(Bucket=self._bucket)
                return
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                logger.info("creating object storage bucket", extra={"bucket": self._bucket})
            try:
                kwargs: dict[str, Any] = {"Bucket": self._bucket}
                if self._region != "us-east-1":
                    kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self._region}
                await client.create_bucket(**kwargs)
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code")
                if code not in _BUCKET_EXISTS_CODES:
                    raise

    async def upload_audio(
        self,
        *,
        session_id: str,
        data: bytes,
        filename: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload audio bytes for a session and return the stored object key.

        Raises:
            RestApiError: ``STORAGE_FAILURE`` if the upload fails.
        """
        key = build_object_key(session_id, filename)
        try:
            async with self._client() as client:
                await client.put_object(
                    Bucket=self._bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                )
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "failed to upload audio to object storage",
                extra={"session_id": session_id, "bucket": self._bucket, "error": str(exc)},
            )

            raise RestApiError(key=ErrorKey.STORAGE_FAILURE) from exc

        logger.info(
            "stored audio object",
            extra={"session_id": session_id, "bucket": self._bucket, "object_key": key},
        )
        return key
