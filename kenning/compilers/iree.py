"""
Wrapper for IREE compiler
"""
from pathlib import Path
from typing import Dict, Tuple, List
import re

from kenning.core.optimizer import Optimizer
from kenning.core.dataset import Dataset


# TODO: Add support for tflite models

def keras_model_parse(model_path, input_shapes, dtype):
    import tensorflow as tf

    # Calling the .fit() method of keras model taints the state of the model in some way,
    # breaking the IREE compiler. Because of that, the workaround is needed.
    original_model = tf.keras.models.load_model(model_path)
    model = tf.keras.models.clone_model(original_model)
    model.set_weights(original_model.get_weights())
    del original_model

    inputspec = []
    for input_layer in model.inputs:
        inputspec.append(tf.TensorSpec(input_shapes[input_layer.name], dtype))

    class WrapperModule(tf.Module):
        def __init__(self):
            super().__init__()
            self.m = model
            self.m.predict = lambda *args: self.m(*args, training=False)
            self.predict = tf.function(
                input_signature=inputspec
            )(self.m.predict)

    return WrapperModule()


def tf_model_parse(model_path, input_shapes, dtype):
    import tensorflow as tf
    model = tf.saved_model.load(model_path)

    # Assuming that the names of input layers contains single ID number, and the order of the
    # inputs are according to their IDs.
    layer_order = {}
    for name in input_shapes.keys():
        layer_id = int(re.search(r"\d+", name).group(0))
        layer_order[name] = layer_id
    ordered_layers = sorted(list(input_shapes.keys()), key=layer_order.get)
    ordered_shapes = [input_shapes[layer] for layer in ordered_layers]

    inputspec = []
    for shape in ordered_shapes:
        inputspec.append(tf.TensorSpec(shape, dtype))

    model.predict = tf.function(
        input_signature=inputspec
    )(lambda *args: model(*args))
    return model


def tflite_model_parse(model, input_shape, dtype):
    raise NotImplementedError  # TODO


backend_convert = {
    # CPU backends
    'dylib': 'dylib-llvm-aot',
    'vmvx': 'vmvx',
    # GPU backends
    'vulkan': 'vulkan-spirv',
    'cuda': 'cuda'
}

class IREECompiler(Optimizer):
    """
    IREE compiler
    """

    inputtypes = {
        'keras': keras_model_parse,
        'tf': tf_model_parse,
        'tflite': tflite_model_parse
    }

    outputtypes = []

    arguments_structure = {
        'modelframework': {
            'argparse_name': '--model-framework',
            'description': 'The input type of the model, framework-wise',
            'default': 'keras',
            'enum': list(inputtypes.keys())
        },
        'backend': {
            'argparse_name': '--backend',
            'description': 'Name of the backend that will run the compiled module',
            'required': True,
            'enum': list(backend_convert.keys())
        },
        'compiler-args': {
            'argaprse_name': '--compiler-args',
            'description': 'Additional options that are passed to compiler',
            'default': None,
            'is_list': True
        }
    }

    def __init__(
            self,
            dataset: Dataset,
            compiled_model_path: Path,
            modelframework: str,
            backend: str,
            compiler_args: List[str] = None):
        """
        IREE compiler

        Parameters
        ----------
        dataset : Dataset
            Dataset used to train the model - may be used for quantization
            during compilation stage
        compiled_model_path : Path
            Path where compiled model will be saved
        modelframework : str
            Framework of the input model
        backend : str
            Backend on which the model will be executed
        compiled_args : List[str]
            Additional arguments for the compiler. Every options should be in a
            separate string, which should be formatted like this: <option>=<value>,
            or <option> for flags (example: 'iree-cuda-llvm-target-arch=sm_60').
            Full list of options can be listed by running 'iree-compile -h'.
        """
        if modelframework in ("keras", "tf"):
            from iree.compiler import tf as ireecmp
        elif modelframework == "tflite":
            from iree.compiler import tflite as ireecmp
        else:
            raise RuntimeError(f"Unsupported model_framework. Choose from {list(self.inputtypes.keys())}.")

        self.model_load = self.inputtypes[modelframework]
        self.ireecmp = ireecmp
        self.model_framework = modelframework
        self.backend = backend_convert.get(backend, backend)
        if compiler_args is not None:
            self.compiler_args = [f"--{option}" for option in compiler_args]
        else:
            self.compiler_args = []
        super().__init__(dataset, compiled_model_path)

    @classmethod
    def from_argparse(cls, dataset, args):
        return cls(
            dataset,
            args.compiled_model_path,
            args.model_framework,
            args.backend
        )

    def compile(
            self,
            inputmodelpath: Path,
            inputshapes: Dict[str, Tuple[int, ...]],
            dtype: str = 'float32'):

        model = self.model_load(inputmodelpath, inputshapes, dtype)
        self.ireecmp.compile_module(
            model,
            output_file=self.compiled_model_path,
            extra_args=self.compiler_args,
            exported_names=['predict'],
            target_backends=[self.backend]
        )

    def get_framework_and_version(self):
        module_path = Path(self.ireecmp.__file__)
        version_text = (module_path.parents[1] / "version.py").read_text()
        version = re.search(r'VERSION = "[\d.]+"', version_text)
        return "iree", version.group(0).split()[-1].strip('"')
