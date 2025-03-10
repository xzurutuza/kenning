# Copyright (c) 2020-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

import pytest
import kenning
import tempfile
import shutil
from pytest import Metafunc
from typing import Optional
from random import randint, random
from pathlib import Path
from PIL import Image
from kenning.utils.class_loader import load_class
from kenning.core.dataset import Dataset
from dataclasses import dataclass
from argparse import ArgumentParser


@dataclass
class DataFolder:
    """
    A dataclass to store datasetimages fixture properties.

    Parameters
    --------
    path: Path
        A path to data files
    amount: int
        Amount of generated images
    """
    path: Path
    amount: int


class Samples:
    def __init__(self):
        """
        The base class for object samples.
        """
        self._data_index = 0
        self._params = {}
        self.samples = {}
        self.kenning_path = kenning.__path__[0]
        pass

    def add(self):
        """
        Adds object sample.
        """
        raise NotImplementedError

    def get(self, data_name: str):
        """
        Returns object instance for specified key.

        Parameters
        ----------
        data_name: str
            A key for the sample.

        Returns
        -------
        Any:
            Object associated with provided sample.
        """
        args, kwargs = self._params[data_name]
        return self.samples[data_name](*args, **kwargs)

    def __iter__(self):
        """
        Provides iterator over data samples.

        Returns
        -------
        Samples:
            This object.
        """
        self._data_index = 0
        self._samples = tuple(self.samples.keys())
        return self

    def __next__(self):
        """
        Returns next object sample.

        Returns
        -------
        Any:
            Object sample.
        """
        if self._data_index < len(self._samples):
            prev = self._data_index
            self._data_index += 1
            return self._samples[prev]
        raise StopIteration


def pytest_addoption(parser: ArgumentParser):
    """
    Adds argparse options to parser
    """
    parser.addoption(
        '--test-directory',
        action='store',
        default='./build',
        help='Directory used to store files used during test execution'
    )


def pytest_sessionstart(session: pytest.Session):
    """
    Initialize session.
    """
    test_directory = Path(session.config.option.test_directory)
    pytest.test_directory = test_directory
    # only master worker should do init
    if hasattr(session.config, 'workerinput'):
        return
    # do nothing when only collecting tests
    if '--collect-only' in session.config.invocation_params.args:
        return
    (test_directory / 'tmp').mkdir(parents=True, exist_ok=True)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int):
    """
    Cleanup a testing directory once we are finished.
    """
    # only master worker should do cleanup
    if hasattr(session.config, 'workerinput'):
        return
    # do nothing when only collecting tests
    if '--collect-only' in session.config.invocation_params.args:
        return
    test_directory_tmp = pytest.test_directory / 'tmp'
    if test_directory_tmp.exists():
        shutil.rmtree(test_directory_tmp)


def pytest_generate_tests(metafunc: Metafunc):
    """
    Creates parameterscheme structure for the pytest tests
    """
    test_directory = metafunc.config.option.test_directory
    if 'tmpfolder' in metafunc.fixturenames:
        metafunc.parametrize('test_directory', [test_directory],
                             scope='class')


@pytest.fixture(scope='class')
def tmpfolder(test_directory: Optional[Path]) -> Path:
    """
    Creates a temporary directory.
    If `--test-directory` directory is set, temporary folders
    will be created and saved at provided path.

    Parameters
    ----------
    test_directory: Optional[Path]
        Path where files produced by tests should be located at.

    Returns
    -------
    Path: A Path object to temporary directory.
    """
    if test_directory is not None:
        test_directory = Path(test_directory)
        tempfile.tempdir = test_directory / 'tmp'
        test_directory.mkdir(exist_ok=True)
        yield Path(tempfile.mkdtemp())
    else:
        with tempfile.TemporaryDirectory() as tmp_folder:
            yield Path(tmp_folder)


@pytest.fixture()
def modelsamples():
    class ModelData(Samples):
        def __init__(self):
            """
            Model samples.
            Stores paths to models presented in Kenning docs.
            """
            super().__init__()
            self.add("/resources/models/classification/pytorch_pet_dataset_mobilenetv2_full_model.pth",   # noqa: E501
                     'torch',
                     'PyTorchPetDatasetMobileNetV2')
            self.add("/resources/models/classification/pytorch_pet_dataset_mobilenetv2.pth",    # noqa: E501
                     'torch_weights',
                     'PyTorchPetDatasetMobileNetV2')
            self.add("/resources/models/classification/tensorflow_pet_dataset_mobilenetv2.h5",  # noqa: E501
                     'keras',
                     'TensorFlowPetDatasetMobileNetV2')

        def add(self, model_path: str, modelframework: str, modelwrapper: str):
            """
            Adds path to model with associated framework
            and associated modelwrapper name to samples

            Parameters
            ----------
            model_path: str
                The path to the model (Relative to kenning's directory).
            modelframework: str
                The framework model is compatible with.
            modelwrapper: str
                The name of ModelWrapper that is compatible with model.
            """
            model_path = self.kenning_path + model_path
            self.samples[modelframework] = (model_path, modelwrapper)

        def get(self, model_name: str):
            """
            Returns data associated with specified key.

            Parameters
            ----------
            model_name: str
                A key for the sample.

            Returns
            -------
            Tuple[str, str]:
                Tuple with path to model and ModelWrapper name
                it is compatible with.
            """
            return self.samples[model_name]
    return ModelData()


@pytest.fixture()
def optimizersamples(datasetimages: DataFolder, datasetsamples: Samples):
    class OptimizerData(Samples):
        def __init__(self):
            """
            Optimizer samples.
            Stores basic Optimizer objects with its parameters.
            """
            super().__init__()
            self.add('kenning.compilers.tflite.TFLiteCompiler',
                     'default', 'keras', 'tflite',
                     dataset=datasetsamples.get('PetDataset'),
                     compiled_model_path=datasetimages.path)

            self.add('kenning.compilers.tvm.TVMCompiler',
                     'llvm', 'keras', 'so',
                     dataset='PetDataset',
                     compiled_model_path=datasetimages.path)

            self.add('kenning.compilers.tvm.TVMCompiler',
                     'llvm', 'torch', 'so',
                     dataset='PetDataset',
                     compiled_model_path=datasetimages.path)

        def add(self,
                import_path: str,
                target: str,
                modelframework: str,
                filesuffix: str,
                dataset: str = None,
                compiled_model_path: Path = datasetimages.path,
                **kwargs):
            """
            Adds Optimizer class to samples with its parameters.

            Parameters
            ----------
            import_path: str
                The import path optimizer will be imported with.
            target: str
                Target accelerator on which the model will be executed.
            modelframework: str
                Framework of the input model, used to select a proper backend.
            filesuffix: str
                The suffix compiled model should be saved with.
            dataset:Dataset
                Dataset used to train the model - may be used for quantization
                during compilation stage.
            compiled_model_path: Path
                Path where compiled model will be saved.
            """
            optimizer = load_class(import_path)
            optimizer_name = import_path.rsplit('.')[-1] + '_' + modelframework
            file_name = optimizer_name + '.' + filesuffix
            compiled_model_path = compiled_model_path / file_name
            self._params[optimizer_name] = (
                (dataset, compiled_model_path),
                {
                    'target': target,
                    'modelframework': modelframework,
                    **kwargs
                }
            )
            self.samples[optimizer_name] = optimizer
    return OptimizerData()


@pytest.fixture()
def modelwrappersamples(datasetsamples: Samples, modelsamples: Samples):
    class WrapperData(Samples):
        def __init__(self):
            """
            ModelWrapper samples.
            Stores parameters for ModelWrapper objects creation.
            """
            super().__init__()
            torch_pet_mobilenet_import_path = "kenning.modelwrappers.classification.pytorch_pet_dataset.PyTorchPetDatasetMobileNetV2"    # noqa: E501
            tensorflow_pet_mobilenet_import_path = "kenning.modelwrappers.classification.tensorflow_pet_dataset.TensorFlowPetDatasetMobileNetV2"  # noqa: E501

            self.add(
                torch_pet_mobilenet_import_path,
                modelsamples.get('torch_weights')[0],
                dataset=datasetsamples.get('PetDataset')
            )

            self.add(
                tensorflow_pet_mobilenet_import_path,
                modelsamples.get('keras')[0],
                dataset=datasetsamples.get('PetDataset')
            )

        def add(self, import_path: str, model: str,
                dataset: Dataset = None, from_file: bool = True, **kwargs):
            """
            Adds ModelWrapper class to samples with its parameters.

            Parameters
            ----------
            import_path: str
                The import path modelwrapper will be imported with.
            model: str
                The path to modelwrapper's model.
            dataset: Dataset
                The dataset to verify inference.
            from_file: bool
                True if model should be loaded from file.
            """
            wrapper = load_class(import_path)
            wrapper_name = import_path.rsplit('.')[-1]
            self._params[wrapper_name] = ((model, dataset),
                                          {'from_file': from_file, **kwargs})
            self.samples[wrapper_name] = wrapper
    return WrapperData()


@pytest.fixture()
def datasetsamples(datasetimages: DataFolder):
    class DatasetData(Samples):
        def __init__(self):
            """
            Dataset samples.
            Stores parameters for dataset objects creation.
            """
            super().__init__()
            self.add("kenning.datasets.pet_dataset.PetDataset")

        def add(self, import_path: str, datapath: Path = datasetimages.path,
                batch_size: int = 1, download_dataset: bool = False, **kwargs):
            """
            Adds Dataset class to samples with its parameters.

            Parameters
            ----------
            import_path: str
                The import path dataset will be imported with.
            datapath: Path
                The path to dataset data.
            batch_size: int
                The dataset batch size.
            download_dataset: bool
                True if dataset should be downloaded first.

            Returns
            -------
            Dataset: Class Dataset.
            """
            dataset = load_class(import_path)
            dataset_name = import_path.rsplit('.')[-1]
            self._params[dataset_name] = ((datapath, ), {
                'batch_size': batch_size,
                'download_dataset': download_dataset,
                **kwargs}
            )
            self.samples[dataset_name] = dataset
    return DatasetData()


@pytest.fixture(scope='class')
def datasetimages(tmpfolder: Path) -> DataFolder:
    """
    Creates a temporary dir with images and data files.
    Images are located under 'image/' folder.

    Parameters
    ----------
    tmpfolder: Path
        A temporary folder

    Returns
    -------
    DataFolder: A DataFolder object that stores path to data and images amount
    """
    images_amount = 148
    (tmpfolder / 'images').mkdir()
    (tmpfolder / 'img').symlink_to(tmpfolder / 'images')
    (tmpfolder / 'annotations').mkdir()
    (tmpfolder / 'annotations' / 'list.txt').touch()
    write_to_dirs(tmpfolder, images_amount)

    for i in range(images_amount):
        file = (tmpfolder / 'images' / f'image_{i}.jpg')
        color = (randint(0, 255), randint(0, 255), randint(0, 255))
        img = Image.new(mode='RGB', size=(5, 5), color=color)
        img.save(file, 'JPEG')

    return DataFolder(tmpfolder, images_amount)


def write_to_dirs(path, amount):
    """
    Creates files under provided 'path' such as 'list.txt' for PetDataset,
    'annotations.csv' and 'classnames.csv' for OpenImagesDataset.

    Parameters
    --------
    path: Path
        The Path to where data have to be located
    amount: int
        Amount of images are being written to data files
    """
    def three_random_one_hot(i):
        return f'{i%37+1} {randint(0, 1)} {randint(0, 1)}'

    def four_random():
        return f'{random()},{random()},{random()},{random()}'

    with open(path / 'annotations' / 'list.txt', 'w') as f:
        [print(f'image_{i} {three_random_one_hot(i)}', file=f)
         for i in range(amount)]

    with open(path / 'classnames.csv', 'w') as f:
        print('/m/o0fd,person', file=f)

    with open(path / 'annotations.csv', 'w') as f:
        title = 'ImageID,Source,LabelName,Confidence,XMin,XMax,YMin,YMax,'
        title += 'IsOccluded,IsTruncated,IsGroupOf,IsDepiction,IsInside'
        print(title, file=f)
        [print(f'image_{i},xclick,/m/o0fd,1,{four_random()},0,0,0,0,0', file=f)
            for i in range(amount)]
