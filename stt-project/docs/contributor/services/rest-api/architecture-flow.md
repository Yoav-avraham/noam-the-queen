# Rest API Service Architecture and Flow

Last verified: 2026-06-08

## Purpose

This document outlines the complete request flow, component interactions, communication patterns, performance characteristics, and scalability considerations for the rest-api service wrapper around the stream-api gRPC pipeline.

## High-Level Architecture

The rest-api service acts as a stateful HTTP/WebSocket wrapper that:

1. Provides a consumer-friendly REST interface for session creation
2. Accepts audio uploads via WebSocket
3. Persists sessions and transcripts in PostgreSQL
4. Archives audio files to object storage (MinIO/S3)
5. Streams audio chunks to stream-api via gRPC
6. Aggregates and returns transcription results

```
┌──────────┐
│  Client  │
└─────┬────┘
      │ HTTP POST /v1/authorize
      ▼
┌─────────────────────────────────────────────────────────────────┐
│                         rest-api Service                        │
│                                                                 │
│  ┌──────────────┐    ┌─────────────┐    ┌─────────────────┐  │
│  │ FastAPI      │◄───┤ AppContext  │───►│ SessionStore    │  │
│  │ (routes)     │    │             │    │ (SQLAlchemy)    │  │
│  └──────┬───────┘    └──────┬──────┘    └────────┬────────┘  │
│         │                   │                     │            │
│         │              ┌────┴──────┐              │            │
│         │              │ Pipeline  │              │            │
│         ▼              │ Components│              ▼            │
│  ┌──────────────┐     └───────────┘         ┌─────────┐      │
│  │ Stream       │    ┌─────────────────┐    │ Postgres│      │
│  │ Handler      │◄───┤ StreamAudio     │    │   DB    │      │
│  │ (WebSocket)  │    │ Client (gRPC)   │    └─────────┘      │
│  └──────┬───────┘    └────────┬────────┘                     │
│         │                     │                               │
│         │            ┌────────┴────────┐                     │
│         ▼            │                 │                     │
│  ┌──────────────┐   │  ┌───────────┐  │   ┌──────────────┐ │
│  │ Transcript   │   │  │ Chunking  │  │   │ Audio Object │ │
│  │ Aggregator   │   │  │ Engine    │  │   │ Storage      │ │
│  └──────────────┘   │  └───────────┘  │   │ (MinIO/S3)   │ │
│                     │                 │   └──────┬───────┘ │
└─────────────────────┼─────────────────┼──────────┼─────────┘
                      │                 │          │
                      ▼                 │          ▼
              ┌────────────┐            │   ┌──────────┐
              │ stream-api │            │   │  MinIO   │
              │ (gRPC)     │            │   │  Bucket  │
              └────────────┘            │   └──────────┘
                                        │
                                        ▼
                                 (inference pipeline)
```

## Component Responsibilities

### API Layer (`api/`)

**routes/authorization.py** — REST endpoint handler

- Validates incoming session creation requests
- Persists session metadata with `status=created`
- Generates signed JWT tokens bound to session_id
- Returns session details and streaming endpoint

**routes/stream.py** — WebSocket endpoint handler

- Token validation (signature, expiration, session binding)
- Session state validation (must be `created`)
- Delegates to `StreamSessionHandler`

**stream_handler.py** — WebSocket session orchestrator

- Manages complete upload-to-transcript lifecycle
- Validates client metadata echo
- Buffers binary audio frames
- Coordinates storage, streaming, and aggregation
- Emits periodic status heartbeats
- Handles graceful/error shutdown

**schemas.py** — Pydantic message contracts

- Client → server: `ClientMetadataMessage`, `UploadCompleteMessage`
- Server → client: `AcceptedMessage`, `StatusMessage`, `TranscriptMessage`, `ClosedMessage`, `ErrorMessage`

### Pipeline Layer (`pipeline/`)

**grpc_client.py** — stream-api gRPC adapter

- Wraps `AudioIngestService.StreamAudio` bidirectional RPC
- Converts raw bytes to `AudioFrame` protobuf messages
- Translates protobuf `ServerEvent` to typed domain events (`StreamAck`, `StreamResult`, `StreamFailure`)
- Isolates the rest of the service from protobuf types

**chunking.py** — Audio partitioning

- Slices uploaded audio into fixed-size byte chunks (default: 32KB)
- No audio format awareness (opaque byte slicing)
- Configurable chunk size via `REST_API_CHUNK_SIZE_BYTES`

**aggregator.py** — Transcript assembly

- Collects all partial transcription results in arrival order
- Orders segments by `(sequence)` for stable output
- Builds final transcript from final segments (if any) or latest partial

### Persistence Layer (`db/`)

**engine.py** — SQLAlchemy async engine factory

- Creates async PostgreSQL engine from `DATABASE_URL`
- Configured for asyncpg dialect

**models.py** — ORM models

- `Session`: session metadata, status lifecycle, foreign session ids, transcript
- `TranscriptSegment`: individual partial results for traceability

**repository.py** — Session store abstraction

- `SessionStore` protocol defines persistence contract
- `SqlAlchemySessionStore` implements CRUD + status transitions
- Methods: `create_session`, `get_session`, `update_status`, `close_session`, `fail_session`

### Storage Layer (`storage/`)

**objects.py** — S3-compatible object storage

- Backed by aioboto3 (async boto3)
- Stores audio under `sessions/{session_id}/audio/{filename}`
- Auto-creates bucket at startup if missing
- Configurable endpoint, credentials, bucket, region

### Security Layer (`security/`)

**tokens.py** — JWT token management

- Generates HS256-signed tokens with `sub=session_id`
- Validates signature, expiration, and subject binding
- Configurable secret, algorithm, TTL

### Domain Layer (`domain/`)

**types.py** — Shared value types

- `SessionStatus` enum (state machine: created → streaming → processing → closed | failed)
- `TranscriptSegment`, `AggregatedTranscript`

**errors.py** — Error contract

- `ErrorKey` enum mapped to HTTP/WebSocket status codes
- `RestApiError` exception with structured error keys

### Application Bootstrap

**config.py** — Environment-driven configuration

- Frozen dataclass with validation
- Loads from `REST_API_*` prefixed env vars
- Fail-fast validation in `__post_init__`

**context.py** — Dependency injection container

- `AppContext` holds long-lived collaborators (store, storage, gRPC channel factory)
- `build_context()` constructs production wiring
- Tests inject fake collaborators

**app.py** — FastAPI factory

- `create_app()` builds the application with lifespan management
- Registers exception handlers, routers
- Attaches context to `app.state`

**server.py** — Uvicorn entrypoint

- Loads config, builds app, runs server

## Complete Request Flow

### Session Creation (POST /v1/authorize)

```
1. Client POST /v1/authorize
   ├─ Body: { participant_ids, meeting_type_id }
   └─ Validation: non-empty participant_ids, integer meeting_type_id

2. FastAPI route handler (authorization.py:authorize_connection)
   ├─ Parse and validate request body (Pydantic)
   ├─ Generate UUID session_id
   └─ Call store.create_session(session_id, metadata)

3. SessionStore.create_session
   ├─ Insert into sessions table (status=created)
   └─ Return SessionView

4. Generate JWT token
   ├─ sub = session_id
   ├─ exp = now + token_ttl_s
   └─ Sign with token_secret (HS256)

5. Response 201 Created
   └─ Body: { session_id, token, status, expires_at, stream_path }
```

**Timing:** ~10-50ms (database insert + JWT signing)

### Transcription Session (WS /v1/upload)

```
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: Authentication & Setup (0-100ms)                       │
└─────────────────────────────────────────────────────────────────┘

1. Client opens WebSocket with token (query param or header)
2. stream.py:stream_session validates token
   ├─ Decode and verify JWT signature
   ├─ Check expiration
   ├─ Verify sub matches session_id in URL
   └─ Raise 401 if invalid

3. Load session from database
   ├─ store.get_session(session_id)
   ├─ Check session exists (404 if not)
   ├─ Check status == created (409 if already streaming/closed)
   └─ Return SessionView

4. Accept WebSocket connection
5. Create StreamSessionHandler(websocket, context, session)
6. Send AcceptedMessage { session_id }

┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: Metadata Validation (0-50ms)                           │
└─────────────────────────────────────────────────────────────────┘

7. Receive client metadata frame (JSON text)
   └─ Expected: { type: "metadata", participant_ids, meeting_type_id }

8. Validate metadata matches session record
   ├─ participant_ids must match (set equality)
   ├─ meeting_type_id must match
   └─ Raise 400 METADATA_MISMATCH if mismatch

┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: Audio Upload (variable, depends on file size)          │
└─────────────────────────────────────────────────────────────────┘

9. Buffer binary WebSocket frames into bytearray
   ├─ Enforce max_upload_bytes limit (default: 100MB)
   ├─ Raise 413 UPLOAD_TOO_LARGE if exceeded
   └─ Continue until text frame received

10. Receive upload_complete control frame
    └─ Expected: { type: "upload_complete" }

11. Validate non-empty upload
    └─ Raise 400 EMPTY_UPLOAD if buffer is empty

┌─────────────────────────────────────────────────────────────────┐
│ Phase 4: Storage & Streaming Setup (100-500ms)                  │
└─────────────────────────────────────────────────────────────────┘

12. Update session status to STREAMING
    └─ store.update_status(session_id, SessionStatus.STREAMING)

13. Upload audio to object storage
    ├─ Generate key: sessions/{session_id}/audio/upload.bin
    ├─ storage.upload_audio(session_id, data)
    └─ MinIO/S3 PUT operation (~50-200ms for 10MB file)

14. Attach storage metadata to session


15. Send StatusMessage { state: "streaming", elapsed_s: 0.0 }

┌─────────────────────────────────────────────────────────────────┐
│ Phase 5: gRPC Streaming (variable, depends on audio duration)   │
└─────────────────────────────────────────────────────────────────┘

16. Update session status to PROCESSING
    └─ store.update_status(session_id, SessionStatus.PROCESSING)

17. Create StreamAudioClient from factory
    └─ Uses shared gRPC channel to stream-api

18. Partition audio into chunks
    ├─ iter_chunks(audio, chunk_size_bytes)
    └─ Default: 32KB chunks

19. Stream chunks to stream-api (bidirectional RPC)
    ├─ client.stream_audio(chunks) → AsyncIterator[StreamEvent]
    ├─ Each chunk → AudioFrame protobuf message
    └─ stream-api processes chunks concurrently

20. Handle upstream events:
    ├─ StreamResult: aggregator.add_result(text, is_final)
    └─ StreamFailure: handle DEADLINE_EXCEEDED gracefully, raise on other errors

21. Periodic status heartbeats (parallel task)
    ├─ Every status_update_interval_s (default: 2s)
    └─ Send StatusMessage { state: "processing", elapsed_s }

22. Wait for final transcript or timeout
    ├─ Timeout: final_result_wait_timeout_s (default: 30s)
    └─ On timeout: log warning, return best-effort result

┌─────────────────────────────────────────────────────────────────┐
│ Phase 6: Transcript Finalization (50-150ms)                     │
└─────────────────────────────────────────────────────────────────┘

23. Build aggregated transcript
    ├─ aggregator.build()
    ├─ Order segments by (sequence)
    ├─ If any finals: concatenate final segment text
    └─ Else: return latest partial text

24. Persist transcript and close session
    ├─ store.close_session(session_id, text, segments)
    ├─ Resolve status_id to CLOSED via session_status lookup
    └─ Log per-segment confidence (segments are not persisted)

25. Send TranscriptMessage { text, is_final, segments[] }
26. Send ClosedMessage { session_id, status: "closed" }
27. Close WebSocket with code 1000 (normal)
```

### Error Flow

```
On any RestApiError exception:
1. Mark session as FAILED (best-effort, non-blocking)
2. Send ErrorMessage { code, message }
3. Close WebSocket with mapped application code (4xxx or 1011)

On client disconnect:
1. Log disconnection
2. Mark session as FAILED (best-effort)
3. Exit handler

On unexpected exception:
1. Log exception with traceback
2. Mark session as FAILED
3. Send ErrorMessage { code: "internal", message: "error" }
4. Close WebSocket with code 1011
```

## Communication Patterns

### rest-api ↔ Client

**Protocol:** HTTP (session creation) + WebSocket (streaming)

**Message framing:**

- Client → server: JSON text frames (metadata, control) + binary frames (audio)
- Server → client: JSON text frames only (status, transcript, errors)

**Flow control:**

- Client paces upload (binary frames) until upload_complete signal
- Server paces status heartbeats at fixed interval
- Server sends transcript as single message when ready

**Error signaling:**

- REST: HTTP status codes (4xx, 5xx) + JSON error body
- WebSocket: ErrorMessage + application close codes (4xxx, 1011)

### rest-api ↔ stream-api

**Protocol:** gRPC (bidirectional streaming RPC)

**Service:** `AudioIngestService.StreamAudio`

**Message flow:**

```
rest-api → stream-api:  AudioFrame stream (binary audio chunks)
stream-api → rest-api:  ServerEvent stream (ack, results, errors)
```

**Event types:**

- `ServerEvent.ack`: session acknowledgement
- `ServerEvent.result`: partial transcription result
- `ServerEvent.error`: in-band error (not RPC abort)

**Error handling:**

- RPC abort (grpc.aio.AioRpcError): mapped to UPSTREAM_STREAM_FAILURE
- DEADLINE_EXCEEDED error event: treated as best-effort (expected while inference unbuilt)
- Other error events: mapped to UPSTREAM_STREAM_FAILURE

**Channel lifecycle:**

- Single shared insecure channel created at startup
- Channel closed during app shutdown
- Per-request stub instances (cheap, no connection overhead)

### rest-api ↔ PostgreSQL

**Protocol:** PostgreSQL wire protocol via asyncpg (SQLAlchemy async)

**Connection pooling:** Managed by SQLAlchemy AsyncEngine

**Transactions:**

- Session creation: single INSERT
- Status updates: single UPDATE
- Session closure: UPDATE sessions + bulk INSERT segments (transactional)

**Queries:**

- By session_id (primary key): O(1) index lookup
- No complex joins or aggregations in hot path

### rest-api ↔ MinIO/S3

**Protocol:** S3 API via aioboto3 (async boto3)

**Operations:**

- `put_object`: upload audio file (single-part upload, synchronous within request)
- `head_bucket`: check bucket existence at startup
- `create_bucket`: auto-create bucket if missing

**Concurrency:** Each request uses a new client session (context manager)

## Performance Characteristics

### Latency Breakdown (Typical 60s Audio File, ~10MB)

| Phase                           | Operation               | Estimated Time                   |
| ------------------------------- | ----------------------- | -------------------------------- |
| Session creation                | DB insert + JWT sign    | 10-50ms                          |
| WebSocket auth                  | JWT verify + DB lookup  | 10-30ms                          |
| Metadata validation             | JSON parse + comparison | 1-5ms                            |
| Audio upload                    | 10MB over WebSocket     | 100-500ms (network dependent)    |
| S3 upload                       | MinIO PUT 10MB          | 50-200ms                         |
| DB status update                | Single UPDATE           | 5-20ms                           |
| Audio chunking                  | Partition 10MB @ 32KB   | 1-5ms (in-memory)                |
| gRPC streaming                  | Transmit ~312 chunks    | 100-300ms (chunk rate dependent) |
| Transcript aggregation          | Build from segments     | 1-5ms                            |
| DB close + segments             | UPDATE + bulk INSERT    | 20-100ms                         |
| **Total (excluding inference)** |                         | **~0.3-1.2s**                    |

**Inference processing time (estimated):**

- Assumption: 1 second of audio = 1ms processing time
- 60-second audio file = ~60ms inference time
- 300-second audio file = ~300ms inference time

**End-to-end for 60s audio:** ~0.4-1.3s (wrapper overhead + inference)

### Throughput Capacity

**Single instance limits:**

**CPU-bound:**

- Audio chunking: ~1000 MB/s (negligible, pure memory slicing)
- JSON serialization/deserialization: ~100 req/s per core
- JWT signing/verification: ~500 ops/s per core

**I/O-bound:**

- PostgreSQL connection pool: ~100 concurrent connections (configurable)
- MinIO/S3 uploads: ~50-100 concurrent PUTs (network/storage dependent)
- gRPC channel: ~1000 concurrent streams (configurable)
- WebSocket connections: ~10,000 concurrent connections (OS dependent)

**Memory-bound:**

- Audio buffer per session: max_upload_bytes (default: 100MB)
- 1000 concurrent uploads: ~100GB RAM (worst case)
- Typical: 1GB RAM per 100 concurrent sessions (10MB avg file size)

**Practical capacity (single instance, 8 CPU cores, 16GB RAM):**

- Concurrent WebSocket sessions: ~100-200
- Session creation rate: ~400-800 req/s
- Audio upload throughput: ~500MB/s aggregate (network limited)

### Bottleneck Analysis

**Likely bottlenecks (in order):**

1. **PostgreSQL connection pool exhaustion**
   - Symptom: `PoolTimeout` errors under high load
   - Mitigation: Increase pool size, optimize query efficiency, add connection pooling proxy (pgBouncer)

2. **MinIO/S3 upload latency**
   - Symptom: Slow upload phase, client timeouts
   - Mitigation: Increase storage throughput, use multi-part uploads for large files, add CDN/edge caching

3. **Memory pressure from concurrent uploads**
   - Symptom: OOM kills, swap thrashing
   - Mitigation: Reduce max_upload_bytes, implement streaming upload (chunked transfer), add backpressure

4. **gRPC channel saturation**
   - Symptom: Slow stream initiation, queue buildup
   - Mitigation: Increase channel concurrency limits, use multiple channels (load balancing), add gRPC connection pooling

5. **WebSocket connection limits**
   - Symptom: Connection refused, accept errors
   - Mitigation: Increase OS file descriptor limits, tune kernel TCP parameters, add load balancer

## Load Scenarios & Issues

### Scenario 1: Flash Crowd (1000 concurrent session creations)

**Expected behavior:**

- Database connection pool saturates (~100 concurrent inserts)
- Remaining requests queue in Uvicorn worker pool
- Latency increases to ~1-5s per session creation

**Issues:**

- Request timeouts if queue depth exceeds worker pool size
- Potential database lock contention on sessions table

**Mitigations:**

- Add database connection pooling proxy (pgBouncer)
- Horizontal scaling (multiple rest-api instances)
- Rate limiting at load balancer

### Scenario 2: Sustained High Upload Rate (500 concurrent uploads @ 10MB each)

**Expected behavior:**

- Memory usage: ~5GB (buffered audio)
- MinIO/S3 upload queue builds up
- Increased latency in Phase 4 (storage)

**Issues:**

- MinIO/S3 backend overload (disk I/O saturation)
- Memory pressure leading to OOM
- Client timeout during upload phase

**Mitigations:**

- Implement streaming upload (chunked S3 multipart)
- Reduce max_upload_bytes to limit memory footprint
- Add backpressure signaling to clients (slow down upload rate)
- Scale MinIO/S3 horizontally (distributed storage cluster)

### Scenario 3: Large File Uploads (100MB+ files)

**Expected behavior:**

- Single session consumes entire max_upload_bytes
- S3 upload time increases to 1-5s
- gRPC chunking produces ~3000+ chunks

**Issues:**

- WebSocket timeout during upload
- S3 single-part upload size limits (5GB max)
- Increased chunk transmission latency to stream-api

**Mitigations:**

- Increase WebSocket timeout configuration
- Implement S3 multipart upload for files > 100MB
- Increase chunk_size_bytes to reduce chunk count
- Add upload progress feedback to client

### Scenario 4: Inference Pipeline Lag (10s processing delay)

**Expected behavior:**

- WebSocket sessions remain open longer (10s+ per session)
- Concurrent connection count increases
- Periodic status heartbeats continue

**Issues:**

- Connection limit exhaustion (OS file descriptors)
- Increased memory usage (connection state overhead)
- Client impatience (perceived slow response)

**Mitigations:**

- Increase final_result_wait_timeout_s
- Optimize status_update_interval_s for better UX
- Add explicit progress indicators (% complete based on chunk count)
- Implement asynchronous processing (return 202, poll for result)

### Scenario 5: Database Failure / Connectivity Loss

**Expected behavior:**

- All session creations fail immediately
- In-flight sessions cannot update status or close
- Error messages sent to clients

**Issues:**

- Transcript data loss for in-flight sessions
- Session state inconsistency (audio in S3, no DB record update)
- No automatic retry/recovery

**Mitigations:**

- Implement database connection retry with exponential backoff
- Add circuit breaker pattern for DB operations
- Implement write-ahead log for critical state transitions
- Add reconciliation job to recover orphaned sessions

## Suggested Improvements

### Short-Term (Low Complexity, High Impact)

1. **Implement streaming upload to S3**
   - Replace in-memory buffering with chunked transfer encoding
   - Use S3 multipart upload API for files > 10MB
   - Reduces memory footprint by 90%+ under load

2. **Add connection pool monitoring**
   - Expose Prometheus metrics for DB pool size, queue depth, wait time
   - Add alerting on pool exhaustion thresholds
   - Enables proactive scaling decisions

3. **Implement request-level timeouts**
   - Add configurable timeout for each phase (upload, storage, streaming)
   - Prevents resource leaks from hung connections
   - Improves error visibility

4. **Add structured logging for performance metrics**
   - Log phase durations: upload_duration_ms, storage_duration_ms, streaming_duration_ms
   - Enable performance regression detection
   - Facilitates capacity planning

5. **Implement graceful degradation for S3 failures**
   - Allow session to continue even if S3 upload fails (log error, continue streaming)
   - Prevents cascade failures

### Medium-Term (Moderate Complexity, High Impact)

6. **Decouple upload from transcription**
   - Accept audio upload, return 202 Accepted immediately
   - Process transcription asynchronously (background worker pool)
   - Client polls `GET /v1/sessions/{session_id}` for status/transcript
   - Reduces WebSocket connection time from minutes to seconds

7. **Implement rate limiting**
   - Per-client rate limits on session creation (e.g., 10/min)
   - Global rate limiting on concurrent uploads (e.g., 500)
   - Prevents abuse and ensures fair resource allocation

8. **Add database read replicas**
   - Route `get_session` queries to read replicas
   - Reduces load on primary database
   - Improves session creation throughput

9. **Implement gRPC channel pool**
   - Use multiple channels to stream-api for load distribution
   - Round-robin or least-loaded channel selection
   - Reduces channel saturation risk

10. **Add resume support for failed uploads**
    - Generate resumable upload token with partial upload metadata
    - Client can resume from last successful chunk
    - Improves UX for large files over unreliable networks

### Long-Term (High Complexity, High Impact)

11. **Implement horizontal auto-scaling**
    - Deploy rest-api as stateless service behind load balancer
    - Scale based on CPU, memory, or connection count metrics
    - Requires session affinity or shared state (Redis)

12. **Add edge caching for S3 uploads**
    - Use CDN with S3 backend for distributed upload ingestion
    - Reduces latency for geographically distributed clients
    - Requires signed upload URLs (presigned S3 URLs)

13. **Implement event-driven architecture**
    - Use message queue (RabbitMQ/Kafka) between upload and streaming
    - Decouples upload service from streaming service
    - Enables independent scaling and fault isolation

14. **Add distributed tracing**
    - Instrument with OpenTelemetry for end-to-end request tracing
    - Trace ID propagation across rest-api → stream-api → inference
    - Enables detailed performance debugging

15. **Implement transcript caching**
    - Cache completed transcripts in Redis (keyed by audio hash)
    - Detect duplicate uploads, return cached result
    - Reduces inference load for re-uploads

## Monitoring & Observability

### Key Metrics to Track

**Request metrics:**

- Session creation rate (req/s)
- Active WebSocket connections (gauge)
- Session completion rate (req/s)
- Error rate by error key (failures/s)

**Latency metrics:**

- Session creation latency (p50, p95, p99)
- Upload phase duration (p50, p95, p99)
- Storage upload duration (p50, p95, p99)
- gRPC streaming duration (p50, p95, p99)
- End-to-end session duration (p50, p95, p99)

**Resource metrics:**

- Memory usage (RSS, heap, buffers)
- Database connection pool (active, idle, waiting)
- gRPC channel active streams (gauge)
- S3 client active requests (gauge)

**Business metrics:**

- Total sessions created (counter)
- Total audio bytes uploaded (counter)
- Total transcripts generated (counter)
- Average audio file size (gauge)
- Average transcript length (gauge)

### Alerting Thresholds

- Session creation error rate > 5%: Critical
- Database connection pool utilization > 80%: Warning
- Memory usage > 90%: Warning
- Active WebSocket connections > 1000: Warning
- p95 end-to-end latency > 30s: Warning

## Adherence to Project Standards

This architecture follows the patterns defined in `docs/contributor/engineering-standards.md`:

**Configuration:** Frozen dataclass with `from_env()`, fail-fast validation

**Error handling:** Typed error keys, structured logging, no silent failures

**Service isolation:** No cross-service imports, gRPC-only communication with stream-api

**Type safety:** Full type hints, modern syntax (`X | Y`), Pydantic schemas for external contracts

**Logging:** Structured logging with `extra={}`, per-module logger via `__name__`

**Testing:** 80%+ coverage (unit + integration tests in `tests/`)

**Protocol Buffers:** Vendored proto, generated stubs, never manually edited

**Database:** Async SQLAlchemy, Alembic migrations, transactional consistency

## Related Documentation

- Consumer API guide: `docs/consumer/rest-api-guide.md`
- Service README: `services/rest-api/README.md`
- Service docs: `docs/contributor/services/rest-api/README.md`
- Engineering standards: `docs/contributor/engineering-standards.md`
- Architecture boundaries: `docs/contributor/architecture-boundaries.md`
