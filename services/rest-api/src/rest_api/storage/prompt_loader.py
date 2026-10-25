"""Load the summarization system prompt from a MinIO/S3 object store."""

from __future__ import annotations

from typing import Any
import logging
from collections.abc import Callable

import aioboto3

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], aioboto3.Session]


async def load_system_prompt(
    *,
    endpoint_url: str,
    access_key: str,
    secret_key: str,
    bucket: str,
    key: str,
    region: str,
    session_factory: SessionFactory | None = None,
) -> str:
    """Fetch the system prompt text from a MinIO/S3 object.

    Args:
        endpoint_url: MinIO/S3 endpoint (e.g. ``http://localhost:9000``).
        access_key: AWS/MinIO access key ID.
        secret_key: AWS/MinIO secret access key.
        bucket: Name of the bucket containing the prompt object.
        key: Object key (path) of the prompt file inside the bucket.
        region: AWS region name.
        session_factory: Optional override for the aioboto3 session factory
            (used in tests to inject a fake S3 client).

    Returns:
        The prompt text decoded as UTF-8.

    Raises:
        botocore.exceptions.ClientError: When the object or bucket does not exist.
    """
    factory: SessionFactory = session_factory or aioboto3.Session
    session: Any = factory()
    async with session.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        verify=False
    ) as s3:
        logger.info("loading system prompt from s3://%s/%s", bucket, key)
        response = await s3.get_object(Bucket=bucket, Key=key)
        async with response["Body"] as stream:
            data: bytes = await stream.read()
    return data.decode("utf-8")
