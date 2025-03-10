#!/bin/bash

# Copyright (c) 2020-2023 Antmicro <www.antmicro.com>
#
# SPDX-License-Identifier: Apache-2.0

python3 -m kenning.scenarios.inference_tester \
    kenning.modelwrappers.classification.tensorflow_pet_dataset.TensorFlowPetDatasetMobileNetV2 \
    kenning.datasets.pet_dataset.PetDataset \
    ./build/local-cpu-tvm-tensorflow-classification.json \
    --compiler-cls kenning.compilers.tvm.TVMCompiler \
    --runtime-cls kenning.runtimes.tvm.TVMRuntime \
    --model-path ./kenning/resources/models/classification/tensorflow_pet_dataset_mobilenetv2.h5 \
    --model-framework keras \
    --target "llvm" \
    --compiled-model-path ./build/compiled-model.tar \
    --opt-level 3 \
    --save-model-path ./build/compiled-model.tar \
    --target-device-context cpu \
    --dataset-root ./build/pet-dataset/ \
    --inference-batch-size 1 \
    --download-dataset \
    --verbosity INFO

python3 -m kenning.scenarios.render_report \
    "Pet Dataset classification using TVM-compiled TensorFlow model" \
    docs/source/generated/local-cpu-tvm-tensorflow-classification.md \
    --root-dir docs/source/ \
    --img-dir docs/source/generated/img \
    --report-types performance classification \
    --measurements build/local-cpu-tvm-tensorflow-classification.json
