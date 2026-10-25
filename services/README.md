# Services Folder

This folder contains isolated runtime services.

## Services

- `stream-api`: implemented ingestion and result-routing service
- `inference-adapter`: scaffold for audio adaptation and normalization responsibilities
- `inference`: scaffold for model inference responsibilities
- `synchronizer`: scaffold for output synchronization responsibilities

## Where To Read More

- Canonical contributor service docs: `../docs/contributor/services/README.md`
- Consumer contract docs: `../docs/consumer/README.md`

## Rule Reminder

Services must not cross-import each other. Use explicit interfaces (gRPC/queue) between services.
