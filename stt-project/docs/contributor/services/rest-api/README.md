# Rest API Service

Last verified: 2026-06-12
Path: `services/rest-api`

## Purpose

Provides a REST + WebSocket front end over the stream-api gRPC pipeline. It
creates and persists transcription sessions in PostgreSQL, archives uploaded audio
to object storage (MinIO/S3), partitions and streams the audio to stream-api,
aggregates the returned transcription partials, and returns a final transcript.

## Current Capabilities

### HTTP

- `POST /v1/authorize/{user_id}`: issues a signed JWT (HS256) bound to the
  user. Returns `{ token, expires_at }`. No request body.

### Socket.IO (client → server)

- `upload` — payload `{ participant_ids, meeting_type_id, audio }`: creates a
  session, archives audio to S3, streams chunks to stream-api over gRPC,
  and emits results back. Acknowledges with `{ session_id }`.
- `restore_session` — payload `{ session_id }`: rejoins an existing session
  room after reconnect; returns accumulated state or an error.

### Socket.IO (server → client)

- `accepted` — `{ session_id }`: session persisted, processing started.
- `status` — `{ state, elapsed_s }`: periodic heartbeat (~2 s).
- `transcript` — `{ text, is_final, segments }`: final transcription result.
- `closed` — `{ session_id, status }`: session marked closed; last event
  before the server disconnects the client.
- `error` — `{ code, message }`: processing failure; server may disconnect.

### Auth flow

1. Client calls `POST /v1/authorize/{user_id}` → receives JWT.
2. Client connects Socket.IO with `auth: { token, user_id }`.
3. Server verifies signature, expiry, and `sub == user_id`.

### Best-effort behavior

While the inference pipeline is unbuilt, on the upstream final-result timeout
the handler returns an empty transcript and still closes the session.

## Architecture Boundary

- rest-api may not import other service packages (enforced by `import-linter`).
- It talks to stream-api over gRPC using its own generated stubs, built from a
  vendored copy of `proto/audio_ingest.proto`. Keep that copy in sync with the
  stream-api source of truth.
- Two session identifiers exist: the rest-api UUID (canonical, in the URL and
  database).

## Service Parts

The package is split into cohesive subpackages under `src/rest_api/`:

- `api/` — HTTP/WS surface: `routes/authorization.py`, `routes/stream.py`, `schemas.py`, `stream_handler.py`
- `pipeline/` — stream-api integration: `grpc_client.py`, `chunking.py`, `aggregator.py`
- `db/` — persistence: `engine.py`, `models.py`, `repository.py`
- `storage/` — object storage: `objects.py`
- `security/` — auth: `tokens.py`
- `domain/` — shared value types (`types.py`) and the error contract (`errors.py`)
- App + bootstrap (composition root): `app.py`, `server.py`, `context.py`
- Config: `config.py` (`REST_API_*` env prefix; shared `DATABASE_URL`)
- Migrations: `migrations/` (Alembic, async)
- Tests: `src/rest_api/tests`

## Operations

Environment variables (selected):

| Variable                               | Default                                                            | Purpose                                         |
| -------------------------------------- | ------------------------------------------------------------------ | ----------------------------------------------- |
| `REST_API_HOST` / `REST_API_PORT`      | `0.0.0.0` / `8080`                                                 | Bind address.                                   |
| `REST_API_STREAM_API_TARGET`           | `localhost:50051`                                                  | stream-api gRPC target.                         |
| `DATABASE_URL`                         | **required**                                                       | Async SQLAlchemy URL.                           |
| `REST_API_S3_ENDPOINT_URL`             | `http://localhost:9000`                                            | MinIO/S3 endpoint.                              |
| `REST_API_S3_ACCESS_KEY`              | **required**                                                       | S3/MinIO access key.                            |
| `REST_API_S3_SECRET_KEY`              | **required**                                                       | S3/MinIO secret key.                            |
| `REST_API_S3_BUCKET`                   | `stt-audio`                                                        | Audio bucket (auto-created at startup).         |
| `REST_API_TOKEN_SECRET`                | **required**                                                       | JWT signing secret.                             |
| `REST_API_TOKEN_TTL_S`                 | `3600`                                                             | Token lifetime.                                 |
| `REST_API_STATUS_UPDATE_INTERVAL_S`    | `2.0`                                                              | Status heartbeat cadence.                       |
| `REST_API_FINAL_RESULT_WAIT_TIMEOUT_S` | `30.0`                                                             | Max wait for a final transcript.                |
| `REST_API_CHUNK_SIZE_BYTES`            | `32768`                                                            | Upstream chunk size.                            |
| `REST_API_MAX_UPLOAD_BYTES`            | `104857600`                                                        | Max upload size.                                |

`DATABASE_URL`, `REST_API_TOKEN_SECRET`, `REST_API_S3_ACCESS_KEY`, and
`REST_API_S3_SECRET_KEY` are required and raise `KeyError` on startup when
unset. The service logs a warning at startup when the insecure default token
secret is in use.

## Quality Checks

```bash
ruff check --fix services/rest-api
pyright services/rest-api/src/rest_api
uv run python -m importlinter.cli
uv run -- pytest services/rest-api/src/rest_api/tests \
  --cov=services/rest-api/src/rest_api --cov-fail-under=80
```

## Documentation

- Consumer guide: `../../../consumer/rest-api-guide.md`
- Data model (ERD): `data-model.md`
- Service README: `../../../../services/rest-api/README.md`
- Architecture boundaries: `../../architecture-boundaries.md`
- Architecture flow: `../../../../services/rest-api/architecture-flow.md`
