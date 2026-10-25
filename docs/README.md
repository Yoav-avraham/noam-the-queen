# Documentation Hub

Last verified: 2026-05-18
Audience: All

This repository uses two canonical documentation spaces:

- `consumer/` for external integrators and client-facing contracts.
- `contributor/` for engineers and AI coding agents working in this monorepo.

## Start Here

- Obsidian vault landing note: `home.md`
- Consumer integration path: `consumer/README.md`
- Contributor engineering path: `contributor/README.md`
- Service-local navigation in code folders: `services/*/README.md`, `common/README.md`

## Documentation Rules

1. Canonical docs live under `docs/`.
2. Local folder `README.md` files are navigation aids, not policy copies.
3. All docs pages use lowercase kebab-case filenames.
4. The only uppercase filename exception is `README.md`.

## Readability Limits

- Canonical page target: 120 to 220 lines.
- Canonical split threshold: 280 lines.
- README target: 40 to 90 lines.
- README split/link-out threshold: 120 lines.

If a page grows past limits, split by topic and keep an index page.

## Update Triggers

Update docs when any of the following changes:

- Protocol buffer contracts or gRPC behavior
- Service boundaries or import-linter constraints
- Runtime commands, setup flow, or environment variables
- Reliability/error-handling behavior visible to consumers

## Ownership

- Contributor standards and workflow: engineering maintainers
- Consumer contract docs: stream-api maintainers
- Service capability pages: owners of each service directory
