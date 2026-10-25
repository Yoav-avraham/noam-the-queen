# Stream API Proto Guide

Last verified: 2026-06-18
Audience: Consumer integrators

## Purpose

Defines how consumers integrate with stream-api gRPC contracts and what runtime behavior is guaranteed.

## Contract Source of Truth

- Contract file: `services/stream-api/proto/audio_ingest.proto`
- Package versioning: `stream_api.v1`
- Generated Python files are implementation artifacts, not a reusable SDK.

## Integration Standard

1. Pull the published `.proto` contract.
2. Generate client code in your language/toolchain.
3. Implement gRPC calls using generated stubs.

Common toolchains:
- Python: `grpcio-tools`
- Go: `protoc-gen-go`, `protoc-gen-go-grpc`
- Java/Kotlin: protobuf + gRPC plugins
- TypeScript/Node.js: `grpc-tools` or Buf-based flow

## StreamAudio Event Flow

Input shape:
- Client sends a stream of `AudioChunk` messages.
- Each `AudioChunk` contains raw audio bytes in `audio`.
- Each `AudioChunk` also carries the audio format: `channels`, `sample_width` (bytes per sample),
  and `sample_rate` (Hz). stream-api forwards these values unchanged to Redis.
- `AudioChunk.session_id` is optional. If omitted, stream-api generates one and returns it in
  the first `ServerEvent.ack`.

Runtime behavior:
- Server emits one initial `ServerEvent.ack` with the active `session_id` once the first chunk is validated and session routing is registered.
- stream-api announces new sessions in Redis stream `active_streams`.
- Audio is persisted to Redis stream key `ready_audio:{session_id}`.
- stream-api does not transcode or normalize audio payload bytes; audio manipulation now belongs to inference-adapter.
- Redis payloads use the shared `ServiceOutput` envelope; ready-audio content is emitted in `window_payload.content.raw_bytes`, alongside `channels`, `sample_width`, and `sample_rate` forwarded unchanged from the `AudioChunk`.
- Chunk messages include monotonically increasing `sequence_id`; stream-api buffers the most recent chunk and persists the actual last chunk with `is_final=true` on client half-close (no synthetic zero-byte marker).
- On validation/persistence failure, server emits `ServerEvent.error` and terminates processing for that stream.
- If final result on `final_output:{session_id}` does not arrive before configured timeout, server emits `ServerEvent.error`
  (`DEADLINE_EXCEEDED`) and closes the stream.
- Server closes the stream after it has emitted routed final results for the session.

## Final Output Routing Behavior

- stream-api reads per-session result entries from Redis stream `final_output:{session_id}`.
- Entries must contain `data` with a valid shared `ServiceOutput` envelope.
- Payloads with mismatched `session_id` or malformed envelopes are dropped.
- `window_payload.content.text` is mapped into `ServerEvent.result.partial_text`.
- Routed entries with `is_final=true` complete the stream lifecycle.

## Python Type-Checking Note

For Python/Pylance consumers, generate `.pyi` stubs with protobuf output:

```bash
python -m grpc_tools.protoc \
  -I services/stream-api/proto \
  --python_out=services/stream-api/src/stream_api/proto \
  --grpc_python_out=services/stream-api/src/stream_api/proto \
  --pyi_out=services/stream-api/src/stream_api/proto \
  services/stream-api/proto/audio_ingest.proto
```

## Evolution Policy

- Keep package major version in the proto package name.
- Add fields with new field numbers only.
- Never reuse released field numbers.
- Document runtime rules that are not fully captured in schema.
