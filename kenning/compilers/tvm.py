# Copyright (c) 2020-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

"""
Wrapper for TVM deep learning compiler.
"""

import tvm
import onnx
import tvm.relay as relay
from pathlib import Path
from typing import Optional, Dict, List

from kenning.core.optimizer import Optimizer
from kenning.core.optimizer import ConversionError
from kenning.core.optimizer import CompilationError
from kenning.core.optimizer import IOSpecificationNotFoundError
from kenning.core.dataset import Dataset
from kenning.utils.logger import get_logger


def onnxconversion(
        compiler: 'TVMCompiler',
        modelpath: Path,
        input_shapes,
        dtypes):
    try:
        dtype = list(dtypes.values())[0]
    except IndexError:
        raise IndexError('No dtype in the input specification')

    onnxmodel = onnx.load(modelpath)
    return relay.frontend.from_onnx(
        onnxmodel,
        shape=input_shapes,
        freeze_params=True,
        dtype=dtype
    )


def kerasconversion(
        compiler: 'TVMCompiler',
        modelpath: Path,
        input_shapes,
        dtypes):
    import tensorflow as tf
    tf.keras.backend.clear_session()
    model = tf.keras.models.load_model(str(modelpath))
    print(model.summary())
    return relay.frontend.from_keras(
        model,
        shape=input_shapes,
        layout='NHWC'
    )


def no_conversion(out_dict):
    return out_dict


def torchconversion(
        compiler: 'TVMCompiler',
        modelpath: Path,
        input_shapes,
        dtypes):
    import torch
    import numpy as np

    # This is a model-specific selector of output conversion functions.
    # It defaults to a no_conversion function that just returns its input
    # It is easily expandable in case it is needed for other models
    if compiler.conversion_func == 'dict_to_tuple':  # For PyTorch Mask R-CNN Model  # noqa: E501
        from kenning.modelwrappers.instance_segmentation.pytorch_coco import dict_to_tuple  # noqa: E501
        wrapper = dict_to_tuple
    else:  # General case- no conversion is happening
        wrapper = no_conversion

    def mul(x: tuple) -> int:
        """
        Method used to convert shape-representing tuple
        to a 1-dimmensional size to allow the model to be inferred with
        an 1-dimmensional byte array

        Parameters
        ----------
        x : tuple
            tuple describing the regular input shape

        Returns
        -------
        int : the size of a 1-dimmensional input matching the original shape
        """
        ret = 1
        for i in list(x):
            ret *= i
        return ret

    class TraceWrapper(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model

        def forward(self, inp):
            out = self.model(
                inp.reshape(input_shapes[list(input_shapes.keys())[0]])
            )
            return wrapper(out[0])

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    def model_func(modelpath: Path):
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        loaded_model = torch.load(modelpath, map_location=device)
        if not isinstance(loaded_model, torch.nn.Module):
            raise CompilationError(
                f'TVM compiler expects the input data of type: torch.nn.Module, but got: {type(loaded_model).__name__}'  # noqa: E501
            )
        return loaded_model

    model = TraceWrapper(model_func(modelpath))
    model.eval()
    inp = torch.Tensor(
        np.random.uniform(
            0.0,
            250.0,
            (mul(input_shapes[list(input_shapes.keys())[0]]))
        ),
    )

    inp = inp.to(device)

    with torch.no_grad():
        model(inp)
        model_trace = torch.jit.trace(model, inp)
        model_trace.eval()

    return relay.frontend.from_pytorch(
        model_trace,
        # this is a list of input infos where there is a dict
        # constructed from {input_name: (n-dim tuple-shape)}
        # into {input_name: [product_of_the_dimmensions]}
        list(
            {
                list(input_shapes.keys())[0]:
                [mul(input_shapes[list(input_shapes.keys())[0]])]
            }.items()
        )
    )


def darknetconversion(
        compiler: 'TVMCompiler',
        modelpath: Path,
        input_shapes,
        dtypes):
    try:
        dtype = list(dtypes.values())[0]
    except IndexError:
        raise IndexError('No dtype in the input specification')

    from tvm.relay.testing.darknet import __darknetffi__
    if not compiler.libdarknetpath:
        log = get_logger()
        log.fatal(
            'The darknet converter requires libdarknet.so library. ' +
            'Provide the path to it using --libdarknet-path flag')
        raise ConversionError('Provide libdarknet.so library')
    try:
        lib = __darknetffi__.dlopen(str(compiler.libdarknetpath))
    except OSError as e:
        raise ConversionError(e)
    net = lib.load_network(
        str(modelpath.with_suffix('.cfg')).encode('utf-8'),
        str(modelpath).encode('utf-8'),
        0
    )
    return relay.frontend.from_darknet(
        net,
        dtype=dtype,
        shape=input_shapes['input']
    )


def tfliteconversion(
        compiler: 'TVMCompiler',
        modelpath: Path,
        input_shapes,
        dtypes):

    with open(modelpath, 'rb') as f:
        tflite_model_buf = f.read()

    try:
        import tflite
        tflite_model = tflite.Model.GetRootAsModel(tflite_model_buf, 0)
    except AttributeError:
        import tflite.Model
        tflite_model = tflite.Model.Model.GetRootAsModel(tflite_model_buf, 0)

    return relay.frontend.from_tflite(
        tflite_model,
        shape_dict=input_shapes,
        dtype_dict=dtypes
    )


class TVMCompiler(Optimizer):
    """
    The TVM compiler.
    """

    inputtypes = {
        'keras': kerasconversion,
        'onnx': onnxconversion,
        'darknet': darknetconversion,
        'torch': torchconversion,
        'tflite': tfliteconversion
    }

    outputtypes = ['tvm']

    arguments_structure = {
        'modelframework': {
            'argparse_name': '--model-framework',
            'description': 'The input type of the model, framework-wise',
            'default': 'onnx',
            'enum': list(inputtypes.keys())
        },
        'target': {
            'description': 'The kind or tag of the target device',
            'default': 'llvm'
        },
        'target_host': {
            'description': 'The kind or tag of the host (CPU) target device',
            'type': str,
            'default': None,
            'nullable': True
        },
        'opt_level': {
            'description': 'The optimization level of the compilation',
            'default': 2,
            'type': int
        },
        'libdarknetpath': {
            'argparse_name': '--libdarknet-path',
            'description': 'Path to the libdarknet.so library, for darknet models',  # noqa: E501
            'default': '/usr/local/lib/libdarknet.so',
            'type': str
        },
        'use_tvm_vm': {
            'argparse_name': '--compile-use-vm',
            'description': 'At compilation stage use the TVM Relay VirtualMachine',  # noqa: E501
            'type': bool,
            'default': False
        },
        'conversion_func': {
            'argparse_name': '--output-conversion-function',
            'description': 'The type of output conversion function used for PyTorch conversion',  # noqa: E501
            'default': 'default',
            'enum': ['default', 'dict_to_tuple']
        },
        'conv2d_data_layout': {
            'description': 'Configures the I/O layout for the CONV2D operations',  # noqa: E501
            'type': str,
            'default': ''
        },
        'conv2d_kernel_layout': {
            'description': 'Configures the kernel layout for the CONV2D operations',  # noqa: E501
            'type': str,
            'default': ''
        },
        'use_fp16_precision': {
            'argparse_name': '--use-fp16-precision',
            'description': 'Applies conversion of FP32 weights to FP16',
            'type': bool,
            'default': False
        },
        'use_int8_precision': {
            'argparse_name': '--use-int8-precision',
            'description': 'Applies conversion of FP32 weights to INT8',
            'type': bool,
            'default': False
        },
        'use_tensorrt': {
            'argparse_name': '--use-tensorrt',
            'description': 'For CUDA targets: delegates supported operations to TensorRT',  # noqa: E501
            'type': bool,
            'default': False
        },
        'dataset_percentage': {
            'argparse_name': '--dataset-percentage',
            'description': 'Tells how much data from the calibration dataset (training or external) will be used for calibration dataset',  # noqa: E501
            'type': float,
            'default': 0.25
        }
    }

    def __init__(
            self,
            dataset: Dataset,
            compiled_model_path: Path,
            modelframework: str = 'onnx',
            target: str = 'llvm',
            target_host: Optional[str] = None,
            opt_level: int = 2,
            libdarknetpath: str = '/usr/local/lib/libdarknet.so',
            use_tvm_vm: bool = False,
            conversion_func: str = 'default',
            conv2d_data_layout: str = '',
            conv2d_kernel_layout: str = '',
            use_fp16_precision: bool = False,
            use_int8_precision: bool = False,
            use_tensorrt: bool = False,
            dataset_percentage: float = 0.25):
        """
        A TVM Compiler wrapper.

        Parameters
        ----------
        dataset : Dataset
            Dataset object
        compiled_model_path : Path
            Path where compiled model will be saved
        modelframework : str
            Framework of the input model, used to select a proper backend
        target : str
            Target accelerator on which the model will be executed
        target_host : str
            CPU architecture of the target (used when target has a host).
        opt_level : int
            optimization level of compilation
        libdarknetpath : str
            path to the libdarknet.so library, used only during conversion
            of darknet model
        conv2d_data_layout : str
            Data layout to convert the model to.
            Empty if no conversion is necessary.
            This value must be set if conv2d_kernel_layout is set
        conv2d_kernel_layout : str
            Kernel layout to convert the model to.
            Empty if no conversion is necessary.
        use_fp16_precision : bool
            Applies conversion of FP32 weights to FP16
        use_int8_precision : bool
            Applies conversion of FP32 weights to INT8
        use_tensorrt : bool
            Applies transformations moving supported operations to
            TensorRT kernels.
        dataset_percentage : float
            If use_int8_precision is set, the given percentage of samples
            from the training dataset or external calibration dataset is
            used for calibrating the model
        """
        assert not (use_fp16_precision and use_int8_precision), 'Compilation cannot use both FP16 and INT8 conversion'  # noqa: E501
        assert not (use_tensorrt and (use_fp16_precision or use_int8_precision)), 'TensorRT usage with FP16 or INT8 passes is not supported'  # noqa: E501
        assert not (use_tensorrt and ('cuda' not in target)), 'TensorRT is only supported with CUDA target'  # noqa: E501
        self.modelframework = modelframework

        self.target = target
        self.target_obj = tvm.target.Target(target)

        self.target_host = target_host
        self.target_host_obj = (
                tvm.target.Target(target_host) if target_host else None
        )

        self.opt_level = opt_level
        self.libdarknetpath = libdarknetpath
        self.use_tvm_vm = use_tvm_vm
        self.conversion_func = conversion_func
        self.set_input_type(modelframework)
        self.conv2d_data_layout = conv2d_data_layout
        self.conv2d_kernel_layout = conv2d_kernel_layout
        self.use_fp16_precision = use_fp16_precision
        self.use_int8_precision = use_int8_precision
        self.use_tensorrt = use_tensorrt
        self.dataset_percentage = dataset_percentage
        super().__init__(dataset, compiled_model_path)

    @classmethod
    def from_argparse(cls, dataset, args):
        return cls(
            dataset,
            args.compiled_model_path,
            args.model_framework,
            args.target,
            args.target_host,
            args.opt_level,
            args.libdarknet_path,
            args.compile_use_vm,
            args.output_conversion_function,
            args.conv2d_data_layout,
            args.conv2d_kernel_layout,
            args.use_fp16_precision,
            args.use_int8_precision,
            args.use_tensorrt,
            args.dataset_percentage
        )

    def compile_model(self, mod, params, outputpath, io_spec):
        # additional regular optimizations applied to models
        transforms = [
            relay.transform.RemoveUnusedFunctions()
        ]

        if self.use_int8_precision:
            def generator():
                for sample in self.dataset.calibration_dataset_generator(
                        self.dataset_percentage):
                    # TODO add support for any number of inputs
                    assert len(io_spec['input']) == 1, \
                        'Currently only single-input models are supported ' + \
                        'during quantization'
                    yield {io_spec['input'][0]['name']: tvm.nd.array(sample)}
            with relay.quantize.qconfig(
                    calibrate_mode='kl_divergence',
                    weight_scale='max'):
                mod = relay.quantize.quantize(
                    mod,
                    params,
                    dataset=generator()
                )

        if self.use_fp16_precision:
            transforms.append(
                relay.transform.ToMixedPrecision()
            )

        if self.conv2d_data_layout != '' or self.conv2d_kernel_layout != '':
            if self.conv2d_kernel_layout == '':
                self.conv2d_kernel_layout = 'default'
            log = get_logger()
            log.info(
                'Applying ConvertLayout transform:\n' +
                f'DATA LAYOUT   : "{self.conv2d_data_layout}"\n' +
                f'KERNEL LAYOUT : "{self.conv2d_kernel_layout}"'
            )

            if self.conv2d_data_layout == '':
                raise CompilationError(
                    'conv2d_data_layout cannot be empty'
                )
            transforms.append(
                relay.transform.ConvertLayout({
                    "nn.conv2d": [
                        self.conv2d_data_layout, self.conv2d_kernel_layout
                    ],
                    "nn.max_pool2d": [
                        self.conv2d_data_layout, self.conv2d_kernel_layout
                    ],
                    "qnn.conv2d": [
                        self.conv2d_data_layout, self.conv2d_kernel_layout
                    ]
                })
            )

        additional_opts = tvm.transform.Sequential(transforms)

        if self.use_tvm_vm:
            with tvm.transform.PassContext(
                    opt_level=3,
                    disabled_pass=["FoldScaleAxis"]):
                mod = additional_opts(mod)
                vm_exec = relay.vm.compile(
                    mod,
                    target=self.target_obj,
                    params=params
                )
                bytecode, lib = vm_exec.save()
                with open(str(outputpath)+'.ro', 'wb') as file:
                    file.write(bytecode)
                lib.export_library(str(outputpath)+'.so')
        else:
            with tvm.transform.PassContext(opt_level=self.opt_level):
                mod = additional_opts(mod)
                if self.use_tensorrt:
                    from tvm.relay.op.contrib.tensorrt import partition_for_tensorrt  # noqa: E501
                    mod = partition_for_tensorrt(mod, params)
                lib = relay.build(
                    mod,
                    target=self.target_obj,
                    target_host=self.target_host_obj,
                    params=params
                )
            lib.export_library(outputpath)

    def compile(
            self,
            inputmodelpath: Path,
            io_spec: Optional[Dict[str, List[Dict]]] = None):

        if io_spec is None:
            io_spec = self.load_io_specification(inputmodelpath)

        try:
            input_spec = io_spec['input']
        except (TypeError, KeyError):
            raise IOSpecificationNotFoundError('No input specification found')

        inputshapes = {spec['name']: spec['shape'] for spec in input_spec}
        dtypes = {spec['name']: spec['dtype'] for spec in input_spec}

        if not inputshapes:
            raise ValueError('No shapes in the input specification')

        mod, params = self.inputtypes[self.inputtype](
            self,
            inputmodelpath,
            inputshapes,
            dtypes
        )
        self.compile_model(mod, params, self.compiled_model_path, io_spec)
        if self.use_fp16_precision or self.use_int8_precision:
            output_dtype = 'float16' if self.use_fp16_precision else 'int8'
            for id in range(len(io_spec['output'])):
                io_spec['output'][id]['prequantized_dtype'] = io_spec['output'][id]['dtype']  # noqa: E501
                io_spec['output'][id]['dtype'] = output_dtype
        self.save_io_specification(inputmodelpath, io_spec)

    def get_framework_and_version(self):
        return ('tvm', tvm.__version__)
