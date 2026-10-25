import onnx

# models/onnx_whisper/1/model.onnx
model = onnx.load("model_path")


for inp in model.graph.input:
    print(inp.name)

for inp in model.graph.output:
    print(inp.name)
