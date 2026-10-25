from __future__ import annotations

import time
from typing import Any
from dataclasses import dataclass
import json

import numpy as np
from tritonclient.grpc import InferInput

from stt_common.constants import (
    DEFAULT_OFFSET,
    DEFAULT_SPEAKER,
    SAMPLE_RATE_16KHZ,
    DEFAULT_MIN_DURATION,
    DEFAULT_MAX_GAP_FRAME,
    EMBEDDING_OUTPUT_NAME,
    TRITON_INPUT_DATA_TYPE,
    DEFAULT_SCORE_THRESHOLD,
    TRITON_INPUT_LAYER_NAME,
    SEGMENTATION_OUTPUT_NAME,
    ModelNames,
)
from inference_adapter.preprocessing import NumpyAudioBuffer

from .base import BaseGateway


@dataclass
class Speaker:
    id: int
    centroid: np.ndarray
    count: int = 1


class SpeakerTracker:
    def __init__(self, threshold=0.715):
        self.threshold = threshold
        self.speakers: list[Speaker] = []
        self.next_id = 0

    def _normalize(self, vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)

        if norm == 0:
            return vector

        return vector / norm

    def _cosine(self, a: np.ndarray, b: np.ndarray):
        return np.dot(a, b)

    def assign(self, embedding: np.ndarray) -> int:
        embedding = self._normalize(embedding)

        if not self.speakers:
            self.speakers.append(Speaker(self.next_id, embedding.copy()))
            self.next_id += 1
            return DEFAULT_SPEAKER

        similarities = [self._cosine(embedding, speaker_cluster.centroid) for speaker_cluster in self.speakers]

        best_idx = int(np.argmax(similarities))
        best_score = similarities[best_idx]

        if best_score >= self.threshold:
            speaker = self.speakers[best_idx]

            # running average
            speaker.centroid = (speaker.centroid * speaker.count + embedding) / (speaker.count + 1)

            speaker.centroid = self._normalize(speaker.centroid)
            speaker.count += 1

            return speaker.id

        self.speakers.append(Speaker(self.next_id, embedding.copy()))
        self.next_id += 1
        return self.next_id - 1


class PyannoteGateway(BaseGateway):
    def __init__(
        self,
        triton_client,
        model_name=ModelNames.PYANNOTE.value,
        segmentation_model_name=ModelNames.PYANNOTE_SEGMENTATION.value,
        embedding_model_name=ModelNames.PYANNOTE_EMBEDDING.value,
        input_layer_name=TRITON_INPUT_LAYER_NAME,
        input_data_type=TRITON_INPUT_DATA_TYPE,
        speaker_gap_threshold=0.45  # 450ms gap, TODO: move this to stt_common
    ):
        self.triton_client = triton_client

        self.model_name = model_name

        self.segmentation_model_name = segmentation_model_name
        self.embedding_model_name = embedding_model_name

        self.input_layer_name = input_layer_name
        self.input_data_type = input_data_type
        self.speaker_gap_threshold = speaker_gap_threshold

        self.session_audio_buffer: dict[str, NumpyAudioBuffer] = {}
        self.session_offsets: dict[str, float] = {}

        self.session_clusters: dict[str, np.ndarray] = {}

        # TODO: add the ability to configure the number of speakers per session.
        self.session_speaker_tracker: dict[str, SpeakerTracker] = {}

    def get_audio_buffer(self, session_id):
        if session_id not in self.session_audio_buffer:
            self.session_audio_buffer[session_id] = NumpyAudioBuffer()

        audio_buffer = self.session_audio_buffer[session_id]

        return audio_buffer

    def get_speaker_tracker(self, session_id):
        if session_id not in self.session_speaker_tracker:
            self.session_speaker_tracker[session_id] = SpeakerTracker()

        speaker_tracker = self.session_speaker_tracker[session_id]

        return speaker_tracker

    async def __call__(self, audio: np.ndarray, session_id: str, **kwargs):
        speaker_tracker = self.get_speaker_tracker(session_id=session_id)

        audio_buffer = self.get_audio_buffer(session_id=session_id)
        audio_buffer.append(audio=audio)

        # _audio_to_triton = audio_buffer.buffer.reshape(1, 1, -1)
        _audio_to_triton = np.expand_dims(audio_buffer.buffer, axis=0)

        infer_input = InferInput(self.input_layer_name, _audio_to_triton.shape, self.input_data_type)
        infer_input.set_data_from_numpy(_audio_to_triton)

        result = await self.triton_client.infer(
            model_name=self.model_name,
            inputs=[ infer_input ],
        )

        unprocessed_ret = json.loads(result.as_numpy("output")[0].decode("utf-8"))
        unprocessed_ret = [
            {
                "start_timestamp": float(a),
                "end_timestamp": float(b),
                "value": str(int(str(t).split('_')[-1])),  # TODO: EW.
            }
            for a, b, t in unprocessed_ret
        ]

        if not unprocessed_ret:
            return []

        unprocessed_ret[0]['start_timestamp'] = 0.0

        ret = [ unprocessed_ret[0], unprocessed_ret[-1] ]
        # This loop drops speakers that "spoke" for less than speaker_gap_threshold
        # in between two segments of the same speaker.
        for i in range(1, len(unprocessed_ret) - 1):
            p_value = unprocessed_ret[i - 1]["value"]
            n_value = unprocessed_ret[i + 1]["value"]

            interval = unprocessed_ret[i]["end_timestamp"] - unprocessed_ret[i]["start_timestamp"]

            if not ((p_value == n_value) and (interval <= self.speaker_gap_threshold)):
                ret.insert(-1, unprocessed_ret[i])

        return ret

        # TODO: we'll get back to this later, for now take this beautiful solution.
        # output = await self._infer(x=infer_input, audio_buffer=audio_buffer, speaker_tracker=speaker_tracker)

        # return output

    def fill_short_label_gaps(self, labels: np.ndarray, max_gap_frames: int = DEFAULT_MAX_GAP_FRAME):
        run_start = 0

        while run_start < len(labels):
            run_end = run_start + 1
            while run_end < len(labels) and labels[run_end] == labels[run_start]:
                run_end += 1

            run_length = run_end - run_start
            left_label = labels[run_start - 1] if run_start > 0 else -1
            right_label = labels[run_end] if run_end < len(labels) else -1

            if run_length <= max_gap_frames and left_label == right_label and left_label != -1:
                labels[run_start:run_end] = left_label

            run_start = run_end

    def build_embedding_segments(
        self,
        audio: np.ndarray,
        score_matrix: np.ndarray,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        min_duration_s: float = DEFAULT_MIN_DURATION,
        max_gap_frames: int = DEFAULT_MAX_GAP_FRAME,
        split_on_overlap: bool = True,
        offset: float = DEFAULT_OFFSET,
    ) -> tuple[list[dict], np.ndarray]:
        frame_hop_s = audio.shape[0] / SAMPLE_RATE_16KHZ / score_matrix.shape[0]

        speaker_frame_mask = (score_matrix > score_threshold).astype(np.int32)
        dominant_speaker = np.full(score_matrix.shape[0], -1, dtype=np.int32)

        active_frame_mask = speaker_frame_mask.sum(axis=1) > 0
        dominant_speaker[active_frame_mask] = np.argmax(score_matrix[active_frame_mask], axis=1)
        self.fill_short_label_gaps(dominant_speaker, max_gap_frames=max_gap_frames)

        if split_on_overlap:
            overlap_frame_mask = speaker_frame_mask.sum(axis=1) > 1
            dominant_speaker[overlap_frame_mask] = -1

        segments_to_embed = []
        min_frames = max(1, int(np.ceil(min_duration_s / frame_hop_s)))
        run_start: int = 0

        while run_start < len(dominant_speaker):
            run_end = run_start + 1
            while run_end < len(dominant_speaker) and dominant_speaker[run_end] == dominant_speaker[run_start]:
                run_end += 1

            speaker_id = dominant_speaker[run_start]
            run_length = run_end - run_start

            if speaker_id != -1 and run_length >= min_frames:
                start_s = offset + (run_start * frame_hop_s)
                end_s = offset + (run_end * frame_hop_s)
                sample_start = max(0, int(np.floor((start_s - offset) * 16_000)))
                sample_end = min(audio.shape[0], int(np.ceil((end_s - offset) * 16_000)))
                segment_audio = audio[sample_start:sample_end].copy()

                if segment_audio.size > 0:
                    segments_to_embed.append(
                        {
                            "speaker": int(speaker_id),
                            "start_s": float(start_s),
                            "end_s": float(end_s),
                            "duration_s": float(end_s - start_s),
                            "sample_start": int(sample_start),
                            "sample_end": int(sample_end),
                            "audio": segment_audio,
                        }
                    )

            run_start = run_end

        return segments_to_embed, dominant_speaker

    async def _infer_segments(self, x: InferInput) -> dict[str, Any]:
        ts = time.perf_counter()
        result = await self.triton_client.infer(
            model_name=self.segmentation_model_name,
            inputs=[x],
        )
        elapsed_time = time.perf_counter() - ts

        segments = result.as_numpy(SEGMENTATION_OUTPUT_NAME)
        metadata = {"time": elapsed_time}

        ret = {"output": segments, "metadata": metadata}

        return ret

    async def _infer_embeddings(self, x: InferInput):
        ts = time.perf_counter()
        result = await self.triton_client.infer(
            model_name=self.embedding_model_name,
            inputs=[x],
        )
        elapsed_time = time.perf_counter() - ts

        embeddings = result.as_numpy(EMBEDDING_OUTPUT_NAME)
        metadata = {"time": elapsed_time}

        ret = {"output": embeddings, "metadata": metadata}

        return ret

    def _cluster_embeddings(self, embeddings: np.ndarray, speaker_tracker: SpeakerTracker):
        labels = []

        for emb in embeddings:
            label = speaker_tracker.assign(emb)
            labels.append(label)

        return labels

    async def _infer(self, x: InferInput, audio_buffer: NumpyAudioBuffer, speaker_tracker: SpeakerTracker):
        segments_ret = await self._infer_segments(x)
        segments = segments_ret["output"]

        embedding_segments, _dominant_speaker = self.build_embedding_segments(
            audio=audio_buffer.buffer,
            score_matrix=segments[0],
            score_threshold=0.4,
            min_duration_s=0.75,
            max_gap_frames=8,
            split_on_overlap=False,
            offset=audio_buffer.offset / SAMPLE_RATE_16KHZ,
        )

        segments2embed = [e["audio"] for e in embedding_segments]

        if not segments2embed:
            return []

        batch_size = len(segments2embed)

        max_dim = max([e.shape[0] for e in segments2embed])

        padded_segmentes2embed = np.array([np.concatenate([e, np.zeros(max_dim - e.shape[0])]) for e in segments2embed])
        padded_segmentes2embed = padded_segmentes2embed.reshape(batch_size, 1, -1).astype(np.float16)

        infer_input = InferInput(self.input_layer_name, padded_segmentes2embed.shape, self.input_data_type)
        infer_input.set_data_from_numpy(padded_segmentes2embed)

        embeddings_ret = await self._infer_embeddings(infer_input)
        embeddings = embeddings_ret["output"]

        speakers = self._cluster_embeddings(embeddings, speaker_tracker=speaker_tracker)
        speakers = list(
            [
                {"start_timestamp": s2e["start_s"], "end_timestamp": s2e["end_s"], "value": str(speaker)}
                for speaker, s2e in zip(speakers, embedding_segments, strict=False)
            ]
        )
        return speakers
