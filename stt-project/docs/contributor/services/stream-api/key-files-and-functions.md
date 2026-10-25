# Stream API Key Files and Functions

Last verified: 2026-05-29

## Service Entry

- `src/__main__.py`
: module entrypoint used by `python -m stream_api`.

- `src/server.py`
: boots gRPC server, validates Redis connectivity via the shared `RedisStreamClient`, and wires `AudioIngestServicer` with a `SessionProcessor` (built on `RedisStreamClient` + `StreamRouter`).

## Config

- `src/config.py`
: `StreamApiConfig.from_env()` loads runtime settings, including normalized audio
	format values (`sample_rate_hz`, `sample_channels`, `sample_codec`, `sample_layout`).

## Persistence

- Shared `stt_common.redis_stream_client.RedisStreamClient` (in `common/`)
: owns the Redis connection and stream-contract helpers (`announce_session()`,
	`append_output()`, per-session `stream_key()`, raw `xadd`/`xread` wrappers).
	stream-api persists accepted chunks via `RedisStreamClient.append_output(StreamName.READY_AUDIO, ...)`.

## Servicer Core

- `src/servicers/stream_servicer.py`
: thin gRPC transport boundary (`AudioIngestServicer`) that bridges each `StreamAudio` call to `SessionProcessor.consume_client_stream(...)` over an outbound queue.
- `src/ingest/session_processor.py`
: per-session stream orchestration, chunk lifecycle, Redis persistence, and `final_output` consumption/routing.
- Audio manipulation modules were moved to `services/inference-adapter/src/inference_adapter/`.
- `src/errors.py`
: canonical runtime error mapping (`ErrorKey`, `ERROR_DEFINITIONS`) used for client-facing `StreamError` events.
- `src/types.py`
: shared stream-api cross-module type contracts (`ServerEventQueue`).

Key methods:
- `StreamAudio`
: consumes client events and yields ack/error/result events.
- `consume_client_stream`
: processes inbound chunks, persists chunk entries, and coordinates close semantics.
- `_write_chunk_to_redis`
: writes chunk entries with a bounded persistence timeout.
- `_enqueue_mapped_error`
: emits normalized `StreamError` payloads from canonical error mappings.
- `_consume_final_output_session`
: polls `final_output:{session_id}`, maps Redis envelopes to result events, and signals final completion.

## Validation + State

- `src/ingest/state.py`
: `StreamState` tracks pending chunk state, stream/session metadata, and counters.

## Session Routing

- `src/ingest/stream_router.py`
: `StreamRouter` owns the in-memory route table with lock-protected methods.

Key methods:
- `register`
: enforces one active route per session and creates its completion event.
- `route_result_event`
: maps a routed result into `ServerEvent.result`, enqueues it for the active session, and signals completion on final results.
- `wait_for_completion`
: waits for the session's final result (bounded by timeout).
- `set_final_output_task` / `cancel_final_output_task`
: track and tear down the per-session `final_output` consumer task.
- `unregister`
: removes route mapping on stream close.
