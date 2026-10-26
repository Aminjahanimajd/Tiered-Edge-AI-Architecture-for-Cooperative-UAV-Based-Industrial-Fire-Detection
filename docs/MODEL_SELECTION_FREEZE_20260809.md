# Six-Model Validation and Selection Freeze — 9 August 2026

**Access:** `[NO LAB]`

**Status:** frozen before the one authorized test-set evaluation

**Machine-readable freeze SHA-256:**
`5e998b2b2e4bb6f0288266fe925a1da17a963e10fbfbad395f4e5b47aaa4be35`

## Preconditions and evidence state

I completed the standardized validation protocol for all six candidates using
the frozen 700-image validation split (392 fire boxes, 381 background images,
and 307 retained source-family groups). The validation annotation SHA-256 is
`1a93f800d63bf355bb586039da245cd612cbdd7052102cbfd6da1409312ab7c6`.
All thresholds below were selected only on validation data by maximizing
object-level F1 at IoU 0.50. The untouched 733-image test split remained locked
while these decisions were made.

The canonical comparison JSON SHA-256 recorded by the freeze is
`a1424f7717518e76c56caea3d1bd6e1c52fb27f1f175a370898ec460a104eaa8`.
The common evaluator SHA-256 is
`8afc3b528ba55f43392e4e1028509598a13a03bedf36ad115522287d977f7095`.

## Validation results

| Candidate | AP50–95 | AP50 | Threshold | Precision | Recall | F1 | Background FPI | Mean latency (ms) | p95 latency (ms) | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| YOLOv8n-416 | 0.236 | 0.566 | 0.45 | 0.681 | 0.556 | 0.612 | 0.0026 | 9.89 | 13.61 | laptop GPU |
| YOLOv8n-640 | 0.220 | 0.542 | 0.36 | 0.553 | 0.556 | 0.555 | 0.0105 | 7.91 | 10.82 | laptop GPU |
| YOLOv8s-416 | 0.203 | 0.497 | 0.30 | 0.549 | 0.533 | 0.541 | 0.0079 | 11.14 | 20.21 | laptop GPU |
| YOLOv8s-640 | 0.213 | 0.532 | 0.22 | 0.576 | 0.548 | 0.562 | 0.0052 | 10.99 | 14.91 | laptop GPU |
| SSD MobileNet V2 FPNLite-320 | 0.185 | 0.491 | 0.81 | 0.667 | 0.500 | 0.571 | 0.0052 | 27.44 | 37.88 | laptop GPU / native TFOD |
| EfficientDet-Lite0-320 | 0.161 | 0.461 | 0.41 | 0.582 | 0.434 | 0.497 | 0.0000 | 1263.86 | 1386.80 | CPU / XNNPACK |

Each latency distribution contains 700 post-warm-up single-image inference
observations. The timed field is the framework/runtime inference call; it does
not include a common cross-framework preprocessing and decoding boundary.
Values therefore do not isolate architecture speed and must not be mixed with
Jetson Nano or VOXL 2 latency.

## Recovery and data-quality record

The first YOLOv8n-416 producer call exposed one repeated framework-level timing
value and was preserved. The canonical retry invokes one image at a time and
contains 698 distinct inference values among 700 rows. The first SSD evaluation
was also preserved as failed after shape-driven TensorFlow retracing caused
7.5 GB WSL RSS, 94.3% mean host RAM use, and severe swap activity. I corrected
the predictor by defining one dynamic-spatial-dimension input signature. The
canonical SSD retry completed in 67.95 seconds and reported two bounded concrete
function traces rather than continued per-shape retracing. Neither recovery
overwrote the failed or superseded evidence.

## Pareto and role interpretation

For the exploratory two-objective comparison that maximizes validation AP50–95
and minimizes observed mean inference-call latency, YOLOv8n-416 and
YOLOv8n-640 form
the Pareto front. YOLOv8n-416 achieved the highest AP50–95 and precision and
tied YOLOv8n-640 for the highest recall at the validation-selected thresholds.
Consequently, this post-hoc screen identifies YOLOv8n-416 as the strongest
validation candidate for both a recall-oriented Sentinel screen and a
precision-oriented Scout screen under the stated metrics.

This outcome does **not** demonstrate that one model should replace the
hardware-tested pair. The final demonstrated hardware system remains the
YOLOv8n-640 TensorRT Sentinel engine and YOLOv8s-640 TFLite Scout backend. No
new six-model device deployment was performed. The laptop screen therefore
does not support a claim that different model families are intrinsically
optimal for the two roles. The defensible value of the hierarchical edge
architecture must instead come from independent secondary verification,
correlated communication, and heterogeneous deployment evidence.

## Test-opening decision

The test annotation SHA-256 was recorded without using test labels for model or
threshold decisions:
`651e2782db96cbbdf2ba718494f7b57447f96aea6d7719fac350132f1b72a06d`.
The following thresholds and checkpoint lineages are frozen: 0.45, 0.36, 0.30,
0.22, 0.81, and 0.41 for YOLOv8n-416, YOLOv8n-640, YOLOv8s-416,
YOLOv8s-640, SSD, and EfficientDet, respectively.

The only permitted next step is one inference/evaluation pass for all six
frozen candidates. After opening the test split, I will not tune thresholds,
select different checkpoints, retrain models based on test outcomes, or make an
unrecorded evaluator change. A demonstrable evaluator defect will preserve both
the original and corrected outputs.

## Limitations

- One controlled training seed is available per candidate.
- Framework and accelerator paths differ, so laptop inference-call latency is
  runtime-specific.
- Source-family groups are conservative inferences because original session
  identities are incomplete.
- The validation set contains no COCO-small objects at stored resolution;
  relative-area recall is descriptive and does not validate lighter-sized flames.
- This comparison did not deploy all six candidates on either drone.
