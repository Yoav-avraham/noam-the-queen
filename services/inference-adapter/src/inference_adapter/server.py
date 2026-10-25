from __future__ import annotations

from typing import Any, cast
import asyncio
import logging

import tritonclient.grpc.aio as triton_grpc_aio

from stt_common.constants import ModelNames
from stt_common.contracts import (
    StreamName,
    ServiceOutput,
    TritonOutputSegment,
    ReadyAudioWindowContent,
)
from stt_common.stream_manager import StreamManager, ServiceHandler
from stt_common.redis_stream_client import RedisStreamClient

from .config import InferenceAdapterConfig
from .preprocessing import Preprocessor
from .model_gateways import BaseGateway, WhisperGateway, PyannoteGateway
import numpy as np

logger = logging.getLogger(__name__)


def configure_process() -> None:
    """Perform one-time, process-wide startup setup.

    Centralizes everything the running service needs before serving — logging,
    i18n catalogs, and any future setup — so the process is bootstrapped from a
    single place. Unit tests do not run this path; components that need a given
    facility (for example the transcript merger and i18n) ensure their own
    prerequisites so they stay independently testable.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def build_stream_handler(model_gateways: dict[str, BaseGateway], preprocessor: Preprocessor) -> ServiceHandler:
    """Build the stream handler used by StreamManager."""

    async def handle_stream_data(source: ServiceOutput) -> dict[str, Any]:
        session_id = source.session_id
        content = source.window_payload.content
        audio = ReadyAudioWindowContent.model_validate(content)

        audio_bytes = audio.raw_bytes
        channels = audio.channels
        sample_width = audio.sample_width
        sample_rate = audio.sample_rate

        logger.info(
            (
                "inference adapter got audio ",
                f"of size: {len(audio_bytes)} ",
                f"duration: {len(audio_bytes) / (sample_rate * sample_width * channels)} "
            )
        )

        numpy_audio = preprocessor(
            audio_bytes=audio_bytes,
            channels=channels,
            sample_width=sample_width,
            sample_rate=sample_rate
        )

        if numpy_audio is None or numpy_audio.size == 0:
            return {"words": [], "speakers": []}

        tasks = []
        for gateway in model_gateways.values():
            tasks.append(gateway(numpy_audio, session_id=session_id, is_final=source.is_final))

        outputs = await asyncio.gather(*tasks)

        words: list[TritonOutputSegment] = []
        speakers: list[TritonOutputSegment] = []

        for model_name, result in zip(model_gateways.keys(), outputs, strict=False):

            logger.info(f"=================== {model_name} output ===================")
            logger.info(result)
            logger.info(f"================= end {model_name} output =================")
            logger.info("")


            if model_name == ModelNames.WHISPER.value:
                stable_output, _metadata = result
                words: list[TritonOutputSegment] = [
                    {
                        "start_timestamp": float(a),
                        "end_timestamp": float(b),
                        "value": str(t),
                    }
                    for a, b, t in stable_output
                ]
            elif model_name == ModelNames.PYANNOTE.value:
                speakers = cast(list[TritonOutputSegment], result)

        if len(words) == 0:
            return {"words": [], "speakers": []}

        # TODO: optimize with synchronizer
        min_words_ts = min([ e['start_timestamp'] for e in words ])
        max_words_ts = max([ e['end_timestamp'] for e in words ])

        speakers_idx_start = speakers_idx_end = 0

        for i, e in enumerate(speakers):
            if min_words_ts > e['end_timestamp']:
                speakers_idx_start += 1
                speakers_idx_end = speakers_idx_start
            elif max_words_ts > e['end_timestamp']:
                speakers_idx_end += 1
            else:
                break

        speakers = speakers[speakers_idx_start:speakers_idx_end+1]

        logger.info(
            (
                f"inference adapter returned output ",
                f"session_id: {source.session_id} ",
                f"sequence_id: {source.sequence_id} ",
                f"is_final: {source.is_final} "
            )
        )

        return {"words": words, "speakers": speakers}

    return handle_stream_data


async def serve() -> None:
    """Start and run the inference adapter service."""

    configure_process()
    logger.info("inference adapter process configured")

    config = InferenceAdapterConfig.from_env()
    triton_client = triton_grpc_aio.InferenceServerClient(url=config.triton_url)
    redis_client = RedisStreamClient.from_url(config.redis_url)

    preprocessor = Preprocessor(output_dtype=np.float32)

    model_gateways: dict[str, BaseGateway] = {
        ModelNames.WHISPER.value: WhisperGateway(
            triton_client,
            model_name=ModelNames.WHISPER.value
        ),
        ModelNames.PYANNOTE.value: PyannoteGateway(
            triton_client,
            model_name="speaker-diarization-community-1",
            segmentation_model_name=ModelNames.PYANNOTE_SEGMENTATION.value,
            embedding_model_name=ModelNames.PYANNOTE_EMBEDDING.value
        ),
    }

    manager = StreamManager(
        redis_client=redis_client,
        consumer_group_name=config.consumer_group_name,
        input_stream_name=StreamName.READY_AUDIO,
        service_handler=build_stream_handler(model_gateways, preprocessor),
    )
    await manager.check_redis_connection()
    await manager.run_workers()


def main() -> None:
    """Run the async service entry point."""
    try:
        asyncio.run(serve())
    except Exception:
        logger.exception("inference adapter process terminated with error")
        raise
