"""
Provides a base class for Kenning Flow elements.
"""

from typing import Dict, List, Tuple, Any

from kenning.interfaces.io_interface import IOInterface
from kenning.interfaces.io_interface import IOCompatibilityError
from kenning.utils.args_manager import add_parameterschema_argument


class Runner(IOInterface):
    """
    Represents an operation block in Kenning Flow.
    """

    def __init__(
            self,
            inputs_sources: Dict[str, Tuple[int, str]],
            inputs_specs: Dict[str, Dict],
            outputs: Dict[str, str]):
        """
        Creates the runner.

        Parameters
        ----------
        inputs_sources: Dict[str, Tuple[int, str]]
            Input from where data is being retrieved
        inputs_specs : Dict[str, Dict]
            Specifications of runner's inputs
        outputs: Dict[str, str])
            Outputs of this Runner
        """
        self.inputs_sources = inputs_sources
        self.inputs_specs = inputs_specs
        self.outputs = outputs

        # get input specs mapped to global variables
        runner_input_spec = {}
        runner_io_spec = self.get_io_specification()
        for local_name, (_, global_name) in self.inputs_sources.items():
            for spec in runner_io_spec['input']:
                if spec['name'] == local_name:
                    runner_input_spec[global_name] = spec
                    break

        # get provided inputs spec mapped to global variables
        outputs_specs = {}
        for local_name, (_, global_name) in self.inputs_sources.items():
            outputs_specs[global_name] = self.inputs_specs[local_name]

        if not IOInterface.validate(outputs_specs, runner_input_spec):
            self.cleanup()
            raise IOCompatibilityError(
                f'Input and output are not compatible.\nOutput is:\n'
                f'{outputs_specs}\nInput is:\n{runner_input_spec}\n'
            )

    def cleanup(self):
        """
        Method that cleans resources after Runner is no longer needed
        """
        pass

    def should_close(self) -> bool:
        """
        Method that checks if Runner got some exit indication (exception etc.)
        and the flow should close.

        Returns
        -------
        bool :
            True if there was some exit indication
        """
        return False

    @classmethod
    def _form_parameterschema(cls):
        """
        Wrapper for creating parameterschema structure
        for the DataProvider class.

        Returns
        -------
        Dict :
            schema for the class
        """
        parameterschema = {
            "type": "object",
            "additionalProperties": False
        }

        add_parameterschema_argument(
            parameterschema,
            cls.arguments_structure,
        )

        return parameterschema

    @classmethod
    def from_json(
            cls,
            json_dict: Dict,
            inputs_sources: Dict[str, Tuple[int, str]],
            inputs_specs: Dict[str, Dict],
            outputs: Dict[str, str]):
        """
        Constructor wrapper that takes the parameters from json dict.

        This function checks if the given dictionary is valid according
        to the json schema defined.
        If it is then it invokes the constructor.

        Parameters
        ----------
        json_dict : Dict
            Arguments for the constructor
        inputs_sources: Dict[str, Tuple[int, str]]
            Input from where data is being retrieved
        inputs_specs : Dict[str, Dict]
            Specifications of runner's inputs
        outputs: Dict[str, str])
            Outputs of this Runner

        Returns
        -------
        Runner :
            object of class Runner
        """
        raise NotImplementedError

    def _run(
            self,
            flow_state: List[Dict[str, Any]]):
        """
        Method used to prepare inputs and run this Runner.

        Parameters
        ----------
        flow_state : List[Dict[str, np.ndarray]])
            Current flow state containing all variables used in flow
        """
        # retrieves input values from current flow state based on data
        # saved in input sources (block index and block output name)
        inputs = {input_name: flow_state[block_idx][output_name]
                  for input_name, (block_idx, output_name)
                  in self.inputs_sources.items()}
        local_outputs = self.run(inputs)
        outputs = {}
        for local_name, global_name in self.outputs.items():
            outputs[global_name] = local_outputs[local_name]

        flow_state.append(outputs)

    def run(
            self,
            inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Method used to run this Runner.

        Parameters
        ----------
        inputs : Dict[str, Any]
            Inputs provided to this block

        Returns
        -------
        Dict[str, Any] :
            Output of this block
        """
        raise NotImplementedError
