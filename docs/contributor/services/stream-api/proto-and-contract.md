# Stream API Proto and Contract

Last verified: 2026-05-20

## Source of Truth

- Contract file: `services/stream-api/proto/audio_ingest.proto`
- Package: `stream_api.v1`
- Service: `AudioIngestService`

## RPC Surfaces

- `StreamAudio(stream AudioChunk) returns (stream ServerEvent)`

## Message Roles

Client -> stream-api:
- `AudioChunk` (carries `audio` bytes plus audio format: `channels`, `sample_width`, `sample_rate`)

stream-api -> client:
- `ServerEvent.ack`
- `ServerEvent.error`
- `ServerEvent.result`

final_output Redis -> stream-api:
- `ServiceOutput.window_payload.content.text` mapped to `ServerEvent.result.partial_text`

## Operational Semantics

- `StreamAudio` consumes raw audio bytes and performs server-side session + chunk lifecycle.
- `AudioChunk.channels`, `AudioChunk.sample_width`, and `AudioChunk.sample_rate` are forwarded unchanged into the ready-audio Redis payload.
- Initial ACK is emitted after first accepted chunk and successful session route registration.
- Accepted chunks are persisted to Redis Streams with sequence metadata; the actual last chunk is persisted with `is_final=true` on half-close (no synthetic marker).
- Persistence/timeout/unexpected runtime failures produce error events and stream termination behavior.
- final-output entries with mismatched session id or malformed payload are dropped.

## Generated Code

Generated artifacts are under `services/stream-api/src/stream_api/proto/` and should not be edited directly.
