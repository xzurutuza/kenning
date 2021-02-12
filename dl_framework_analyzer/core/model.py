"""
Provides a wrapper for deep learning models.
"""

from typing import List, Any
from .dataset import Dataset
from .measurements import Measurements, MeasurementsCollector
from .measurements import timemeasurements, systemstatsmeasurements
from collections import defaultdict


class ModelWrapper(object):
    """
    Wraps the given model.
    """

    def __init__(self, dataset: Dataset):
        """
        Creates the model wrapper.

        Parameters
        ----------
        dataset : Dataset
            The dataset to verify the inference
        """
        self.dataset = dataset
        self.data = defaultdict(list)
        self.prepare_model()

    def prepare_model(self):
        """
        Downloads/loads the model.
        """
        return NotImplementedError

    def preprocess_input(self, X: List) -> Any:
        """
        Preprocesses the inputs for a given model before inference.

        By default no action is taken, and the inputs are passed unmodified.

        Parameters
        ----------
        X : List
            The input data from the Dataset object

        Returns
        -------
        Any: the preprocessed inputs that are ready to be fed to the model
        """
        return X

    def _preprocess_input(self, X):
        return self.preprocess_input(X)

    def postprocess_outputs(self, y: Any) -> List:
        """
        Processes the outputs for a given model.

        By default no action is taken, and the outputs are passed unmodified.

        Parameters
        ----------
        y : Any
            The output from the model

        Returns
        -------
        List:
            the postprocessed outputs from the model that need to be in
            format requested by the Dataset object.
        """
        return y

    def _postprocess_outputs(self, y):
        return self.postprocess_outputs(y)

    def run_inference(self, X: List) -> Any:
        """
        Runs inference for a given preprocessed input.

        Parameters
        ----------
        X : List
            The preprocessed inputs for the model

        Returns
        -------
        Any: the results of the inference.
        """
        raise NotImplementedError

    @timemeasurements('inference_step')
    def _run_inference(self, X):
        return self.run_inference(X)

    @systemstatsmeasurements('inferencesysstats')
    @timemeasurements('inference')
    def test_inference(self) -> List:
        """
        Runs the inference with a given dataset.

        Returns
        -------
        List : The inference results
        """

        measurements = Measurements()

        for X, y in iter(self.dataset):
            prepX = self._preprocess_input(X)
            preds = self._run_inference(prepX)
            posty = self._postprocess_outputs(preds)
            measurements += self.dataset.evaluate(posty, y)

        MeasurementsCollector.measurements += measurements

        return measurements
