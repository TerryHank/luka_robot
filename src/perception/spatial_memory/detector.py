"""YOLO11 COCO inference, TensorRT 10 with an explicit ONNX CPU fallback."""
import ast
import ctypes as C
import pathlib
import cv2
import numpy as np
import onnxruntime as ort


class TrtRunner:
    def __init__(self, path):
        import tensorrt as trt
        self.log = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.log)
        self.engine = self.runtime.deserialize_cuda_engine(pathlib.Path(path).read_bytes())
        if self.engine is None:
            raise RuntimeError('TensorRT engine could not be deserialized')
        self.context = self.engine.create_execution_context()
        self.cuda = C.CDLL('/usr/local/cuda/lib64/libcudart.so.12')
        self.cuda.cudaMalloc.argtypes = [C.POINTER(C.c_void_p), C.c_size_t]
        self.cuda.cudaMemcpy.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t, C.c_int]
        self.cuda.cudaStreamCreate.argtypes = [C.POINTER(C.c_void_p)]
        self.cuda.cudaStreamSynchronize.argtypes = [C.c_void_p]
        self.cuda.cudaFree.argtypes = [C.c_void_p]
        self.cuda.cudaStreamDestroy.argtypes = [C.c_void_p]
        self.stream = C.c_void_p()
        self.check(self.cuda.cudaStreamCreate(C.byref(self.stream)))
        self.buffers = {}
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            shape = tuple(self.engine.get_tensor_shape(name))
            if min(shape) <= 0:
                raise RuntimeError('Use a static engine')
            array = np.empty(shape, dtype=trt.nptype(self.engine.get_tensor_dtype(name)))
            ptr = C.c_void_p()
            self.check(self.cuda.cudaMalloc(C.byref(ptr), array.nbytes))
            self.context.set_tensor_address(name, ptr.value)
            self.buffers[name] = (array, ptr)
            if self.engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                self.input = name
            else:
                self.output = name

    @staticmethod
    def check(code):
        if code:
            raise RuntimeError(f'CUDA operation failed: {code}')

    def __call__(self, blob):
        host, device = self.buffers[self.input]
        np.copyto(host, blob)
        self.check(self.cuda.cudaMemcpy(device, C.c_void_p(host.ctypes.data), host.nbytes, 1))
        if not self.context.execute_async_v3(self.stream.value):
            raise RuntimeError('TensorRT execution failed')
        self.check(self.cuda.cudaStreamSynchronize(self.stream))
        host, device = self.buffers[self.output]
        self.check(self.cuda.cudaMemcpy(C.c_void_p(host.ctypes.data), device, host.nbytes, 2))
        return host.copy()


class Detector:
    def __init__(self, root, confidence=.4, backend='auto'):
        root = pathlib.Path(root)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 4
        self.ort = ort.InferenceSession(str(root/'models/yolo11n.onnx'), opts,
                                        providers=['CPUExecutionProvider'])
        self.names = ast.literal_eval(self.ort.get_modelmeta().custom_metadata_map['names'])
        self.input = self.ort.get_inputs()[0].name
        dim = self.ort.get_inputs()[0].shape[-1]
        self.size = dim if isinstance(dim,int) else 640
        self.confidence = confidence
        engine = root/'models/yolo11n-fp16.engine'
        self.backend = 'onnxruntime-cpu'
        self.runner = None
        if backend != 'cpu' and engine.exists():
            self.runner = TrtRunner(engine)
            self.backend = 'tensorrt-fp16-gpu'
        elif backend == 'gpu':
            raise RuntimeError('GPU engine missing; run build_engine.py')

    def detect(self, bgr):
        h, w = bgr.shape[:2]
        ratio = min(self.size/w, self.size/h)
        nw, nh = round(w*ratio), round(h*ratio)
        px, py = (self.size-nw)//2, (self.size-nh)//2
        canvas = np.full((self.size,self.size,3),114,dtype=np.uint8)
        canvas[py:py+nh,px:px+nw] = cv2.resize(bgr,(nw,nh))
        blob = np.ascontiguousarray(canvas[:,:,::-1].transpose(2,0,1)[None],dtype=np.float32)/255
        raw = self.runner(blob) if self.runner else self.ort.run(None,{self.input:blob})[0]
        rows = raw[0].T
        classes = rows[:,4:].argmax(1)
        scores = rows[np.arange(len(rows)),4+classes]
        rows, classes, scores = rows[scores>=self.confidence], classes[scores>=self.confidence], scores[scores>=self.confidence]
        if not len(rows):
            return []
        xywh = rows[:,:4].copy()
        xywh[:,:2] -= xywh[:,2:]/2
        xywh[:,0] = (xywh[:,0]-px)/ratio
        xywh[:,1] = (xywh[:,1]-py)/ratio
        xywh[:,2:] /= ratio
        detections = []
        for cls in np.unique(classes):
            indices = np.flatnonzero(classes==cls)
            keep = cv2.dnn.NMSBoxes(xywh[indices].tolist(),scores[indices].tolist(),self.confidence,.45)
            for k in np.asarray(keep).reshape(-1):
                idx = indices[k]
                x,y,bw,bh = xywh[idx]
                box = [max(0,round(float(x))),max(0,round(float(y))),min(w,round(float(x+bw))),min(h,round(float(y+bh)))]
                if box[2]-box[0]<3 or box[3]-box[1]<3:
                    continue
                detections.append({'class':self.names[int(cls)],'confidence':round(float(scores[idx]),4),'bbox':box})
        return detections
