# M3 Six-Model Controlled Comparison Protocol

**Experiment ID:** `model_screening_v1_20260729`

**Dataset:** `fire_only_curated_manifest_v7`

**Status:** protocol locked before training

## Objective

I will compare six pretrained object-detector configurations under a controlled
fire-only training and evaluation procedure. The goal is not to identify a
universally best detector. I will identify the best observed accuracy-resource
trade-offs among the tested candidates and determine whether their measured
properties support the intended Sentinel and Scout role division.

## Candidates

The four YOLO runs form a 2 x 2 comparison of capacity (`n` versus `s`) and
input resolution (416 versus 640 pixels). SSD-MobileNetV2 provides a
non-YOLO mobile baseline. EfficientDet-Lite0 provides a second independently
designed efficiency-oriented baseline.

The exact machine-readable matrix is
`config/model_screening_matrix_v1_20260729.json`. Any substitution caused by an
unavailable or non-deployable implementation must be recorded before results
are inspected and must retain the intended architecture family.

## Experimental stages

1. Materialize and hash the frozen dataset without changing source files.
2. Verify every framework can load one training batch and produce a valid loss.
3. Run one screening seed (`20260729`) for all six candidates.
4. Calculate validation accuracy, small-object metrics, training time, peak
   VRAM, parameter count, FLOPs where supported, and artifact size.
5. Check exported-model prediction parity before target-hardware benchmarking.
6. Select non-dominated finalists using validation data and declared hardware
   feasibility only.
7. Repeat finalists with seeds `20260729`, `20260803`, and `20260811`.
8. Freeze model/threshold choices and evaluate the test split once.
9. Benchmark deployable finalists on the Sentinel Jetson Nano and, after
   1 September, the Scout VOXL 2.

## Controls

- All candidates use the identical version-7 record split.
- Test images and test metrics cannot influence model, epoch, export, or
  threshold selection.
- Pretrained initialization, framework version, optimizer, learning-rate
  schedule, augmentation, batch size, effective batch, epoch count, stopping
  decision, seed, and checkpoint hash are recorded per run.
- Framework-specific defaults are not described as identical when they differ.
- A model-specific native input size is reported as a deployment comparison,
  not a pure architecture-only comparison.
- Thresholds are selected on validation predictions and then frozen.
- Failed, interrupted, out-of-memory, and restarted runs remain in the run log.

## Frozen input and environment evidence

The source record manifest contains 4,991 images (3,558 training, 700
validation, and 733 test), 2,404 positive images, 2,587 background images, and
3,400 fire boxes. Its SHA-256 is
`478803efb7f8f4f6c3fe74d58658958bccfa2d0f58ec50a1a5c16535e393a7dd`.
The independent YOLO materialization index SHA-256 is
`c3f748b1012d0038bcb8d9f948df1c982863987b32c543b8146efabd69131945`.
The COCO label SHA-256 values are recorded separately for training
(`12e8c94f97ae5f317a24c41c2d9b4f4cb799bb7bca1a420f960e53cf2fc93477`),
validation
(`1a93f800d63bf355bb586039da245cd612cbdd7052102cbfd6da1409312ab7c6`),
and test
(`651e2782db96cbbdf2ba718494f7b57447f96aea6d7719fac350132f1b72a06d`).
These generated datasets are ignored artifacts; their summaries and hashes
provide the reproducibility link to the immutable source manifest.

The Windows YOLO environment is frozen in
`config/model_training_yolo_py312.lock.txt`, and its machine-readable hardware,
framework, and starting-weight evidence is in
`manifests/model_training_environment_v1.json`. GPU training is subject to a
preflight gate: CUDA must execute a kernel, at least 3,000 MiB GPU memory must
be free, initial GPU temperature must be below 70 degrees Celsius, known
GPU-heavy applications must be closed, and full runs require explicit AC-power
confirmation.

## Measurements

Accuracy outputs include precision, recall, F1, AP50, AP50-95, PR curves,
confusion matrices, per-image predictions, and errors stratified by source box
size. Resource outputs include wall-clock training time, per-epoch time, peak
VRAM, checkpoint size, parameter count, FLOPs where available, inference
latency distributions, throughput, RAM, temperature, and power where the
platform exposes them.

The laptop screening latency is a development measurement, not a substitute
for Jetson Nano or VOXL 2 latency. Target-device measurements must include
preprocessing, inference, decoding/NMS, and full-pipeline timing separately.

## Statistical interpretation

Screening runs are exploratory single-seed comparisons. Repeated-finalist
results will report mean, standard deviation, range, and confidence intervals
where justified. Paired image-level comparisons will use the same held-out
records. Statistical significance will not be claimed from one training seed.

## Acceptance and stopping rules

- A candidate must complete dataset loading and loss sanity checks before a
  full run.
- A run with non-finite loss, inconsistent labels, unresolved data leakage, or
  missing configuration evidence is invalid.
- A target export must pass prediction-parity checks before its latency is
  paired with source-model accuracy.
- Finalists are selected from the validation Pareto frontier, considering
  accuracy, false-alert behavior, small-fire recall, latency, memory, and
  artifact size.
- The thesis wording is limited to the best observed candidate under the tested
  conditions.
