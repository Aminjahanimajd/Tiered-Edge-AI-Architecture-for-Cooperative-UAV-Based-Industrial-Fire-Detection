"""TensorRT and TensorFlow Lite adapters that validate model metadata."""

from __future__ import print_function


class TensorRTBackend(object):
    """Static-shape TensorRT 8 adapter with engine-derived buffer sizes."""

    def __init__(self, engine_path):
        import numpy as np
        import pycuda.driver as cuda
        import pycuda.autoinit  # noqa: F401
        import tensorrt as trt

        self._np = np
        self._cuda = cuda
        self._trt = trt
        self._logger = trt.Logger(trt.Logger.WARNING)
        with open(engine_path, "rb") as source:
            serialized = source.read()
        self._runtime = trt.Runtime(self._logger)
        self._engine = self._runtime.deserialize_cuda_engine(serialized)
        if self._engine is None:
            raise RuntimeError("TensorRT could not deserialize {}".format(engine_path))
        self._context = self._engine.create_execution_context()
        self._stream = cuda.Stream()
        self._bindings = [0] * self._engine.num_bindings
        self._host = {}
        self._device = {}
        self.binding_metadata = []
        input_indices = []
        output_indices = []
        for index in range(self._engine.num_bindings):
            shape = tuple(int(value) for value in self._engine.get_binding_shape(index))
            if any(value <= 0 for value in shape):
                raise ValueError("dynamic or invalid binding shape: {}".format(shape))
            dtype = trt.nptype(self._engine.get_binding_dtype(index))
            count = int(trt.volume(shape))
            host = cuda.pagelocked_empty(count, dtype)
            device = cuda.mem_alloc(host.nbytes)
            self._host[index] = host
            self._device[index] = device
            self._bindings[index] = int(device)
            is_input = bool(self._engine.binding_is_input(index))
            (input_indices if is_input else output_indices).append(index)
            self.binding_metadata.append(
                {
                    "index": index,
                    "name": self._engine.get_binding_name(index),
                    "shape": shape,
                    "dtype": str(dtype),
                    "is_input": is_input,
                    "elements": count,
                }
            )
        if len(input_indices) != 1 or len(output_indices) != 1:
            raise ValueError("exactly one input and one output binding are required")
        self._input_index = input_indices[0]
        self._output_index = output_indices[0]
        input_shape = self.binding_metadata[self._input_index]["shape"]
        output_shape = self.binding_metadata[self._output_index]["shape"]
        if len(input_shape) != 4 or input_shape[0] != 1 or input_shape[1] != 3:
            raise ValueError("expected NCHW RGB input, received {}".format(input_shape))
        self.layout = "NCHW"
        self.model_height = input_shape[2]
        self.model_width = input_shape[3]
        self.output_shape = output_shape

    def infer(self, tensor):
        tensor = self._np.asarray(tensor)
        expected = self._host[self._input_index]
        if tensor.dtype != expected.dtype:
            raise ValueError(
                "input dtype {} does not match engine dtype {}".format(
                    tensor.dtype, expected.dtype
                )
            )
        flattened = tensor.ravel()
        if flattened.size != expected.size:
            raise ValueError(
                "input contains {} elements; engine requires {}".format(
                    flattened.size, expected.size
                )
            )
        self._np.copyto(expected, flattened)
        self._cuda.memcpy_htod_async(
            self._device[self._input_index], expected, self._stream
        )
        ok = self._context.execute_async_v2(
            bindings=self._bindings, stream_handle=self._stream.handle
        )
        if ok is False:
            raise RuntimeError("TensorRT execution returned failure")
        output_host = self._host[self._output_index]
        self._cuda.memcpy_dtoh_async(
            output_host, self._device[self._output_index], self._stream
        )
        self._stream.synchronize()
        if output_host.size != int(self._trt.volume(self.output_shape)):
            raise RuntimeError("TensorRT output buffer size changed unexpectedly")
        return output_host.reshape(self.output_shape).copy()


class TFLiteBackend(object):
    """TFLite adapter that validates the deployed model's tensor interface."""

    def __init__(self, model_path, num_threads):
        import numpy as np
        import tflite_runtime.interpreter as tflite

        self._np = np
        self._interpreter = tflite.Interpreter(
            model_path=model_path, num_threads=int(num_threads)
        )
        self._interpreter.allocate_tensors()
        inputs = self._interpreter.get_input_details()
        outputs = self._interpreter.get_output_details()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("exactly one TFLite input and output are required")
        self.input_metadata = inputs[0]
        self.output_metadata = outputs[0]
        shape = tuple(int(value) for value in self.input_metadata["shape"])
        if len(shape) != 4 or shape[0] != 1 or shape[3] != 3:
            raise ValueError("expected NHWC RGB input, received {}".format(shape))
        if self.input_metadata["dtype"] != np.float32:
            raise ValueError("current preprocessing requires float32 TFLite input")
        self.layout = "NHWC"
        self.model_height = shape[1]
        self.model_width = shape[2]

    def infer(self, tensor):
        tensor = self._np.asarray(tensor)
        expected_shape = tuple(int(value) for value in self.input_metadata["shape"])
        if tuple(tensor.shape) != expected_shape:
            raise ValueError(
                "input shape {} does not match model shape {}".format(
                    tuple(tensor.shape), expected_shape
                )
            )
        if tensor.dtype != self.input_metadata["dtype"]:
            raise ValueError("TFLite input dtype mismatch")
        self._interpreter.set_tensor(self.input_metadata["index"], tensor)
        self._interpreter.invoke()
        return self._interpreter.get_tensor(self.output_metadata["index"]).copy()
