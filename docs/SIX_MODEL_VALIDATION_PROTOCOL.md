# Six-Model Validation Protocol

**Protocol:** `six_model_validation_v1`

**Access:** `[NO LAB]`

**Status on 9 August 2026:** six-model validation completed and selection frozen;
the one authorized test evaluation is the next permitted action

**Critical restriction:** the test split remains locked until the validation outputs and selection note are complete.

## Purpose

I use one frozen validation split to compare the four YOLO configurations, SSD
MobileNet V2 FPNLite, and EfficientDet-Lite0. This comparison screens predictive
performance and computational cost on the laptop. It does not imply that all six
models were deployed on the drones. The demonstrated hardware system remains the
separate two-model Sentinel--Scout implementation.

The machine-readable contract is
`config/six_model_validation_v1.json`. Its initial audit retained the contract
hash, validation annotation hash, checkpoint hashes, and readiness state in
`artifacts/experiments/model_screening_v1/validation_comparison_v1/contract_status_pre_effdet.json`.

The source-controlled runner is `tools/run_six_model_validation.ps1`. It
hard-codes the frozen validation paths and annotation SHA-256, samples host and
NVIDIA resources every 0.5 seconds, refuses to overwrite partial evidence,
skips only fully completed candidate bundles, and never accepts a test
annotation path. Before execution, I connect the laptop to mains power, close
unrelated GPU and high-load applications, and confirm that no NVIDIA compute
process is active. For EfficientDet, the four output-tensor indices must be
supplied from the retained `inspect_tflite_interface.py` record rather than
inferred from tensor order.

For the final EfficientDet export, the retained positive-image probe identifies
boxes at tensor index 598, classes at 599, scores at 600, and detection count at
601. The input is quantized `uint8` with raw 0--255 pixels supplied directly;
class values are zero-based and are offset by one for the COCO category ID.

## Frozen inputs

- Validation images: 700.
- Fire annotations: 392 across 319 positive images.
- Background images: 381.
- Validation COCO JSON SHA-256:
  `1a93f800d63bf355bb586039da245cd612cbdd7052102cbfd6da1409312ab7c6`.
- Source-family records SHA-256:
  `478803efb7f8f4f6c3fe74d58658958bccfa2d0f58ec50a1a5c16535e393a7dd`.
- Retained validation source-family groups: 307.
- Training/selection seed: 20260729.
- Inference score floor used to retain predictions: 0.001.
- Runtime observations use batch 1 after ten excluded warm-up iterations.
- Confidence selection grid: 0.01 to 0.99 in increments of 0.01.
- Threshold objective: maximum object-level F1 at IoU 0.50; ties are resolved
  by higher recall and then the lower threshold.

The retained prediction floor is lower than the selected operating threshold so
that threshold selection can be reproduced without rerunning inference.

## Common evidence contract

Each model producer writes:

1. `predictions.json` in COCO result format;
2. `latency_ms.csv` with per-image inference observations;
3. `run_summary.json` with the model, checkpoint, dataset, software,
   configuration, timestamps, hashes, and run status;
4. a raw console log retained beside the run.

Before metric calculation, `tools/sanitize_coco_predictions.py` creates a
derived `predictions_evaluable.json` and records every exclusion. The frozen
rule removes only non-finite or nonpositive-width/height COCO boxes; raw
predictions are never edited. The predictor implementations also reject such
degenerate boxes for subsequent runs.

`tools/evaluate_coco_predictions.py` then writes the threshold-independent COCO
metrics and the validation-selected operating point. The evaluator refuses a
test run unless a frozen validation threshold is supplied. A validation run, in
turn, refuses a manually supplied threshold.

## Metrics and matching

The primary predictive metrics are AP50--95 and AP50. At the selected operating
threshold I also report object-level precision, recall, F1, TP, FP, FN, and the
fraction of background images containing at least one prediction. Greedy matching
is confidence-ordered and uses IoU 0.50.

COCO's standard object-size strata are retained. The data audit found **no COCO
small objects in the validation split**: all 392 boxes exceed \(32^2\) pixels at
their stored image resolution. Therefore AP-small cannot support a thesis claim
about lighter-sized flames. To expose size sensitivity without relabelling the
data, I additionally report descriptive ground-truth recall in predeclared
relative-area bins: below 1%, 1--5%, 5--20%, and at least 20% of image area. These
strata remain dataset-specific and do not validate 2 cm lighter flames or
industrial stand-off distances.

Uncertainty intervals for precision, recall, F1, and background-image false
positive rate use a nonparametric percentile bootstrap over the 307 retained
source-family groups, rather than treating all 700 images as independent. The
group identifiers are conservative inferences made during leakage control;
therefore these intervals describe resampling variability within the curated
corpus but cannot correct annotation error, missing capture-session identities,
or source-domain bias.

## Framework-specific inference

- **YOLO:** `tools/predict_yolo_coco.py` loads each retained `best.pt` artifact
  and records Ultralytics preprocessing, inference, and postprocessing timing.
- **SSD:** `tools/predict_tfod_coco.py` restores the latest checkpoint using the
  exact TensorFlow Object Detection API pipeline configuration. This native
  framework path avoids treating a failed conversion as a model-quality result.
- **EfficientDet:** `tools/export_effdet_checkpoint.py` restores the retained
  full-state checkpoint and exports a hashed TFLite artifact.
  `tools/inspect_tflite_interface.py` records the tensor interface before
  `tools/predict_tflite_coco.py` is run with explicit tensor indices.

Framework-specific preprocessing and non-maximum suppression remain part of the
candidate deployment pipeline and are recorded, not silently normalized away.
Laptop latency will be labelled by framework, input size, batch size, and device.
It will not be mixed with Jetson Nano or VOXL 2 latency.

Each candidate command is wrapped by
`tools/run_with_resource_sampling.py`. At 0.5-second intervals the wrapper
records host-wide CPU and RAM, process-tree resident memory where observable,
and NVIDIA GPU utilization, VRAM, temperature, and power. The laptop must be
otherwise idle during a formal run. WSL~2 process resident memory can be
under-reported, so host RAM is the cross-framework memory observation and this
limitation is carried into the comparison.

## Acceptance and failure handling

A candidate passes validation production only if all 700 images receive an
inference record, the run summary reports `completed`, all outputs hash
successfully, and the common evaluator finishes. A failed or interrupted output
directory is preserved and a new uniquely named retry directory is used. A
completed candidate is never rerun merely to make the queue uniform.

If the one authorized EfficientDet recovery does not complete by 10 August, its
best epoch-aligned checkpoint will be evaluated and the run will be classified
as truncated. That classification will be carried into Results, Discussion, and
Limitations.

## Test-opening gate

I will open the test split for model inference only after all of the following
exist:

- six validation results, or an explicit incompatibility/truncation record;
- frozen model and checkpoint hashes;
- frozen validation-selected thresholds;
- a written Pareto and role-suitability selection note;
- a clean evaluator test record and source hash;
- a signed/timestamped test-opening record stating that no further tuning will
  follow inspection of test results.

All gate conditions were satisfied on 9 August 2026. The authoritative
human-readable decision is `docs/MODEL_SELECTION_FREEZE_20260809.md`; the
machine-readable freeze is retained under the validation evidence directory
with SHA-256
`5e998b2b2e4bb6f0288266fe925a1da17a963e10fbfbad395f4e5b47aaa4be35`.
The test split had not been used for inference or metric calculation when this
freeze was created.
