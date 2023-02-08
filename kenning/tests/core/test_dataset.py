import pytest
from typing import Type, Final
import os
import shutil

from kenning.core.dataset import Dataset, CannotDownloadDatasetError
from kenning.datasets import *  # noqa: 401, 403
from kenning.tests.core.conftest import get_all_subclasses
from kenning.tests.core.conftest import get_dataset
from kenning.tests.core.conftest import get_dataset_download_path


DATASET_SUBCLASSES: Final = get_all_subclasses(Dataset)


class TestDataset:
    @pytest.mark.parametrize('dataset_cls', [
        pytest.param(dataset_cls, marks=[
            pytest.mark.xdist_group(name=f'TestDataset_{dataset_cls.__name__}')
        ])
        for dataset_cls in DATASET_SUBCLASSES
    ])
    def test_folder_does_not_exist(self, dataset_cls: Type[Dataset]):
        dataset_download_dir = get_dataset_download_path(dataset_cls)
        if os.path.isdir(dataset_download_dir):
            shutil.rmtree(dataset_download_dir)

        try:
            dataset = dataset_cls(dataset_download_dir, download_dataset=False)
            dataset.prepare()
            assert len(dataset.dataX) > 0
        except FileNotFoundError:
            pass
        except Exception as e:
            pytest.fail(f'Exception {e}')

    @pytest.mark.parametrize('dataset_cls', [
        pytest.param(dataset_cls, marks=[
            pytest.mark.dependency(
                name=f'test_download[{dataset_cls.__name__}]'
            ),
            pytest.mark.xdist_group(name=f'TestDataset_{dataset_cls.__name__}')
        ])
        for dataset_cls in DATASET_SUBCLASSES
    ])
    def test_download(self, dataset_cls: Type[Dataset]):
        dataset_download_dir = get_dataset_download_path(dataset_cls)
        if os.path.isdir(dataset_download_dir):
            shutil.rmtree(dataset_download_dir)

        try:
            dataset = dataset_cls(dataset_download_dir, download_dataset=True)
            assert len(dataset.dataX) > 0
        except CannotDownloadDatasetError:
            pytest.xfail('Cannot download dataset.')
        except Exception as e:
            pytest.fail(f'Exception {e}')

    @pytest.mark.parametrize('dataset_cls', [
        pytest.param(dataset_cls, marks=[
            pytest.mark.dependency(
                depends=[f'test_download[{dataset_cls.__name__}]']
            ),
            pytest.mark.xdist_group(name=f'TestDataset_{dataset_cls.__name__}')
        ])
        for dataset_cls in DATASET_SUBCLASSES
    ])
    def test_iterator(self, dataset_cls: Type[Dataset]):
        try:
            dataset = get_dataset(dataset_cls)
            assert len(dataset.dataX) > 0
        except CannotDownloadDatasetError:
            pytest.xfail('Cannot download dataset.')
        except Exception as e:
            pytest.fail(f'Exception {e}')

        for i, (x, y) in enumerate(dataset):
            assert x is not None
            assert y is not None
            if i > 10:
                break

        assert len(dataset) > 0
