# One-Time Six-Model Test Evaluation — 9 August 2026

## Status and access

- **Access:** `[NO LAB]`
- **Status:** completed without test-driven tuning
- **Test opened (UTC):** `2026-08-09T10:35:35.6769738Z`
- **Selection-freeze SHA-256:**
  `5e998b2b2e4bb6f0288266fe925a1da17a963e10fbfbad395f4e5b47aaa4be35`
- **Test-annotation SHA-256:**
  `651e2782db96cbbdf2ba718494f7b57447f96aea6d7719fac350132f1b72a06d`
- **Test set:** 733 images, 503 fire boxes, 354 positive images, 379
  background images, and 306 inferred source groups

The test split was opened only after validation thresholds, checkpoints,
class mapping, and the selection interpretation had been frozen. The retained
opening record commits to no threshold tuning, checkpoint reselection, or
test-driven retraining.

## Reproducible interface

The controlled entry point is:

```powershell
powershell -ExecutionPolicy Bypass -File tools/run_six_model_test.ps1
```

The runner verifies the frozen selection record and test-annotation hashes,
refuses silent overwrites, applies the six validation-selected thresholds, and
retains predictions, per-image latency, grouped bootstrap summaries, metric
reports, and hashes. The runner SHA-256 at execution was:

`8bf6916f44e494a4c3349ffef398cc883953079b5a57ab8a82844fba527cd8c0`.

The consolidated comparison is stored under
`artifacts/experiments/model_screening_v1/test_comparison_v1/`.
The comparison CSV SHA-256 is
`8605eb6accfd948bae7b2c4890d3f6c834724cdc9c2177eb1ee4465912d32198`.

## Frozen-threshold results

| Candidate | Threshold | AP50–95 | AP50 | Precision | Recall | F1 | Background FPI |
|---|---:|---:|---:|---:|---:|---:|---:|
| YOLOv8n-416 | 0.45 | 0.119 | 0.303 | 0.541 | 0.300 | 0.386 | 0.0554 |
| YOLOv8n-640 | 0.36 | 0.101 | 0.260 | 0.409 | 0.274 | 0.329 | 0.0396 |
| YOLOv8s-416 | 0.30 | 0.130 | 0.319 | 0.508 | 0.320 | 0.393 | 0.0792 |
| YOLOv8s-640 | 0.22 | 0.133 | 0.359 | 0.545 | 0.328 | 0.409 | 0.0343 |
| SSD MobileNet V2 FPNLite-320 | 0.81 | 0.114 | 0.303 | 0.546 | 0.237 | 0.330 | 0.0554 |
| EfficientDet-Lite0-320 | 0.41 | 0.168 | 0.403 | 0.679 | 0.328 | 0.442 | 0.0343 |

The 95% grouped-bootstrap F1 intervals were `[0.236, 0.544]`,
`[0.175, 0.450]`, `[0.236, 0.537]`, `[0.245, 0.545]`,
`[0.162, 0.479]`, and `[0.274, 0.596]` in table order. They are
descriptive intervals over the retained inferred source groups and do not
correct source-domain bias, annotation error, or the single-seed design.

## Recovery record

The first invocation completed YOLOv8n-416 inference, then stopped during
post-processing because of a Windows-to-WSL path-normalization defect. The raw
predictions and latency file were retained unchanged. I corrected only the
artifact-level path handling and made post-processing idempotent. The original
YOLOv8n-416 predictions were then evaluated without rerunning inference. The
remaining five candidates completed through the frozen runner. No model,
checkpoint, threshold, prediction, or ground-truth record was changed in this
recovery.

## Engineering interpretation

EfficientDet-Lite0 ranked first on test AP50–95, precision, and F1, despite
ranking last on validation AP50–95. This post-test rank reversal is evidence
of split/domain sensitivity, not permission to reselect the deployed system.
The validation-frozen interpretation and the experimentally demonstrated
hardware pair remain unchanged: the final Sentinel used the distinct
YOLOv8n-640 TensorRT engine, and the Scout used YOLOv8s-640 TFLite.

The common test results establish an exploratory comparison under one frozen
split and one training seed. They do not establish a universally best model
family. Laptop inference-call latency is not a substitute for Jetson Nano or VOXL 2
deployment latency and must remain in a separately labelled comparison.

## Limitations

- The stored-resolution test annotations contain only three COCO-small boxes;
  AP-small therefore cannot support a general small-object claim.
- A separate relative-area stratum contains 54 boxes occupying less than 1%
  of image area, but this is a different descriptive definition.
- The test-set labels may not be used for further threshold selection,
  checkpoint choice, or retraining in this thesis experiment.
- The grouped bootstrap uses inferred source families because original capture
  session identities were unavailable.
- The six runtime paths used different frameworks and devices; their latency
  comparison measures observed pipelines rather than architecture-only speed.

## Acceptance decision

**Pass.** All six frozen candidates produced predictions and comparable held-
out metrics; output hashes were retained; the recovery preserved original raw
evidence; and no post-test tuning or model reselection occurred.
