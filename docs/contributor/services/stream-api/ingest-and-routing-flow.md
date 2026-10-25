# Stream API Ingest and Routing Flow

Last verified: 2026-05-20

## Ingest Flow (`StreamAudio`)

1. Client streams `AudioChunk` messages (audio bytes plus `channels`, `sample_width`, `sample_rate`).
2. Service ignores empty chunks and waits for first non-empty chunk.
3. Service generates `session_id`, registers route, stores first pending chunk, and emits initial `ServerEvent.ack`.
4. Each subsequent chunk is persisted to the session's `ready_audio` stream via the shared `RedisStreamClient` with `is_final=false`.
5. On client half-close, service flushes the pending chunk with `is_final=true`.
6. Service waits for final routed result (`is_final=true`) for the same `session_id`.
7. Service closes route and outbound stream.

Note:
- ACK is emitted once per stream after first-chunk validation/registration, not per chunk.

## Error Paths

- Session route registration failure: failed precondition error event.
- Persistence failure/timeout: internal error event.
- Missing final synchronizer result before timeout: deadline exceeded error event.
- Unexpected runtime exception: internal error event.

## Result Routing Flow (Redis `final_output`)

1. On route registration, stream-api starts a per-session Redis poller on `final_output:{session_id}`.
2. Poller reads `data` envelopes and validates `ServiceOutput` payload shape.
3. Payloads with mismatched session id or malformed data are dropped and logged.
4. Valid payloads are converted into `ServerEvent.result` and enqueued to the active client route.
5. When an `is_final=true` result is routed, the completion event is set.
6. Client stream close cancels the poller and unregisters the route.
