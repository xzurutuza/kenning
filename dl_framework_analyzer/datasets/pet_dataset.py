"""
The Oxford-IIIT Pet Dataset wrapper
"""

import tempfile
from pathlib import Path
import tarfile
from PIL import Image
import numpy as np

from dl_framework_analyzer.core.dataset import Dataset
from dl_framework_analyzer.utils.logger import download_url
from dl_framework_analyzer.core.measurements import Measurements


class PetDataset(Dataset):
    """
    The Oxford-IIIT Pet Dataset

    Omkar M Parkhi and Andrea Vedaldi and Andrew Zisserman and C. V. Jawahar

    It is a classification dataset with 37 classes, where 12 classes represent
    cat breeds, and the remaining 25 classes represent dog breeds.

    It is a seemingly balanced dataset breed-wise, with around 200 images
    examples per class.

    There are 7349 images in total, where 2371 images are cat images, and the
    4978 images are dog images.

    *License*: Creative Commons Attribution-ShareAlike 4.0 International
    License.

    *Page*: `Pet Dataset site <https://www.robots.ox.ac.uk/~vgg/data/pets/>`_.

    The images can be either classified by species (2 classes)
    or breeds (37 classes).

    The affinity of images to classes is taken from annotations, but the class
    IDs are starting from 0 instead of 1, as in the annotations.
    """
    def __init__(
            self,
            root: Path,
            batch_size: int = 1,
            download_dataset: bool = False,
            classify_by='breeds',
            standardize: bool = True):
        """
        Prepares all structures and data required for providing data samples.

        The object of classification can be either breeds (37 classes) or
        species (2 classes).

        Parameters
        ----------
        root : Path
            The path to the dataset data
        batch_size : int
            The batch size
        download_dataset : bool
            True if dataset should be downloaded first
        classify_by : str
            Determines what should be the object of classification.
            The valid values are "species" and "breeds".
        standardize : bool
            Standardize the given input samples.
            Should be set to False when using compute_input_mean_std
        """
        assert classify_by in ['species', 'breeds']
        self.classify_by = classify_by
        self.numclasses = None
        self.classnames = dict()
        self.standardize = standardize
        if standardize:
            self.mean, self.std = self.get_input_mean_std()
        super().__init__(root, batch_size, download_dataset)

    @classmethod
    def form_argparse(cls):
        parser, group = super().form_argparse()
        group.add_argument(
            '--classify-by',
            help='Determines if classification should be performed by species or by breeds',  # noqa: E501
            choices=['species', 'breeds'],
            default='breeds'
        )
        return parser, group

    @classmethod
    def from_argparse(cls, args):
        return cls(
            args.dataset_root,
            args.inference_batch_size,
            args.download_dataset,
            args.classify_by
        )

    def download_dataset(self):
        self.root.mkdir(parents=True, exist_ok=True)
        imgs = 'https://www.robots.ox.ac.uk/~vgg/data/pets/data/images.tar.gz'
        anns = 'https://www.robots.ox.ac.uk/~vgg/data/pets/data/annotations.tar.gz'  # noqa: E501
        with tempfile.TemporaryDirectory() as tmpdir:
            tarimgspath = Path(tmpdir) / 'dataset.tar.gz'
            tarannspath = Path(tmpdir) / 'annotations.tar.gz'
            download_url(imgs, tarimgspath)
            download_url(anns, tarannspath)
            tf = tarfile.open(tarimgspath)
            tf.extractall(self.root)
            tf = tarfile.open(tarannspath)
            tf.extractall(self.root)

    def prepare(self):
        with open(self.root / 'annotations' / 'list.txt', 'r') as datadesc:
            for line in datadesc:
                if line.startswith('#'):
                    continue
                fields = line.split(' ')
                self.dataX.append(
                    str(self.root / 'images' / (fields[0] + '.jpg'))
                )
                if self.classify_by == 'species':
                    self.dataY.append(int(fields[2]) - 1)
                else:
                    self.dataY.append(int(fields[1]) - 1)
                    clsname = fields[0].rsplit('_', 1)[0]
                    if not self.dataY[-1] in self.classnames:
                        self.classnames[self.dataY[-1]] = clsname
                    assert self.classnames[self.dataY[-1]] == clsname
            if self.classify_by == 'species':
                self.numclasses = 2
                assert min(self.dataY) == 0
                assert max(self.dataX) == self.numclasses - 1
                self.classnames = {
                    0: 'cat',
                    1: 'dog'
                }
            else:
                self.numclasses = len(self.classnames)

    def prepare_input_samples(self, samples):
        result = []
        for sample in samples:
            img = Image.open(sample)
            img = img.convert('RGB')
            img = img.resize((224, 224))
            npimg = np.array(img) / 255.0
            if self.standardize:
                npimg = (npimg - self.mean) / self.std
            result.append(npimg)
        return result

    def prepare_output_samples(self, samples):
        return list(np.eye(self.numclasses)[samples])

    def evaluate(self, predictions, truth):
        confusion_matrix = np.zeros((self.numclasses, self.numclasses))
        top_5_count = 0
        for prediction, label in zip(predictions, truth):
            confusion_matrix[np.argmax(label), np.argmax(prediction)] += 1
            top_5_count += 1 if np.argmax(label) in np.argsort(prediction)[::-1][:5] else 0  # noqa: E501
        measurements = Measurements()
        measurements.accumulate(
            'eval_confusion_matrix',
            confusion_matrix,
            lambda: np.zeros((self.numclasses, self.numclasses))
        )
        measurements.accumulate('top_5_count', top_5_count, lambda: 0)
        measurements.accumulate('total', len(predictions), lambda: 0)
        return measurements

    def compute_input_mean_std(self):
        count = 0
        mean = np.zeros((3))
        std = np.zeros((3))
        for X, _ in iter(self):
            for img in X:
                mean += np.mean(img, axis=(0, 1))
                std += np.std(img, axis=(0, 1))
                count += 1
        mean /= count
        std /= count
        return mean, std

    def get_input_mean_std(self):
        return np.array([0.48136492, 0.44937421, 0.39576963]), np.array([0.22781384, 0.22496867, 0.22693157])  # noqa: E501
