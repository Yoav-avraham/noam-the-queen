from __future__ import annotations

import re
import json
from typing import TYPE_CHECKING, Any
from dataclasses import dataclass

from pydantic import BaseModel

from rest_api.domain.types import AggregatedTranscript

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class SummarizationResponse(BaseModel):
    data: dict[str, object]
    model: str


@dataclass(frozen=True)
class SummarizationFailure:
    reason: str


# TODO: change to something yhali or maya prefer in the future
class SummarizationService:
    def __init__(
        self,
        client: AsyncOpenAI,
        model_name: str,
    ) -> None:
        self._client = client
        self._model = model_name

    async def summarize(
        self,
        transcript: AggregatedTranscript,
        *,
        system_prompt: str,
    ) -> SummarizationResponse:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": transcript.text,
                },
            ],
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content or ""

        # Some models prepend a `#` comment before the JSON object — strip it.
        json_text = re.sub(r"^\s*#\s*", "", raw).strip()

        # Strip markdown code fences (```json ... ```) if present.
        json_text = re.sub(r"^```json\s*", "", json_text, flags=re.IGNORECASE)
        json_text = re.sub(r"\s*```$", "", json_text)

        try:
            data: dict[str, Any] = json.loads(json_text)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Model returned malformed JSON.\nRaw output:\n{raw}\nAttempted JSON:\n{json_text}\nError: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError("summarization response must be a JSON object")
        return SummarizationResponse(
            data=data,
            model=response.model,
        )
