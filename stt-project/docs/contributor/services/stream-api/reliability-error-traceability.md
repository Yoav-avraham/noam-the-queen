# Stream API Reliability Error Traceability

Last verified: 2026-05-29

## Scope

This page maps reliability and error-handling review concerns to concrete implementation and test coverage in stream-api.

## Review Concern to Implementation Matrix

| Review concern | Implementation | Test coverage | Status |
|---|---|---|---|
| First-chunk and later-chunk handling duplicated persistence logic | Unified chunk persistence path in `SessionProcessor._handle_audio_chunk(...)` and reused from `_handle_first_chunk(...)` in `services/stream-api/src/stream_api/ingest/session_processor.py` | `test_stream_audio_emits_single_initial_ack`, `test_stream_audio_emits_error_when_first_chunk_persist_fails` in `services/stream-api/src/stream_api/tests/test_ingest_servicer.py` | Closed |
| Missing final `final_output` result could hang stream close | Added bounded wait in `AudioIngestServicer._await_session_completion(...)` with explicit false-on-timeout semantics in `services/stream-api/src/stream_api/servicers/stream_servicer.py`; timeout mapped to client-facing stream error via `ErrorKey.FINAL_RESULT_TIMEOUT` in `services/stream-api/src/stream_api/errors.py` | `test_stream_audio_times_out_waiting_for_final_result`, `test_stream_audio_waits_for_final_result_before_closing` in `services/stream-api/src/stream_api/tests/test_ingest_servicer.py` | Closed |
| Chunk persistence should fail fast and not share final-result timeout value | Added dedicated per-chunk timeout `chunk_persist_timeout_s` in `services/stream-api/src/stream_api/ingest/session_processor.py`; configured separately from final result wait in `services/stream-api/src/stream_api/config.py` and `services/stream-api/src/stream_api/servicers/stream_servicer.py` | `test_stream_audio_emits_error_on_chunk_persistence_timeout` in `services/stream-api/src/stream_api/tests/test_ingest_servicer.py`; config parsing/validation tests in `services/stream-api/src/stream_api/tests/test_config.py` | Closed |
| Error mapping was distributed and inconsistent | Introduced canonical `ErrorKey` and `ERROR_DEFINITIONS` in `services/stream-api/src/stream_api/errors.py`; centralized event emission through `SessionProcessor._enqueue_mapped_error(...)` | Persist/timeout/unexpected error assertions in `services/stream-api/src/stream_api/tests/test_ingest_servicer.py` | Closed |
| Unexpected exceptions after session setup should surface to clients and still clean up | Added top-level exception handler in `SessionProcessor.consume_client_stream(...)` that emits mapped `UNEXPECTED_STREAM_FAILURE` and ensures stream close in `finally` in `services/stream-api/src/stream_api/ingest/session_processor.py` | `test_stream_audio_emits_unexpected_error_after_state_created` in `services/stream-api/src/stream_api/tests/test_ingest_servicer.py` | Closed |
| Route/session state leakage on timeout/failure paths | Standardized close path via `_close_session_stream(...)` and route unregistration in `services/stream-api/src/stream_api/servicers/stream_servicer.py`; timeout/error tests assert route map is empty post-close | Route cleanup assertions in `test_stream_audio_times_out_waiting_for_final_result`, `test_stream_audio_emits_error_on_chunk_persistence_timeout`, `test_stream_audio_emits_unexpected_error_after_state_created` in `services/stream-api/src/stream_api/tests/test_ingest_servicer.py` | Closed |
| Runtime knobs were hardcoded and split between constants and config | Removed constants file; moved reliability knobs to `StreamApiConfig.from_env()` and passed through bootstrap in `services/stream-api/src/stream_api/server.py` | `test_from_env_reads_reliability_controls`, `test_from_env_rejects_invalid_reliability_float`, `test_config_rejects_non_positive_reliability_controls` in `services/stream-api/src/stream_api/tests/test_config.py` | Closed |

## Operational Defaults (Realtime-Oriented)

- `STREAM_API_FINAL_RESULT_WAIT_TIMEOUT_S=12.0`
- `STREAM_API_CHUNK_PERSIST_TIMEOUT_S=3.0`
- `STREAM_API_OUTBOUND_QUEUE_MAXSIZE=100`

These defaults intentionally separate final-result coordination from per-chunk persistence latency budgets.

## Remaining Risk and Follow-up

- Backpressure saturation behavior is controlled by `STREAM_API_OUTBOUND_QUEUE_MAXSIZE`, but there is no dedicated deterministic unit test that forces outbound queue saturation under load.
- If this becomes an active concern, add a targeted stress test with controllable producer/consumer pacing.
