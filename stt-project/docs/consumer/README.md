# Consumer Docs

Last verified: 2026-05-18
Audience: External integrators, API consumers

This section documents the runtime contracts and behaviors consumers rely on.

## Pages

- `stream-api-proto-guide.md`: stream-api gRPC contract ownership, event flow, and compatibility policy.
- `rest-api-guide.md`: rest-api REST + WebSocket endpoints, request/response schemas, WebSocket protocol, and session persistence model.

## Scope Rules

Include:
- Contract semantics
- Message flow expectations
- Error and durability behavior visible to clients

Do not include:
- Internal coding standards
- Monorepo contribution workflow
- Internal implementation details not visible at the contract boundary
