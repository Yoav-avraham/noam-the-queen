# Stream API Service

Last verified: 2026-05-26
Path: `services/stream-api`

## Purpose

Implements gRPC audio ingestion for clients, persists validated audio chunks, and routes transcription updates to active client sessions.

## Read This First

- `proto-and-contract.md`
- `ingest-and-routing-flow.md`
- `key-files-and-functions.md`
- `config-and-operations.md`
- `reliability-error-traceability.md`

## Current Capabilities

- `StreamAudio` bidirectional stream over `AudioChunk` with server-side chunk persistence.
- Initial ACK after first accepted chunk and route registration; subsequent chunks are persisted with per-chunk error handling.
- Per-session result routing by consuming Redis `final_output:{session_id}` entries.
- Single active route per `session_id`.
- Audio transcoding/resampling ownership was moved out of stream-api and into inference-adapter.

## Service Parts

- Contract layer: `proto/audio_ingest.proto`
- gRPC bootstrap: `src/server.py`
- Runtime config: `src/config.py`
- Persistence: shared `stt_common.redis_stream_client.RedisStreamClient` (in `common/`)
- Stream logic: `src/ingest/*` + `src/servicers/stream_servicer.py`
- Tests: `src/tests`
