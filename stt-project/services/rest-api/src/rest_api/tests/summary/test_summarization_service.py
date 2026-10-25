from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from rest_api.domain.types import AggregatedTranscript
from rest_api.summary.summarization_service import SummarizationService


def _build_client(*, content: str, model: str = "fake-model") -> tuple[Any, AsyncMock]:
    create = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            model=model,
        ),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )
    return client, create


@pytest.mark.asyncio
async def test_summarize_accepts_json_object_payload() -> None:
    client, create = _build_client(content='{"text": "fake summary"}', model="m")
    service = SummarizationService(
        client=client,
        model_name="unit-model",
    )

    result = await service.summarize(AggregatedTranscript(text="hello"), system_prompt="system")

    assert result.data == {"text": "fake summary"}
    assert result.model == "m"
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_summarize_rejects_non_object_json_payload() -> None:
    client, _ = _build_client(content='["not", "an", "object"]')
    service = SummarizationService(
        client=client,
        model_name="unit-model",
    )

    with pytest.raises(ValueError, match="JSON object"):
        await service.summarize(AggregatedTranscript(text="hello"), system_prompt="system")
