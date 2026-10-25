"""Tenant-scoped prompt loading from a MinIO/S3 object store."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any
import logging
from collections.abc import Callable

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

from ..domain import ErrorKey, RestApiError

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], aioboto3.Session]

_S3_CLIENT_CONFIG = Config(request_checksum_calculation="when_required")
_MISSING_OBJECT_CODES = {"NoSuchKey", "NotFound"}


def build_prompt_key(user_id: str, meeting_type: str) -> str:
    """Build the S3 object key for a tenant meeting prompt."""
    return f"{user_id}/{meeting_type}.md"


class PromptRepository:
    """Loads meeting prompts from tenant-scoped object storage keys."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        session_factory: SessionFactory | None = None,
        verify: bool | str,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._bucket = bucket
        self._region = region
        self._session_factory: SessionFactory = session_factory or aioboto3.Session
        self._verify = verify

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
            config=_S3_CLIENT_CONFIG,
        )

    async def get(self, *, user_id: str, meeting_type: str) -> str:
        """Load a tenant prompt and return its UTF-8 text content."""
        key = build_prompt_key(user_id, meeting_type)

        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._bucket, Key=key)
                async with response["Body"] as stream:
                    data: bytes = await stream.read()
        except ClientError as exc:
            status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            code = exc.response.get("Error", {}).get("Code")
            if status_code == HTTPStatus.NOT_FOUND:
                logger.info(
                    "prompt object missing",
                    extra={
                        "bucket": self._bucket,
                        "object_key": key,
                        "user_id": user_id,
                        "status_code": status_code,
                        "error_code": code,
                    },
                )
                raise RestApiError(key=ErrorKey.INVALID_METADATA) from exc

            if code in _MISSING_OBJECT_CODES:
                logger.info(
                    "prompt object missing with non-standard status",
                    extra={
                        "bucket": self._bucket,
                        "object_key": key,
                        "user_id": user_id,
                        "status_code": status_code,
                        "error_code": code,
                    },
                )
                raise RestApiError(key=ErrorKey.INVALID_METADATA) from exc

            logger.error(
                "failed to load prompt object",
                extra={
                    "bucket": self._bucket,
                    "object_key": key,
                    "error": str(exc),
                    "status_code": status_code,
                    "error_code": code,
                },
            )
            raise RestApiError(key=ErrorKey.STORAGE_FAILURE) from exc
        except BotoCoreError as exc:
            logger.error(
                "failed to load prompt object",
                extra={"bucket": self._bucket, "object_key": key, "error": str(exc)},
            )
            raise RestApiError(key=ErrorKey.STORAGE_FAILURE) from exc

        return data.decode("utf-8")
