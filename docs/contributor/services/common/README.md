# Common Package

Last verified: 2026-05-29
Path: `common`

## Purpose

Holds shared code used by two or more services.

## Current State

- Package: `stt_common`
- Shared surface intentionally minimal.
- Includes shared keyed error contract primitives used by multiple services.

## Key Paths

- Package source: `common/src/stt_common`
- Tests: `common/tests`

Key module:
- `common/src/stt_common/errors.py`
	- `ErrorDefinition`: canonical metadata model (`status`, `message`, `context`, `debug_details`, `extra`).
	- `Error`: keyed runtime error base that resolves service definitions and formats consistent error strings.
- `common/src/stt_common/redis_stream_client.py`
	- `RedisStreamClient`: owns the async Redis connection lifecycle (`from_url()`,
		`ping()`, `aclose()`) and the shared STT stream surface: raw command wrappers
		(`xadd`/`xread`/`xreadgroup`/`xack`/`xclaim`) plus contract helpers
		(`announce_session()`, `append_output()`, `parse_output()`, per-session
		`stream_key()`). Used by both stream-api (producer) and `StreamManager`
		(consumer) so the Redis wire format lives in one place.

## RedisStreamClient + StreamManager Topology

`StreamManager` is injected with a `RedisStreamClient` (it no longer constructs
its own Redis connection) and delegates all Redis access through it.

`common/src/stt_common/stream_manager.py` implements `StreamManager`,
which leases sessions from a shared Redis index and processes their data streams:

- **Session index (`active_streams`)**: a shared stream that announces sessions. A
	worker leases sessions with a single `XREADGROUP` whose `claim_min_idle_time`
	argument returns both new (`>`) entries and entries idle longer than
	`CLAIM_IDLE_MS`, so new and abandoned sessions are leased together. The read is
	bounded by a `count` so sessions are balanced across the consumer group. A
	session's lease is renewed by a throttled heartbeat (`XCLAIM`): after a
	per-session data message is processed, the worker renews that session's lease,
	but at most once per `MIN_HEARTBEAT_INTERVAL_S`.
- **Per-session data streams (`{input_stream_name}:{session_id}`)**: each leased
	session has its own data stream. Reads are unbounded (no `count`): every message
	is owned by the leasing instance, so there is nothing to balance and the worker
	drains whatever is pending. Each message carries a serialized `ServiceOutput`
	envelope; the handler receives `window_payload.content`. The handler result is
	published to the **next** stream in the pipeline
	(`{output_stream_name}:{session_id}`), not back to the input stream.
	`output_stream_name` defaults to the next stream in the circular `StreamName`
	order (`StreamName.next`) and can be overridden explicitly. Messages are acked
	individually, and the session lease is released (`XACK` on the index) only once
	the `is_final` message has been processed.


## Rules

- Do not place service-specific business logic in `common`.
- Promote code to `common` only when duplicate service usage is proven.
- Keep `common` contracts transport-agnostic where possible; service-specific status values are defined in each service's `src/errors.py`.

## Related Docs

- `../../architecture-boundaries.md`
- `../../engineering-standards.md`
