from __future__ import annotations

import numpy as np
from webrtcvad import Vad

from stt_common.constants import MONO_CHANNELS, BYTES_PER_16BIT, SAMPLE_RATE_16KHZ

VAD_MS = [10, 20, 30]
TEN_MS = 10 / 1000
SUPPORTED_VAD_SAMPLE_RATES = (8000, 16000, 32000, 48000)

vad = Vad(2)

dtype_mapping = {1: np.int8, 2: np.int16, 4: np.int32}


def resample_audio(audio: np.ndarray, sample_rate: int, output_dtype):
    old_indices = np.arange(audio.shape[0], dtype=output_dtype)
    new_length = int(round(audio.shape[0] * SAMPLE_RATE_16KHZ / sample_rate))
    new_indices = np.linspace(0, audio.shape[0] - 1, new_length, dtype=output_dtype)
    audio = np.interp(new_indices, old_indices, audio).astype(output_dtype)

    return audio


def normalize_audio(
    audio_bytes: bytes,
    channels: int = MONO_CHANNELS,
    sample_width: int = BYTES_PER_16BIT,
    sample_rate: int = SAMPLE_RATE_16KHZ,
    output_dtype = np.float32
) -> np.ndarray:
    """

    Args:
            audio_bytes (bytes): Raw PCM audio bytes.
            channels (int, optional): Number of channels in the PCM stream. Defaults to 1.
            sample_width (int, optional): Bytes per sample (e.g. 2 for int16 PCM). Defaults to 2.
            sample_rate (int, optional): Sample rate (Hz). Defaults to 16kHz.

    Raises:
            ValueError: Raises this error if the sample width isn't supported

    Returns:
            np.ndarray: returns the audio as ndarray float32 format.
    """

    # Assuming 16-bit PCM, adjust if audio is different
    # How to know which dtype to use? check the sample_width from the incoming audio
    # sample_width is in bytes, and the dtype in bits.
    # 16-bit PCM is calculated using sample_width x 8 (8 bits per byte)
    if sample_width not in dtype_mapping:
        supported_sample_widths = list([str(supported_width) for supported_width in dtype_mapping.keys()])
        supported_values = ",".join(supported_sample_widths)
        err_msg = f"Unsupported sample width: {sample_width} (supported values are {supported_values})"
        raise ValueError(err_msg)
    audio_type = dtype_mapping[sample_width]

    info = np.iinfo(audio_type)
    abs_max = max(info.max, abs(info.min))

    # audio is a 1D array of dtype-bit signed integers.
    # after this line, each number is of (dtype) bytes.
    audio = np.frombuffer(audio_bytes, dtype=audio_type)

    # If the audio has multiple channels, reshape and average to mono
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=-1)

    # to normalize to [-1.0, 1.0) range,
    # divide by the max absolute value of the min and max of the dtype.
    audio = audio.astype(output_dtype) / abs_max

    if sample_rate != SAMPLE_RATE_16KHZ:
        audio = resample_audio(
            audio,
            sample_rate=sample_rate,
            output_dtype=output_dtype
        )

    return audio


def calc_bytes_per_ms(
    sample_rate: int, sample_width: int, channels: int, ms: float = TEN_MS, int_flag: bool = True
) -> float | int:
    r"""
    According to the forumal of duration (in seconds) as a function of the audio bytes.
    sample rate, sample width and channels we get

    .. math:: duration = \frac{bytes}{sr \cdot sw \cdot ch}

    s.t.
            sr - sample rate
            sw - sample width
            ch - channels
    """

    bpms = ms * sample_rate * sample_width * channels

    if int_flag:
        return int(bpms)
    return bpms


def vad_collector(chunk: bytes, bytes_per_ten_ms: int, sample_rate: int = SAMPLE_RATE_16KHZ):
    if sample_rate not in SUPPORTED_VAD_SAMPLE_RATES:
        supported_values = ", ".join(str(rate) for rate in SUPPORTED_VAD_SAMPLE_RATES)
        err_msg = f"Unsupported sample rate: {sample_rate} (supported values are {supported_values})"
        raise ValueError(err_msg)

    ret = []

    for frame_idx in range(0, len(chunk), bytes_per_ten_ms):
        frame = chunk[frame_idx : min(frame_idx + bytes_per_ten_ms, len(chunk))]
        padded_frame = frame + b"\x00" * (bytes_per_ten_ms - len(frame))

        # each approval is for 10ms frame,
        # i.e.,
        # sr x sw x ch x 10ms samples.
        # in other words, bytes_per_ten_ms
        frame_approval = vad.is_speech(padded_frame, sample_rate)
        ret.extend([frame_approval] * len(frame))
    return np.array(ret, dtype=bool)
