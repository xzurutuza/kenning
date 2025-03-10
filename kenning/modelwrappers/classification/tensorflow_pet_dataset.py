# Copyright (c) 2020-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

"""
Contains Tensorflow models for the pet classification.

Pretrained on ImageNet dataset, trained on Pet Dataset
"""

from pathlib import Path
import sys
if sys.version_info.minor < 9:
    from importlib_resources import files
else:
    from importlib.resources import files

import tensorflow as tf
import numpy as np

from kenning.core.dataset import Dataset
from kenning.modelwrappers.frameworks.tensorflow import TensorFlowWrapper
from kenning.interfaces.io_interface import IOInterface
from kenning.datasets.pet_dataset import PetDataset
from kenning.resources.models import classification


class TensorFlowPetDatasetMobileNetV2(TensorFlowWrapper):
    default_dataset = PetDataset
    pretrained_modelpath = files(classification) / 'tensorflow_pet_dataset_mobilenetv2.h5'  # noqa: 501
    arguments_structure = {}

    def __init__(
            self,
            modelpath: Path,
            dataset: Dataset,
            from_file=True
    ):
        gpus = tf.config.list_physical_devices('GPU')
        for gpu in gpus:
            tf.config.experimental.set_memory_growth(gpu, True)

        if dataset is not None:
            self.numclasses = dataset.numclasses
            self.mean, self.std = dataset.get_input_mean_std()
            self.class_names = dataset.get_class_names()
        else:
            io_spec = self.load_io_specification(modelpath)
            input_1 = IOInterface.find_spec(io_spec, 'input', 'input_1')
            out_layer = IOInterface.find_spec(io_spec, 'output', 'out_layer')

            self.mean = input_1['mean']
            self.std = input_1['std']
            self.class_names = out_layer['class_names']
            self.numclasses = len(self.class_names)

        super().__init__(
            modelpath,
            dataset,
            from_file
        )

    @classmethod
    def from_argparse(
            cls,
            dataset: Dataset,
            args,
            from_file: bool = True):
        return cls(
            args.model_path,
            dataset,
            from_file
        )

    @classmethod
    def _get_io_specification(cls, numclasses, class_names=None,
                              mean=None, std=None):
        io_spec = {
            'input': [{
                'name': 'input_1',
                'shape': (1, 224, 224, 3),
                'dtype': 'float32',
                'mean': mean,
                'std': std
            }],
            'output': [{
                'name': 'out_layer',
                'shape': (1, numclasses),
                'dtype': 'float32'
            }],
        }
        if class_names is not None:
            io_spec['output'][0]['class_names'] = class_names
        if mean is not None:
            io_spec['input'][0]['mean'] = mean
        if std is not None:
            io_spec['input'][0]['std'] = std
        return io_spec

    @classmethod
    def derive_io_spec_from_json_params(cls, json_dict):
        return cls._get_io_specification(-1)

    def get_io_specification_from_model(self):
        mean = self.mean
        std = self.std
        if isinstance(mean, np.ndarray):
            mean = mean.tolist()
        if isinstance(std, np.ndarray):
            std = std.tolist()
        return self._get_io_specification(self.numclasses, self.class_names,
                                          mean, std)

    def prepare_model(self):
        if self.model_prepared:
            return None
        import tensorflow as tf
        if self.from_file:
            self.load_model(self.modelpath)
            self.model_prepared = True
        else:
            self.base = tf.keras.applications.MobileNetV2(
                input_shape=(224, 224, 3),
                include_top=False,
                weights='imagenet'
            )
            self.base.trainable = False
            avgpool = tf.keras.layers.GlobalAveragePooling2D()(
                self.base.output
            )
            layer1 = tf.keras.layers.Dense(
                1024,
                activation='relu')(avgpool)
            d1 = tf.keras.layers.Dropout(0.5)(layer1)
            layer2 = tf.keras.layers.Dense(
                512,
                activation='relu')(d1)
            d2 = tf.keras.layers.Dropout(0.5)(layer2)
            layer3 = tf.keras.layers.Dense(
                128,
                activation='relu')(d2)
            d3 = tf.keras.layers.Dropout(0.5)(layer3)
            output = tf.keras.layers.Dense(
                self.numclasses,
                name='out_layer'
            )(d3)
            self.model = tf.keras.models.Model(
                inputs=self.base.input,
                outputs=output
            )
            self.model_prepared = True
            self.save_model(self.modelpath)
            self.model.summary()

    def train_model(
            self,
            batch_size: int,
            learning_rate: int,
            epochs: int,
            logdir: Path):
        import tensorflow as tf

        self.prepare_model()

        def preprocess_input(path, onehot):
            data = tf.io.read_file(path)
            img = tf.io.decode_jpeg(data, channels=3)
            img = tf.image.resize(img, [224, 224])
            img = tf.image.convert_image_dtype(img, dtype=tf.float32)
            img /= 255.0
            img = tf.image.random_brightness(img, 0.1)
            img = tf.image.random_contrast(img, 0.7, 1.0)
            img = tf.image.random_flip_left_right(img)
            img = (img - self.mean) / self.std
            return img, tf.convert_to_tensor(onehot)

        Xt, Xv, Yt, Yv = self.dataset.train_test_split_representations(
            0.25
        )
        Yt = self.dataset.prepare_output_samples(Yt)
        Yv = self.dataset.prepare_output_samples(Yv)
        traindataset = tf.data.Dataset.from_tensor_slices((Xt, Yt))
        traindataset = traindataset.map(
            preprocess_input,
            num_parallel_calls=tf.data.experimental.AUTOTUNE
        ).batch(batch_size)
        validdataset = tf.data.Dataset.from_tensor_slices((Xv, Yv))
        validdataset = validdataset.map(
            preprocess_input,
            num_parallel_calls=tf.data.experimental.AUTOTUNE
        ).batch(batch_size)

        tensorboard_callback = tf.keras.callbacks.TensorBoard(
            str(logdir),
            histogram_freq=1
        )

        model_checkpoint_callback = tf.keras.callbacks.ModelCheckpoint(
            filepath=str(logdir),
            monitor='val_categorical_accuracy',
            mode='max',
            save_best_only=True
        )

        self.model.compile(
            optimizer=tf.keras.optimizers.Adam(lr=learning_rate),
            loss=tf.keras.losses.CategoricalCrossentropy(from_logits=True),
            metrics=[
                tf.keras.metrics.CategoricalAccuracy()
            ]
        )

        self.model.fit(
            traindataset,
            epochs=epochs,
            callbacks=[
                tensorboard_callback,
                model_checkpoint_callback
            ],
            validation_data=validdataset
        )
