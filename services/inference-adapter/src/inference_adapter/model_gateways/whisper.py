from __future__ import annotations

import json
import time

import numpy as np
from tritonclient.grpc import InferInput

from stt_common.constants import (
    SAMPLE_RATE_16KHZ,
    TRITON_INPUT_DATA_TYPE,
    TRITON_INPUT_LAYER_NAME,
    ModelNames,
)

from inference_adapter.preprocessing import NumpyAudioBuffer
from inference_adapter.postprocessing import HypothesisBuffer

from .base import BaseGateway


class WhisperGateway(BaseGateway):
    def __init__(
        self,
        triton_client,
        model_name=ModelNames.WHISPER.value,
        input_layer_name=TRITON_INPUT_LAYER_NAME,
        input_data_type=TRITON_INPUT_DATA_TYPE
    ):
        self.triton_client = triton_client

        self.model_name = model_name
        self.input_layer_name = input_layer_name
        self.input_data_type = input_data_type

        self.session_audio_buffer: dict[str, NumpyAudioBuffer] = {}

        self.session_hypothesis_buffer: dict[str, HypothesisBuffer] = {}
        self.session_offsets: dict[str, float] = {}

    def get_audio_buffer(self, session_id):
        if session_id not in self.session_audio_buffer:
            self.session_audio_buffer[session_id] = NumpyAudioBuffer()

        audio_buffer = self.session_audio_buffer[session_id]

        return audio_buffer

    def get_hypothesis_buffer(self, session_id):
        if session_id not in self.session_hypothesis_buffer:
            self.session_hypothesis_buffer[session_id] = HypothesisBuffer()
            self.session_offsets[session_id] = 0.0

        hypothesis_buffer = self.session_hypothesis_buffer[session_id]
        offset = self.session_offsets[session_id]

        return hypothesis_buffer, offset

    async def __call__(self, audio: np.ndarray, session_id: str, **kwargs):
        hypothesis_buffer, insert_offset = self.get_hypothesis_buffer(session_id=session_id)
        audio_buffer = self.get_audio_buffer(session_id=session_id)

        audio_buffer.append(audio=audio)

        _audio_to_triton = audio_buffer.buffer.reshape(1, -1)

        infer_input = InferInput(self.input_layer_name, _audio_to_triton.shape, self.input_data_type)
        infer_input.set_data_from_numpy(_audio_to_triton)

        output = await self._infer(infer_input)

        hypothesis = output["output"]
        metadata = output["metadata"]

        hypothesis_buffer.insert(hypothesis, insert_offset)

        stable_output = hypothesis_buffer.flush()
        if kwargs.get('is_final', False):
            stable_output.extend([ (a, b, t) for a, b, t in hypothesis_buffer.buffer ])


        audio_cut_ts = hypothesis_buffer.cut(insert_offset)

        if audio_cut_ts > 0:
            audio_buffer.truncate_buffer(int((audio_cut_ts) * SAMPLE_RATE_16KHZ))

            # This line is equivalent to `self.session_offsets[session_id] = hypothesis_buffer.last_sentence_time`
            self.session_offsets[session_id] = insert_offset + audio_cut_ts

        return stable_output, metadata

    async def _infer(self, x: InferInput):
        ts = time.perf_counter()
        result = await self.triton_client.infer(
            model_name=self.model_name,
            inputs=[x],
        )
        elapsed_time = time.perf_counter() - ts

        output = json.loads(result.as_numpy("output")[0].decode("utf-8"))
        metadata = json.loads(result.as_numpy("metadata")[0].decode("utf-8"))
        metadata["time"] = elapsed_time

        ret = {"output": output, "metadata": metadata}

        return ret
