# REST API ICD

Last verified: 2026-06-29
Audience: client/frontend developers

This document describes the current public contract of the `rest-api` service.

## Transport

- HTTP: REST endpoint for token issuance
- Realtime: Socket.IO v4 (`/socket.io`)

## 1. Authorize Endpoint

### `POST /v1/authorize/{user_id}`

Issues a short-lived JWT used for Socket.IO authentication.

Request:

- Method: `POST`
- Path parameter: `user_id` (string)
- Body: none

Response (`201 Created`):

```json
{
  "token": "<jwt>",
  "expires_at": "2026-06-29T12:00:00Z"
}
```

Fields:

- `token`: JWT token string
- `expires_at`: ISO-8601 timestamp

## 2. Socket.IO Connect

Connect with auth payload:

```json
{
  "token": "<jwt>",
  "user_id": "alice"
}
```

Connection may be rejected with one of:

- `missing auth`
- `invalid_token`
- `token_expired`
- `token_user_mismatch`

## 3. Client -> Server Socket.IO Events

### `upload`

Starts processing for one audio payload.

Payload:

```json
{
  "participant_ids": ["alice"],
  "meeting_type_id": 1,
  "channels": 1,
  "sample_width": 2,
  "sample_rate": 16000,
  "audio": "<binary bytes>"
}
```

Validation rules:

- `participant_ids`: non-empty array of non-empty strings
- `meeting_type_id`: integer >= 1
- `channels`: integer >= 1
- `sample_width`: integer >= 1
- `sample_rate`: integer >= 1
- `audio`: required bytes/bytearray

Acknowledgement payload (Socket.IO callback return):

```json
{ "session_id": "<uuid>" }
```

If audio is missing/invalid, server emits an `error` event and returns:

```json
{ "session_id": "" }
```

### `restore_session`

Rejoins a session room and returns current persisted snapshot.

Payload:

```json
{ "session_id": "<uuid>" }
```

Acknowledgement success payload:

```json
{
  "session_id": "<uuid>",
  "status": "created|streaming|processing|closed|failed",
  "text": "<nullable transcript text>",
  "created_at": "<iso8601>",
  "updated_at": "<iso8601>"
}
```

Acknowledgement error payloads:

```json
{ "error": "missing_session_id" }
```

```json
{ "error": "session_not_found" }
```

## 4. Server -> Client Socket.IO Events

### `accepted`

Emitted once upload metadata is accepted and session is created.

```json
{ "session_id": "<uuid>" }
```

### `status`

Periodic heartbeat while processing.

```json
{ "state": "processing", "elapsed_s": 1.234 }
```

### `transcript`

Final aggregated transcript.

```json
{ "text": "..." }
```

Notes:

- No `is_final` field is emitted to clients.
- No segments array is emitted to clients.

### `summary`

Summarization payload.

- On success: emits the summarizer JSON object as-is (no fixed schema enforced by API layer).
- For test purposes in this repo, payload includes `text`.

Success example:

```json
{ "text": "meeting summary" }
```

Failure example:

```json
{ "error": "<reason>" }
```

### `closed`

Session completion/closure.

```json
{ "session_id": "<uuid>", "status": "closed" }
```

### `error`

Terminal processing/auth/validation error.

```json
{ "code": "<error_code>", "message": "<human-readable message>" }
```

## 5. Event Order (Typical Happy Path)

1. Client: `upload`
2. Server: `accepted`
3. Server: zero or more `status`
4. Server: `transcript`
5. Server: `summary`
6. Server: `closed`

## 6. Notes

- Binary audio is transported in the `upload` payload (`audio` field).
- Session IDs are generated server-side.
- Server joins the socket to a room named by `session_id`.
