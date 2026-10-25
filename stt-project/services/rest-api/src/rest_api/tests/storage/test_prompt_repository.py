"""Tests for tenant prompt loading from S3/MinIO."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError

from rest_api.domain import ErrorKey, RestApiError
from rest_api.storage.prompt_repository import PromptRepository, build_prompt_key


def test_build_prompt_key_uses_tenant_and_meeting_type() -> None:
    assert build_prompt_key("tenant-a", "hr_interview") == "tenant-a/hr_interview.md"


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aenter__(self) -> _FakeBody:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    def __init__(
        self,
        *,
        body: bytes = b"prompt",
        error_code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self._body = body
        self._error_code = error_code
        self._status_code = status_code
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeS3Client:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self._error_code is not None:
            response: dict[str, Any] = {"Error": {"Code": self._error_code}}
            if self._status_code is not None:
                response["ResponseMetadata"] = {"HTTPStatusCode": self._status_code}
            raise ClientError(response, "GetObject")
        return {"Body": _FakeBody(self._body)}


class _FakeSession:
    def __init__(self, client: _FakeS3Client) -> None:
        self._client = client

    def client(self, *_args: object, **_kwargs: object) -> _FakeS3Client:
        return self._client


def _repository(client: _FakeS3Client) -> PromptRepository:
    return PromptRepository(
        endpoint_url="http://minio:9000",
        access_key="k",
        secret_key="s",
        bucket="stt-audio",
        region="us-east-1",
        session_factory=lambda: _FakeSession(client),  # type: ignore[arg-type,return-value]
        verify=False,
    )


@pytest.mark.asyncio
async def test_get_returns_prompt_text() -> None:
    client = _FakeS3Client(body=b"system prompt")
    repository = _repository(client)

    result = await repository.get(user_id="tenant-a", meeting_type="hr_interview")

    assert result == "system prompt"
    assert client.calls == [{"Bucket": "stt-audio", "Key": "tenant-a/hr_interview.md"}]


@pytest.mark.asyncio
async def test_get_maps_missing_prompt_to_invalid_metadata() -> None:
    repository = _repository(_FakeS3Client(error_code="NoSuchKey", status_code=404))

    with pytest.raises(RestApiError) as exc:
        await repository.get(user_id="tenant-a", meeting_type="missing")

    assert exc.value.key is ErrorKey.INVALID_METADATA


@pytest.mark.asyncio
async def test_get_maps_unknown_404_error_to_invalid_metadata() -> None:
    repository = _repository(_FakeS3Client(error_code="CustomNotFound", status_code=404))

    with pytest.raises(RestApiError) as exc:
        await repository.get(user_id="tenant-a", meeting_type="hr_interview")

    assert exc.value.key is ErrorKey.INVALID_METADATA


@pytest.mark.asyncio
async def test_get_maps_known_missing_error_without_404_to_invalid_metadata() -> None:
    repository = _repository(_FakeS3Client(error_code="NoSuchKey", status_code=403))

    with pytest.raises(RestApiError) as exc:
        await repository.get(user_id="tenant-a", meeting_type="hr_interview")

    assert exc.value.key is ErrorKey.INVALID_METADATA


@pytest.mark.asyncio
async def test_get_maps_other_s3_errors_to_storage_failure() -> None:
    repository = _repository(_FakeS3Client(error_code="AccessDenied", status_code=403))

    with pytest.raises(RestApiError) as exc:
        await repository.get(user_id="tenant-a", meeting_type="hr_interview")

    assert exc.value.key is ErrorKey.STORAGE_FAILURE
