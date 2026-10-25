# Synchronizer Key Files and Functions

Last verified: 2026-06-15

## Runtime Modules

- `services/synchronizer/src/synchronizer/types.py`
  - Transcript merge contract:
    - `MergedTranscript`

- `services/synchronizer/src/synchronizer/server.py`
  - `configure_process`
    - Initializes logging and i18n catalogs for the running process.
  - Uses `SynchronizerConfig.from_env`
    - Loads Redis URL and optional consumer-group override.
  - `build_stream_handler`
    - Adapts synchronizer transcript merge logic to the shared `StreamManager` handler contract.
  - `serve`
    - Composes `StreamManager` with `TranscriptMerger` and starts the runtime.
  - `main`
    - Synchronous process entrypoint around `asyncio.run`.

- `common/src/stt_common/contracts.py`
  - `TritonOutputWindowContent`
    - Input `WindowPayload.content` contract for `StreamName.TRITON_OUTPUT`.
  - `FinalOutputWindowContent`
    - Output `WindowPayload.content` contract for `StreamName.FINAL_OUTPUT`.

- `services/synchronizer/src/synchronizer/transcript_merger.py`
  - `TranscriptMerger.merge_window`
    - Merges a resolved window into python-i18n-localized, speaker-labeled text
      (Hebrew default), retaining per-session boundary state for cross-window
      continuation suppression.

## Runtime Contracts

- Session ingestion, publish ordering, message acking, and lease renewal are owned by the shared `StreamManager`.
- Synchronizer-specific output content is only the merged transcript text.
- Transcript merging preserves per-session speaker continuation state across windows until `is_final`.

## Tests

- `services/synchronizer/src/synchronizer/tests/test_server.py`
  - Server composition, environment loading, and stream-handler wiring.
- `services/synchronizer/src/synchronizer/tests/test_transcript_merger.py`
  - Merge correctness, speaker labeling, python-i18n localization (Hebrew default),
    continuation suppression, and edge cases.
