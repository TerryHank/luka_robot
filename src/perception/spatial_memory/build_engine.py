import pathlib
import tensorrt as trt

root = pathlib.Path(__file__).resolve().parent
log = trt.Logger(trt.Logger.WARNING)
builder = trt.Builder(log)
network = builder.create_network(0)
parser = trt.OnnxParser(network, log)
if not parser.parse((root/'models/yolo11n.onnx').read_bytes()):
    raise RuntimeError('\n'.join(str(parser.get_error(i)) for i in range(parser.num_errors)))
network.get_input(0).shape = (1,3,640,640)
config = builder.create_builder_config()
config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)
config.set_flag(trt.BuilderFlag.FP16)
config.builder_optimization_level = 3
print('Building TensorRT FP16 engine',flush=True)
plan = builder.build_serialized_network(network, config)
if plan is None:
    raise RuntimeError('Engine build failed')
dest = root/'models/yolo11n-fp16.engine'
dest.write_bytes(bytes(plan))
print('Saved',dest,flush=True)
