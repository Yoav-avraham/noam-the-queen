# Rest API Service

## Folder Purpose

REST + Socket.IO wrapper that fronts the stream-api gRPC pipeline. It creates and
persists transcription sessions, accepts uploaded audio via a Socket.IO event,
archives it to object storage (MinIO/S3), partitions and streams it to stream-api,
aggregates the transcription results, and returns the final transcript.

## Key Paths

The package is organized into focused subpackages under `src/rest_api/`:

- API layer (HTTP/WS): `api/routes/`, `api/schemas.py`, `api/stream_handler.py`
- Pipeline (stream-api gRPC client, chunking, aggregation): `pipeline/`
- Persistence (engine, models, store): `db/`
- Object storage: `storage/`
- Signed tokens: `security/`
- Domain types + error contract: `domain/`
- App wiring + entrypoint: `app.py`, `context.py`, `server.py`, `config.py`
- Proto client stubs: `proto/audio_ingest.proto` (vendored copy), generated into `src/rest_api/proto/`
- Database migrations: `migrations/` (Alembic)
- Tests (mirror the source layout): `src/rest_api/tests/`

## API Surface

### HTTP

- `POST /v1/authorize/{user_id}` — issue a signed JWT bound to the user.
  Returns `{ token, expires_at }`.

### Socket.IO (client → server)

- `upload` — `{ participant_ids, meeting_type_id, audio (bytes) }`: creates a
  session, archives audio, streams to stream-api, emits results back.
  Acknowledges with `{ session_id }`.
- `restore_session` — `{ session_id }`: rejoins a session room after reconnect;
  returns current state or an error.

### Socket.IO (server → client)

- `accepted` — `{ session_id }`: session persisted, processing started.
- `status` — `{ state, elapsed_s }`: periodic heartbeat.
- `transcript` — `{ text, is_final, segments }`: final transcription result.
- `closed` — `{ session_id, status }`: session closed; last event before disconnect.
- `error` — `{ code, message }`: processing failure.

### Auth flow

1. Client calls `POST /v1/authorize/{user_id}` → receives JWT.
2. Client connects Socket.IO with `auth: { token, user_id }`.
3. Server verifies signature, expiry, and user match.

See the consumer guide for full details: `../../docs/consumer/rest-api-guide.md`.

## Architecture Note

rest-api is forbidden by `import-linter` from importing `stream_api` (or any other
service). It communicates with stream-api strictly over gRPC, using its own
generated stubs from a vendored copy of `audio_ingest.proto`. Keep that copy in
sync with the stream-api source of truth.

> The downstream inference pipeline (inference-adapter / synchronizer) is still a
> scaffold, so stream-api currently returns no final transcription. The wrapper
> handles this gracefully: on the upstream final-result timeout it returns a
> best-effort (often empty) transcript and still closes the session.

## Local Development

```bash
# Bring up dependencies (Postgres, MinIO, Redis, stream-api).
docker compose up -d postgres minio redis stream-api

# Apply database migrations.
cd services/rest-api
DATABASE_URL=postgresql+asyncpg://dev_user:dev_password@localhost:5432/stt_db \
  alembic upgrade head

# Run the service.
REST_API_TOKEN_SECRET=local-dev-secret \
  uv run --package stt-rest-api python -m rest_api
```

### Regenerating proto stubs

```bash
cd services/rest-api
python -m grpc_tools.protoc -I proto \
  --python_out=src/rest_api/proto \
  --grpc_python_out=src/rest_api/proto \
  --pyi_out=src/rest_api/proto \
  proto/*.proto
```

## Documentation

- Consumer guide (schemas, Socket.IO protocol, DB schema): `../../docs/consumer/rest-api-guide.md`
- Contributor service docs: `../../docs/contributor/services/rest-api/README.md`
- Contributor standards: `../../docs/contributor/engineering-standards.md`
