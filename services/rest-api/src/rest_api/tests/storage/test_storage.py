"""Tests for the S3/MinIO audio storage layer using a fake aioboto3 client."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from rest_api.domain import ErrorKey, RestApiError
from rest_api.storage import AudioObjectStorage, build_object_key


def test_build_object_key_sanitises_filename() -> None:
    key = build_object_key("sess-1", "../../etc/passwd")
    assert key == "sessions/sess-1/audio/passwd"


def test_build_object_key_defaults_when_missing() -> None:
    assert build_object_key("s", None) == "sessions/s/audio/upload.bin"


class _FakeS3Client:
    def __init__(self, *, head_error: bool = False) -> None:
        self.head_error = head_error
        self.put_calls: list[dict[str, Any]] = []
        self.created: list[str] = []

    async def __aenter__(self) -> _FakeS3Client:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def head_bucket(self, *, Bucket: str) -> None:
        if self.head_error:
            raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    async def create_bucket(self, *, Bucket: str) -> None:
        self.created.append(Bucket)

    async def put_object(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)


class _FakeSession:
    def __init__(self, client: _FakeS3Client) -> None:
        self._client = client

    def client(self, *_args: object, **_kwargs: object) -> _FakeS3Client:
        return self._client


def _storage(client: _FakeS3Client) -> AudioObjectStorage:
    return AudioObjectStorage(
        endpoint_url="http://minio:9000",
        access_key="k",
        secret_key="s",
        bucket="stt-audio",
        region="us-east-1",
        session_factory=lambda: _FakeSession(client),  # type: ignore[arg-type,return-value]
    )


@pytest.mark.asyncio
async def test_upload_audio_puts_object() -> None:
    client = _FakeS3Client()
    storage = _storage(client)

    key = await storage.upload_audio(session_id="sess-1", data=b"audio-bytes")

    assert key == "sessions/sess-1/audio/upload.bin"
    assert client.put_calls[0]["Bucket"] == "stt-audio"
    assert client.put_calls[0]["Body"] == b"audio-bytes"


@pytest.mark.asyncio
async def test_ensure_bucket_creates_when_missing() -> None:
    client = _FakeS3Client(head_error=True)
    storage = _storage(client)

    await storage.ensure_bucket()

    assert client.created == ["stt-audio"]


@pytest.mark.asyncio
async def test_upload_failure_raises_storage_error() -> None:
    client = _FakeS3Client()

    async def _boom(**_kwargs: Any) -> None:
        raise ClientError({"Error": {"Code": "500"}}, "PutObject")

    client.put_object = _boom  # type: ignore[method-assign]
    storage = _storage(client)

    with pytest.raises(RestApiError) as exc:
        await storage.upload_audio(session_id="sess-1", data=b"x")
    assert exc.value.key is ErrorKey.STORAGE_FAILURE
