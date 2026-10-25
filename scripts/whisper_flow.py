########################################################
# This file contains few function that                 #
# would be used when working with triton               #
#                                                      #
# Working hours wasted here: ~4h over a missing 's'    #
########################################################

import os
import warnings

import numpy as np
import torch
from transformers import WhisperProcessor
from tritonclient.grpc import InferInput, InferRequestedOutput
import tritonclient.grpc.aio as triton_grpc_aio
from transformers.modeling_outputs import BaseModelOutput

warnings.filterwarnings("ignore")

os.environ["HF_HUB_OFFLINE"] = "1"

# load model and processor
processor = WhisperProcessor.from_pretrained("./models/whisper-large-v3-turbo")

# INPUT_LAYER_NAME and OUTPUT_LAYER_NAME values were taken from
# the nn_architecture_info.py output.
# To know what's the output layer name run the code in `nn_architecture_info.py`
OUTPUT_LAYER_NAME = "encoder_hidden_state"
INPUT_LAYER_NAME = "mel"

INPUT_DATA_TYPE = "FP32"
TRITON_MODEL_NAME = "whisper"


MODEL_OUTPUT = InferRequestedOutput(OUTPUT_LAYER_NAME)


TEST_AUDIO_PATH = "saved_audio/audio_20260513_125646.wav"

# with wave.open(TEST_AUDIO_PATH, "rb") as wav_file:
#     sample_rate = wav_file.getframerate()
#     channels = wav_file.getnchannels()
#     sample_width = wav_file.getsampwidth()
#     n_frames = wav_file.getnframes()

#     print(
#         f"Audio file info: sample_rate={sample_rate}, channels={channels}, "
#         f"sample_width={sample_width}, n_frames={n_frames}"
#     )
#     wav_data = wav_file.readframes(n_frames)
#     print(f"Read {len(wav_data)} bytes of audio data from {TEST_AUDIO_PATH}")


def stream_audio_chunks(wav_data, chunk_size=4096):
    for i in range(0, len(wav_data), chunk_size):
        yield wav_data[i : i + chunk_size]


def tokenize_audio(
    pcm_bytes: bytes,
    sample_rate: int,
    channels: int,
    input_layer_name: str = "mel",
    input_data_type: str = "FP32",
):
    # Assuming 16-bit PCM, adjust if audio is different
    # How to know which dtype to use? check the sample_width from the incoming audio
    # sample_width is in bytes, and the dtype in bits.
    # 16-bit PCM is calculated using sample_width x 8 (8 bits per byte)
    audio_type = np.int16

    # audio is a 1D array of 16-bit signed integers.
    audio = np.frombuffer(pcm_bytes, dtype=audio_type)

    # Normalize to [-1.0, 1.0): for int16 input, divide by 32768.
    # int16 range is -32768..32767, so 32768 is abs(min).
    audio = audio.astype(np.float32) / 32768.0

    # If the audio has multiple channels, reshape and average to mono
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    # Now `audio` is a 1D numpy array of float32 samples in the range [-1.0, 1.0).
    # Next, convert this raw audio array into model input features.
    input_features = processor(audio, sampling_rate=sample_rate, return_tensors="pt").input_features
    #                                        ^ missing "s" here caused failures.

    input_features = input_features.astype(np.float32)
    infer_input = InferInput(input_layer_name, input_features.shape, input_data_type)
    infer_input.set_data_from_numpy(input_features)

    return infer_input


def decode(hidden_states: np.ndarray | torch.Tensor) -> str:
    if not isinstance(hidden_states, torch.Tensor):
        hidden_states = BaseModelOutput(last_hidden_state=torch.from_numpy(hidden_states).float())

    return processor.batch_decode(hidden_states, skip_special_tokens=True)


async def infer(
    triton_client: triton_grpc_aio.InferenceServerClient,
    pcm_bytes: bytes,
    sample_rate: int,
    channels: int,
    model_name: str = "whisper",
) -> str:
    if not pcm_bytes:
        return ""

    infer_input = tokenize_audio(pcm_bytes=pcm_bytes, sample_rate=sample_rate, channels=channels)
    hidden_states = await triton_client.infer(model_name=model_name, input=[infer_input], outputs=[MODEL_OUTPUT])
    output = decode(hidden_states)
    print(output)


# input_data = tokenize_audio(wav_data, sample_rate=sample_rate, channels=channels)
# print(input_data)


# async def main():
#     try:
#         triton_client = triton_grpc_aio.InferenceServerClient(url="localhost:8001")
#         is_live = await triton_client.is_server_live()
#         if not is_live:
#             print("Triton server is not live")
#             return

#         print(f"Triton server live: {is_live}")

#         infer_input = triton_grpc_aio.InferInput("mel", [1, 80, 300], "FP32")
#         infer_input.set_data_from_numpy(
#             np.random.rand(1, 80, 300).astype(np.float32)
#         )  # Example input

#         requested_output = triton_grpc_aio.InferRequestedOutput("encoder_hidden_states")

#         result = await triton_client.infer(
#             model_name="onnx_whisper",
#             inputs=[
#                 infer_input
#             ],
#             outputs=[
#                 requested_output
#             ]
#         )

#         print("Inference result:", result)

#     except Exception as e:
#         print(f"Error connecting to Triton server: {e}")

# if __name__ == "__main__":
#     asyncio.run(main())


# import onnx

# model = onnx.load("models/onnx_whisper/1/model.onnx")

# for node in model.graph.node:
#     print(f"Node name: {node.name}, Op type: {node.op_type}")

# for inp in model.graph.input:
# 	print(inp.name)

# for inp in model.graph.output:
# 	print(inp.name)
