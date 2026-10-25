from __future__ import annotations

from enum import Enum

SAMPLE_RATE_16KHZ = 16_000
BYTES_PER_16BIT = 2
MONO_CHANNELS = 1


class ModelNames(Enum):
    WHISPER = "whisper"
    PYANNOTE = "pyannote"

    PYANNOTE_SEGMENTATION = "pyannote-segmentation-python"
    PYANNOTE_EMBEDDING = "pyannote-embedding-python"


TRITON_INPUT_DATA_TYPE = "FP32"
TRITON_INPUT_LAYER_NAME = "audio"

DEFAULT_MAX_GAP_FRAME: int = 8
DEFAULT_SPEAKER: int = 0

# Embedding building

DEFAULT_OFFSET: float = 0.0
DEFAULT_MIN_DURATION: float = 0.5
DEFAULT_SCORE_THRESHOLD: float = 0.4

# Triton outputs

SEGMENTATION_OUTPUT_NAME = "segments"
EMBEDDING_OUTPUT_NAME = "embeddings"

# Redis stream/group constants
GROUP_START_NEW_ENTRIES = "$"
GROUP_START_ALL_ENTRIES = "0"
BUSYGROUP_TOKEN = "BUSYGROUP"
READ_NEW_MESSAGES_ID = ">"

# Redis stream reply tuple indices
STREAM_REPLY_KEY_INDEX = 0
STREAM_REPLY_ENTRIES_INDEX = 1
ENTRY_ID_INDEX = 0
ENTRY_FIELDS_INDEX = 1
