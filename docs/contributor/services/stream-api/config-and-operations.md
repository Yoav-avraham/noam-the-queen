# Stream API Config and Operations

Last verified: 2026-06-20

## Environment Variables

Defined by `StreamApiConfig` in `services/stream-api/src/stream_api/config.py`:

- `STREAM_API_HOST` (default: `0.0.0.0`)
- `STREAM_API_PORT` (default: `50051`)
- `REDIS_URL` (default: `redis://localhost:6379`)
- `STREAM_API_FINAL_RESULT_WAIT_TIMEOUT_S` (default: `12.0`)
- `STREAM_API_CHUNK_PERSIST_TIMEOUT_S` (default: `3.0`)
- `STREAM_API_FINAL_OUTPUT_POLL_BLOCK_MS` (default: `1000`)
- `STREAM_API_OUTBOUND_QUEUE_MAXSIZE` (default: `1024`)

## Run Locally

```bash
uv run --package stt-stream-api python -m stream_api
```

## Redis Stream Format

- Ready-audio stream key: `ready_audio:{session_id}`
- Final-output stream key: `final_output:{session_id}`
- Shared envelope: `ServiceOutput` stored under `data`

Persisted chunk fields include:
- `session_id`
- `sequence_id` (monotonic per session)
- `is_final` (`true` only for the last persisted chunk or final output)
- `window_payload.content.raw_bytes` for ready-audio chunks, with `channels`, `sample_width`, and `sample_rate` forwarded unchanged from the `AudioChunk`
- `window_payload.content.text` for routed final output

## Chunk Persistence Semantics

- Clients send raw `AudioChunk.audio` bytes plus audio format (`channels`, `sample_width`, `sample_rate`) and may optionally supply `AudioChunk.session_id`.
- stream-api persists raw chunk bytes directly to Redis and does not decode, transcode, or resample payloads.
- The first accepted chunk registers the session and is written immediately with `is_final=false`.
- Each subsequent chunk is written immediately with its own monotonic `sequence_id`.
- On client half-close, stream-api flushes the buffered last chunk with `is_final=true`; it does not write a synthetic zero-byte marker.
- Chunk persistence timeout is controlled by `STREAM_API_CHUNK_PERSIST_TIMEOUT_S`.
- stream-api consumes per-session final results from `final_output:{session_id}`.
- Wait for the final Redis result is bounded by `STREAM_API_FINAL_RESULT_WAIT_TIMEOUT_S`.
- Outbound per-stream queue size is bounded by `STREAM_API_OUTBOUND_QUEUE_MAXSIZE`.
- If final result wait times out, stream emits `ServerEvent.error` and closes.

## Quality and Test Commands

Start Redis before integration tests:

```bash
docker compose up -d redis
```

```bash
ruff check --fix services/stream-api/
pyright services/stream-api/src/stream_api
uv run -- pytest services/stream-api/src/stream_api/tests --cov=services/stream-api/src/stream_api --cov-fail-under=80
```

Run integration test file directly:

```bash
uv run -- pytest services/stream-api/src/stream_api/tests/test_integration.py -v
```

## Contributor Notes

- Keep contract semantics synced with `docs/consumer/stream-api-proto-guide.md`.
- If route behavior changes, update `ingest-and-routing-flow.md`.
- If persistence payload changes, update this page and relevant consumer docs.
