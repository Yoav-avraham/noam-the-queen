# Synchronizer Service

Last verified: 2026-06-15
Path: `services/synchronizer`

## Purpose

Coordinates and aligns outputs across pipeline components for real-time response delivery.

Planned focus:
- Redis Streams consumer-group ingestion with reliability semantics.
- Session state and buffering/context handling.
- Async Triton gRPC client integration path.
- Result parsing and timestamp/speaker alignment.

## Current State

- `server.py` composes the shared `StreamManager` with synchronizer-specific
  transcript merging.
- Transcript merge and output enrichment are implemented: resolved windows
  are merged into localized, speaker-labeled text before publish.
- The only synchronizer-specific shared type is
	`services/synchronizer/src/synchronizer/types.py` (`MergedTranscript`).
- Stream-stage payload content contracts are shared in
	`common/src/stt_common/contracts.py`:
	- `TritonOutputWindowContent` (incoming from `StreamName.TRITON_OUTPUT`)
	- `FinalOutputWindowContent` (outgoing to `StreamName.FINAL_OUTPUT`)
- Transcript merge logic lives at service root in
	`services/synchronizer/src/synchronizer/transcript_merger.py`.

## Key Paths

- Source: `services/synchronizer/src`
- Tests: `services/synchronizer/src/synchronizer/tests`

## Service Detail Pages

- `key-files-and-functions.md`
	- Quick map of synchronizer runtime modules, key interfaces, and responsibilities.

Key modules:
- `services/synchronizer/src/synchronizer/config.py`: frozen runtime config (`SynchronizerConfig.from_env`).
- `services/synchronizer/src/synchronizer/server.py`: runtime composition, config loading, and process entrypoint.
- `services/synchronizer/src/synchronizer/transcript_merger.py`: window merge, python-i18n-backed speaker labeling (Hebrew default), and cross-window continuation suppression.
- `services/synchronizer/src/synchronizer/types.py`: `MergedTranscript`.

## Notes

- Add contract and runtime pages in this folder as synchronizer interfaces become concrete.
- Keep this page high-level while runtime behavior remains small and server-driven.
