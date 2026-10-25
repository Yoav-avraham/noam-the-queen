from __future__ import annotations

import sys
import json
import wave
import types
from typing import Any, cast
import asyncio
from pathlib import Path

import numpy as np
import pytest

try:
    import webrtcvad as _webrtcvad  # noqa: F401
except ModuleNotFoundError:
    fake_webrtcvad = types.ModuleType("webrtcvad")

    class _FallbackVad:
        def __init__(self, _mode: int):
            pass

        def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
            return True

    fake_webrtcvad.Vad = _FallbackVad  # type: ignore[attr-defined]
    sys.modules["webrtcvad"] = fake_webrtcvad

from inference_adapter.preprocessing import Preprocessor, vad_collector, normalize_audio, calc_bytes_per_ms
from inference_adapter.postprocessing import HypothesisBuffer
import inference_adapter.preprocessing.audio as audio_module
import inference_adapter.preprocessing.preprocess as preprocess_module

try:
    from inference_adapter.model_gateways import WhisperGateway
    import inference_adapter.model_gateways.whisper as whisper_module

    TRITON_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    WhisperGateway = None  # type: ignore[assignment]
    whisper_module = None  # type: ignore[assignment]
    TRITON_IMPORT_ERROR = exc


TESTS_DIR = Path(__file__).parent
WAV_PATH = TESTS_DIR / "test_data.wav"
NPY_PATH = TESTS_DIR / "test_numpy_array.txt"


def _read_wav_audio() -> tuple[bytes, int, int, int]:
    with wave.open(str(WAV_PATH), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        audio_bytes = wav_file.readframes(wav_file.getnframes())
    return audio_bytes, channels, sample_width, sample_rate


class _FakeVad:
    def __init__(self, approvals: list[bool]):
        self._approvals = approvals
        self._idx = 0

    def is_speech(self, _frame: bytes, _sample_rate: int) -> bool:
        if self._idx >= len(self._approvals):
            return self._approvals[-1]
        approval = self._approvals[self._idx]
        self._idx += 1
        return approval


class _FakeInferInput:
    def __init__(self, name: str, shape: tuple[int, ...], data_type: str):
        self.name = name
        self.shape = shape
        self.data_type = data_type
        self.data: np.ndarray | None = None

    def set_data_from_numpy(self, data: np.ndarray) -> None:
        self.data = data


class _FakeInferResult:
    def __init__(self, output_payload: list[list[object]], metadata_payload: dict[str, object]):
        self._payload = {
            "output": np.array([json.dumps(output_payload).encode("utf-8")], dtype=object),
            "metadata": np.array([json.dumps(metadata_payload).encode("utf-8")], dtype=object),
        }

    def as_numpy(self, key: str) -> np.ndarray:
        return self._payload[key]


class _FakeTritonClient:
    def __init__(self):
        self.calls: list[tuple[str, list[object]]] = []

    async def infer(self, model_name: str, inputs: list[object]) -> _FakeInferResult:
        self.calls.append((model_name, inputs))
        return _FakeInferResult(
            output_payload=[[0.0, 0.5, "hello."]],
            metadata_payload={"language": "en"},
        )


@pytest.fixture
def wav_audio() -> tuple[bytes, int, int, int]:
    return _read_wav_audio()


@pytest.fixture
def expected_numpy() -> np.ndarray:
    with open(NPY_PATH) as f:
        a = f.readlines()
    return np.array([float(e) for e in a], dtype=np.float32)


def test_calc_bytes_per_ms_for_16khz_mono_16bit() -> None:
    bytes_per_ten_ms = calc_bytes_per_ms(sample_rate=16000, sample_width=2, channels=1)
    assert bytes_per_ten_ms == 320


def test_normalize_audio_from_wav_is_float32_and_non_empty(wav_audio: tuple[bytes, int, int, int]) -> None:
    audio_bytes, channels, sample_width, sample_rate = wav_audio

    normalized = normalize_audio(
        audio_bytes=audio_bytes,
        channels=channels,
        sample_width=sample_width,
        sample_rate=sample_rate,
    )

    assert normalized.dtype == np.float32
    assert normalized.size > 0
    assert np.max(np.abs(normalized)) <= 1.0


def test_vad_collector_expands_frame_decisions_to_byte_mask(monkeypatch: pytest.MonkeyPatch) -> None:
    bytes_per_ten_ms = 8
    chunk = b"abcdefghijklmno"  # 15 bytes -> 2 frames

    monkeypatch.setattr(audio_module, "vad", _FakeVad([True, False]))
    mask = vad_collector(chunk=chunk, bytes_per_ten_ms=bytes_per_ten_ms, sample_rate=16000)

    assert mask.dtype == np.bool_
    assert mask.shape == (len(chunk),)
    assert mask[:8].all()
    assert not mask[8:].any()


def test_vad_collector_rejects_unsupported_sample_rate() -> None:
    with pytest.raises(ValueError, match="Unsupported sample rate"):
        vad_collector(chunk=b"abcdefgh", bytes_per_ten_ms=8, sample_rate=11025)


def test_preprocessor_matches_expected_numpy_when_vad_accepts_all(
    monkeypatch: pytest.MonkeyPatch,
    wav_audio: tuple[bytes, int, int, int],
    expected_numpy: np.ndarray,
) -> None:
    audio_bytes, channels, sample_width, sample_rate = wav_audio

    def _all_true_vad(*, chunk: bytes, bytes_per_ten_ms: int, sample_rate: int) -> np.ndarray:
        del bytes_per_ten_ms, sample_rate
        return np.ones(len(chunk), dtype=bool)

    monkeypatch.setattr(preprocess_module, "vad_collector", _all_true_vad)

    processed = Preprocessor().preprocess(
        audio_bytes=audio_bytes,
        channels=channels,
        sample_width=sample_width,
        sample_rate=sample_rate,
    )

    assert processed is not None
    assert processed.shape == expected_numpy.shape
    assert np.allclose(processed, expected_numpy, atol=1e-6)


def test_preprocessor_returns_none_when_vad_rejects_all(
    monkeypatch: pytest.MonkeyPatch,
    wav_audio: tuple[bytes, int, int, int],
) -> None:
    audio_bytes, channels, sample_width, sample_rate = wav_audio

    def _all_false_vad(*, chunk: bytes, bytes_per_ten_ms: int, sample_rate: int) -> np.ndarray:
        del bytes_per_ten_ms, sample_rate
        return np.zeros(len(chunk), dtype=bool)

    monkeypatch.setattr(preprocess_module, "vad_collector", _all_false_vad)

    processed = Preprocessor().preprocess(
        audio_bytes=audio_bytes,
        channels=channels,
        sample_width=sample_width,
        sample_rate=sample_rate,
    )

    assert processed is None


def test_hypothesis_buffer_promotes_shared_prefix_to_stable() -> None:
    buf = HypothesisBuffer()

    buf.insert([(0.0, 0.4, "hello"), (0.4, 0.8, "world")], offset=0.0)
    assert buf.flush() == []

    buf.insert([(0.0, 0.4, "hello"), (0.4, 0.8, "world"), (0.8, 1.1, "again")], offset=0.0)
    stable = buf.flush()

    assert stable == [(0.0, 0.4, "hello"), (0.4, 0.8, "world")]
    assert buf.complete() == [(0.8, 1.1, "again")]


def test_hypothesis_buffer_cut_uses_sentence_punctuation() -> None:
    buf = HypothesisBuffer()
    buf.stable = [(0.0, 0.4, "hello"), (0.4, 0.9, "world.")]

    audio_cut = buf.cut(offset=0.0)

    assert audio_cut == pytest.approx(0.9)


@pytest.mark.skipif(TRITON_IMPORT_ERROR is not None, reason="tritonclient dependency unavailable")
def test_whisper_gateway_infer_parses_output_and_metadata() -> None:
    client = _FakeTritonClient()
    gateway = WhisperGateway(client)  # type: ignore[misc]

    parsed = asyncio.run(gateway._infer(cast(Any, _FakeInferInput("audio", (4,), "FP32"))))

    assert parsed["output"] == [[0.0, 0.5, "hello."]]
    assert parsed["metadata"]["language"] == "en"
    assert "time" in parsed["metadata"]


@pytest.mark.skipif(TRITON_IMPORT_ERROR is not None, reason="tritonclient dependency unavailable")
def test_whisper_gateway_call_uses_buffer_and_returns_metadata(
    monkeypatch: pytest.MonkeyPatch,
    expected_numpy: np.ndarray,
) -> None:
    monkeypatch.setattr(whisper_module, "InferInput", _FakeInferInput)

    client = _FakeTritonClient()
    gateway = WhisperGateway(client)  # type: ignore[misc]
    audio = expected_numpy[:400].astype(np.float16)

    stable_output, metadata = asyncio.run(gateway(audio=audio, session_id="session-1"))

    assert isinstance(stable_output, list)
    assert metadata["language"] == "en"
    assert "time" in metadata
    assert "session-1" in gateway.session_audio_buffer
    assert "session-1" in gateway.session_hypothesis_buffer
    assert client.calls[0][0] == "whisper"
