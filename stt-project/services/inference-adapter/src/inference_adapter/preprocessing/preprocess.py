from __future__ import annotations

import numpy as np

from stt_common.constants import (
    MONO_CHANNELS,
    BYTES_PER_16BIT,
    SAMPLE_RATE_16KHZ,
)

from stt_common.audio import dtype_mapping, vad_collector, normalize_audio, calc_bytes_per_ms


class NumpyAudioBuffer:
    def __init__(self):
        self.buffer = self._init_buffer()
        self.offset = 0

    def append(self, audio: np.ndarray):
        # TODO: np.concatenate is of O(n²) time complexity
        # 		set buffer as list of chunks, and concatenate
        # once the whole audio is needed
        # implement get_buffer function, that concats when invoked.
        self.buffer = np.concatenate([self.buffer, audio])

    def _init_buffer(self) -> np.ndarray:
        return np.array([], dtype=np.float32)

    def flush_buffer(self):
        self.buffer = self._init_buffer()
        self.offset = 0

    def truncate_buffer(self, start=0, end=None, step=None):
        self.buffer = self.buffer[start:end:step]
        self.offset += start


class Preprocessor:
    def __init__(self, output_dtype=np.float32):
        self.output_dtype = output_dtype

    def __call__(
        self,
        audio_bytes: bytes,
        channels: int = MONO_CHANNELS,
        sample_width: int = BYTES_PER_16BIT,
        sample_rate: int = SAMPLE_RATE_16KHZ
    ) -> np.ndarray | None:
        return self.preprocess(
            audio_bytes=audio_bytes,
            channels=channels,
            sample_width=sample_width,
            sample_rate=sample_rate,
        )

    def preprocess(
        self,
        audio_bytes: bytes,
        channels: int = MONO_CHANNELS,
        sample_width: int = BYTES_PER_16BIT,
        sample_rate: int = SAMPLE_RATE_16KHZ,
    ) -> np.ndarray | None:
        # Canonicalize input first so VAD always runs on mono 16kHz PCM16 frames.
        normalized_audio = normalize_audio(
            audio_bytes=audio_bytes,
            channels=channels,
            sample_width=sample_width,
            sample_rate=sample_rate,
            output_dtype=self.output_dtype
        )

        audio_type = dtype_mapping[sample_width]
        info = np.iinfo(audio_type)

        pcm16_bytes = (normalized_audio * info.max).astype(audio_type).tobytes()

        bytes_per_ten_ms = calc_bytes_per_ms(
            sample_rate=SAMPLE_RATE_16KHZ,
            sample_width=BYTES_PER_16BIT,
            channels=MONO_CHANNELS,
        )

        vad_mask = vad_collector(
            chunk=pcm16_bytes,
            bytes_per_ten_ms=int(bytes_per_ten_ms),
            sample_rate=SAMPLE_RATE_16KHZ,
        )

        sample_mask = vad_mask.reshape(-1, BYTES_PER_16BIT).all(axis=1)
        filtered_audio = normalized_audio[sample_mask]

        if filtered_audio.size == 0:
            return None

        return filtered_audio.astype(self.output_dtype, copy=False)
