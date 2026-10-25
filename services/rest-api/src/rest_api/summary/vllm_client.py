from __future__ import annotations

import httpx2 as httpx
from openai import AsyncOpenAI


class VLLMClient:
    def __init__(self, *, base_url: str, api_key: str) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.AsyncClient(
                verify=False,
            ),
        )

    @property
    def client(self) -> AsyncOpenAI:
        return self._client
