# Summarization Usage Example

This module provides meeting transcript summarization via a vLLM backend.
It is composed of two classes:

- **`VLLMClient`** — wraps `AsyncOpenAI` and reads connection settings
  (`VLLM_BASE_URL`, `VLLM_API_KEY`) from environment variables via `vllm_connection_settings`.
- **`SummarizationService`** — sends the transcript to the model and returns a
  structured `SummarizationResponse`.

---

## Minimal example

```python
from rest_api.config import vllm_connection_settings
from rest_api.domain.types import AggregatedTranscript
from rest_api.summary.vllm_client import VLLMClient
from rest_api.summary.summarization_service import SummarizationService

# 1. Build the OpenAI-compatible client pointed at the vLLM server.
#    Connection settings (base URL, API key, model name) come from env vars:
#      VLLM_BASE_URL  — default "http://vllm:8000/v1"
#      VLLM_API_KEY   — default "EMPTY"
#      VLLM_MODEL     — default "llama-3.1-8b-instruct"
client = VLLMClient()

# 2. Instantiate the service, passing the underlying AsyncOpenAI client
#    and the model name to use for completions.
service = SummarizationService(
    client=client.client,
    model_name=vllm_connection_settings.vllm_model,
)

# 3. Call summarize() with an AggregatedTranscript (returned by StreamSessionHandler._process).
#    Only transcript.text is sent to the model. No optional args.
transcript: AggregatedTranscript = ...  # obtained from the transcription pipeline

result = await service.summarize(transcript)

# SummarizationResponse fields:
#   result.summary       — concise summary string
#   result.key_points    — list[str] of important points
#   result.action_items  — list[str] of decisions / tasks to follow up on
#   result.model         — model name echoed back from the API response
print(result.summary)
print(result.key_points)
print(result.action_items)
```

The model is instructed to return structured JSON and the API call uses
`response_format={"type": "json_object"}` to enforce it. The raw JSON is
parsed internally and mapped onto `SummarizationResponse` — callers always
receive a typed object, never raw text.

---

## Notes

- `SummarizationService.summarize()` is **async** — it must be awaited inside an
  async context (e.g. a FastAPI route handler or an async test).
- The system prompt instructs the model to preserve decisions and action items and
  to write in the same language as the transcript.
- To override connection settings without changing code, set the env vars before
  starting the service:
  ```bash
  export VLLM_BASE_URL=http://my-vllm-host:8000/v1
  export VLLM_API_KEY=my-secret-key
  export VLLM_MODEL=my-custom-model
  ```
